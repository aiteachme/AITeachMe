from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.metrics import DigestTokenSummary
from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
from app.workflows.digest.docgen import graph
from app.workflows.digest.docgen.lib import chapter_planning, document_backbone as document_backbone_lib, quality, repair
from app.workflows.digest.docgen.lib.document_backbone import build_document_backbone as build_document_backbone_value
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    CanonicalClaim,
    CanonicalGlossaryItem,
    AssetManifest,
    ChapterExecutionBrief,
    ChapterDraft,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    ChapterReviewReport,
    ChapterSourceSlice,
    ConceptDependencyEdge,
    DocGenContext,
    DocGenIntentProfile,
    DocumentBackbone,
    DocumentPreparationBundle,
    DocumentConsistencyReport,
    EnhancedChapterDraft,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    LLMDocumentConsistencyReviewResult,
    LockedChapterTitle,
    RepairTraceItem,
    ReviewAction,
    ReviewedChapterDraft,
    PracticeManifest,
    SourceAffinityByChapter,
)
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_chapter_kg_refinement_item,
    build_chapters_enhanced,
    build_dispatch_table,
    build_docgen_kg_draft,
    build_guideline,
    build_intent_enhanced,
    build_preliminary_kg,
    build_summary_enhanced,
    build_user_profile_enhanced,
)
from app.workflows.digest.docgen.lib.pipeline_context import learner_profile_text_for_branch
from app.workflows.digest.docgen.lib.reporting import build_docgen_lane_summary
from app.workflows.digest.docgen.nodes import generate_chapters
from app.workflows.digest.docgen.nodes import (
    build_document_backbone,
    build_chapter_execution_briefs,
    enhance_chapters,
    generate_cover,
    lock_titles_for_chapters,
    prepare_global_seed,
    prepare_knowledge_graph,
    repair_or_route,
    review_content,
)
from app.workflows.digest.kg_doc_sync.lib.models import (
    PendingMarkdownExtractedEdge,
    SectionExtractionContext,
    SectionExtractionPayload,
    SectionExtractionRecord,
)


def test_initial_state_exposes_explicit_docgen_pipeline_artifacts() -> None:
    state = graph.create_docgen_initial_state(
        course_id="course_state_contract",
        course_name="线性代数",
        file_ids=[],
        user_prompt="构建系统课程",
        requested_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
        build_session_id="build-1",
    )

    assert state["intent_enhanced"] == {}
    assert state["user_profile"] == {}
    assert state["summary_enhanced"] == {}
    assert state["chapters_enhanced"] == []
    assert state["guideline"] == {}
    assert state["dispatch_table"] == {}
    assert state["preliminary_kg"] == {}
    assert state["kg_refinement_items"] == []
    assert state["docgen_kg_draft"] == {}
    assert state["kg_draft_early_persist_metrics"] == {}
    assert state["kg_draft_rollback_metrics"] == {}


def test_document_backbone_does_not_promote_planner_coverage_text_to_semantic_units() -> None:
    term = "逻辑运算符&& || !的条件真值与优先级"
    backbone, _ = build_document_backbone_value(
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="变量与数据类型",
                required_elements=["变量声明与定义"],
            ),
            ChapterGenerationTaskSeed(
                chapter_index=2,
                confirmed_title="流程控制",
                required_elements=[term],
            ),
        ],
        agenda=BackboneResearchAgenda(glossary_candidates=[term]),
        evidence_units=[],
        file_summaries=[],
    )

    assert backbone.canonical_glossary == []
    assert backbone.canonical_claim_pool == []
    assert backbone.concept_dependency_graph == []


@pytest.mark.anyio
async def test_document_backbone_uses_one_llm_slot_and_preserves_measured_source_stats(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_completion(messages, **kwargs):
        captured["messages"] = messages
        captured["response_model"] = kwargs.get("response_model")
        return DocumentPreparationBundle(
            document_backbone=DocumentBackbone(
                canonical_glossary=[
                    CanonicalGlossaryItem(
                        term="行列配对",
                        definition="矩阵乘法中对应行与列的元素配对求积后相加。",
                        source_hint="notes.md/s1",
                        target_chapters=[1],
                    )
                ],
                source_trust_summary={"model_supplied": True},
            ),
            chapter_execution_briefs=[
                ChapterExecutionBrief(
                    chapter_index=1,
                    teaching_outline=["先解释维度条件，再演示行列配对"],
                    writing_instructions=["使用资料中的矩阵算例，并给出一次维度不匹配反例。"],
                    concept_targets=["行列配对"],
                    retrieval_queries=[
                        "矩阵乘法 行列配对",
                        "矩阵乘法 维度条件",
                        "矩阵乘法 反例",
                    ],
                )
            ],
        )

    monkeypatch.setattr(document_backbone_lib, "acompletion_with_fallback", fake_completion)

    backbone, briefs, warnings = await document_backbone_lib.generate_document_backbone(
        course_name="线性代数",
        digest_mode="systematic",
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="矩阵乘法",
                required_elements=["行列配对"],
            )
        ],
        agenda=BackboneResearchAgenda(glossary_candidates=["行列配对"]),
        evidence_units=[
            HighConfidenceEvidenceUnit(
                evidence_id="e1",
                text="矩阵乘法按行列配对求和。",
                source_ref="local://file/f1/section/s1",
                source_type="local",
                confidence=0.9,
            )
        ],
        file_summaries=[FileMaterialSummary(file_id="f1", filename="notes.md")],
        max_retrieval_queries_per_chapter=2,
    )

    assert captured["response_model"] is DocumentPreparationBundle
    assert backbone.canonical_glossary[0].term == "行列配对"
    assert backbone.source_trust_summary == {
        "evidence_unit_count": 1,
        "source_type_counts": {"local": 1},
        "avg_evidence_confidence": 0.9,
        "file_summary_count": 1,
    }
    assert backbone.fallback_used is False
    assert briefs[0].teaching_outline == ["先解释维度条件，再演示行列配对"]
    assert briefs[0].writing_instructions == ["使用资料中的矩阵算例，并给出一次维度不匹配反例。"]
    assert briefs[0].retrieval_queries == ["矩阵乘法 行列配对", "矩阵乘法 维度条件"]
    assert "retrieval_queries 每章最多 2 条" in captured["messages"][1]["content"]
    assert warnings == []


@pytest.mark.anyio
async def test_document_preparation_rejects_duplicate_brief_indices_and_falls_back(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        del args, kwargs
        return DocumentPreparationBundle(
            document_backbone=DocumentBackbone(),
            chapter_execution_briefs=[
                ChapterExecutionBrief(chapter_index=1),
                ChapterExecutionBrief(chapter_index=1),
            ],
        )

    monkeypatch.setattr(document_backbone_lib, "acompletion_with_fallback", fake_completion)

    backbone, briefs, warnings = await document_backbone_lib.generate_document_backbone(
        course_name="线性代数",
        digest_mode="systematic",
        task_seeds=[
            ChapterGenerationTaskSeed(chapter_index=1, confirmed_title="矩阵"),
            ChapterGenerationTaskSeed(chapter_index=2, confirmed_title="线性映射"),
        ],
        agenda=BackboneResearchAgenda(),
        evidence_units=[],
        file_summaries=[],
    )

    assert backbone.fallback_used is True
    assert [brief.chapter_index for brief in briefs] == [1, 2]
    assert all(brief.fallback_used for brief in briefs)
    assert {warning.warning_id for warning in warnings} == {"bb_no_evidence_units", "bb_llm_fallback"}


@pytest.mark.anyio
async def test_prepare_chapter_tasks_accumulates_internal_llm_calls(monkeypatch) -> None:
    def fake_builder(llm_calls: int, output_key: str):
        def build_node(*, context):
            del context

            async def node(state):
                del state
                return {output_key: True, "llm_calls_total": llm_calls}

            return node

        return build_node

    monkeypatch.setattr(graph, "build_confirm_and_seed_backbone_node", fake_builder(0, "seed_ready"))
    monkeypatch.setattr(graph, "build_document_backbone_node", fake_builder(1, "backbone_ready"))
    monkeypatch.setattr(graph, "build_assemble_chapter_tasks_node", fake_builder(0, "tasks_ready"))

    node = graph._build_prepare_chapter_tasks_node(context=object())
    result = await node({})

    assert result["seed_ready"] is True
    assert result["backbone_ready"] is True
    assert result["tasks_ready"] is True
    assert result["llm_calls_total"] == 1


def test_docgen_lane_summary_uses_final_published_quality_metrics() -> None:
    state = {
        "chapter_drafts": [
            {"chapter_index": 1, "quality_signals": {"coverage_score": 0.55, "quality_score": 0.7}},
            {"chapter_index": 2, "quality_signals": {"coverage_score": 0.65, "quality_score": 0.8}},
        ],
        "research_traces": [{"coverage_score": 0.4}],
        "chapter_metadatas": [
            {
                "chapter_index": 1,
                "chapter_review_report": {"coverage_score": 1.0},
                "quality_signals": {"quality_score": 0.92},
            },
            {
                "chapter_index": 2,
                "chapter_review_report": {"coverage_score": 0.9},
                "quality_signals": {"quality_score": 0.88},
            },
        ],
    }

    summary = build_docgen_lane_summary(state, token_summary=DigestTokenSummary())

    assert summary["coverage_score"] == pytest.approx(0.95)
    assert summary["quality_score"] == pytest.approx(0.9)
    assert summary["quality_summary"]["avg_coverage_score"] == pytest.approx(0.95)


def test_intent_payload_preserves_confirmed_contract_and_legacy_fields() -> None:
    payload = prepare_global_seed._intent_payload_for_state(  # noqa: SLF001
        DocGenIntentProfile(
            learning_goal_text="掌握矩阵乘法",
            content_strategy_text="严格按确认章节组织",
            depth_level="compact",
            example_ratio=0.32,
        )
    )

    assert payload["learning_goal_text"] == "掌握矩阵乘法"
    assert payload["content_strategy_text"] == "严格按确认章节组织"
    assert payload["example_ratio"] == pytest.approx(0.32)
    assert payload["legacy_compat"]["depth_level"] == "compact"


def test_intent_compilation_uses_planner_writing_strategies_without_fixed_teaching_policy() -> None:
    profile = prepare_global_seed._intent_from_confirmed_plan(  # noqa: SLF001
        docgen_context=DocGenContext(
            course_name="青少年人工智能素养",
            digest_mode="sprint",
            user_prompt="理解人工智能、数据偏见、隐私和负责任使用。",
            plan="先理解原理，再分析社会影响并练习伦理决策。",
            learner_profile_text="从高中生熟悉的生成式 AI 使用场景切入。",
        ),
        confirmed_plan={
            "chapters": [
                {
                    "title": "训练数据与偏见",
                    "writing_instructions": "从招聘筛选案例切入，对比数据偏差和算法偏差。",
                },
                {
                    "title": "隐私与责任边界",
                    "writing_instructions": "用个人信息授权场景组织伦理决策练习。",
                },
            ]
        },
    )

    assert "招聘筛选案例" in profile.content_strategy_text
    assert "个人信息授权场景" in profile.example_practice_policy
    assert profile.audience_profile_text == "从高中生熟悉的生成式 AI 使用场景切入。"
    assert profile.example_ratio == 0.0
    assert profile.practice_ratio == 0.0
    assert profile.depth_level == "standard"
    assert "紧凑讲解后立即" not in profile.example_practice_policy


def test_chapter_generation_plan_ignores_planner_default_length_for_writer_budget() -> None:
    plan = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(
            course_name="高等数学",
            digest_mode="systematic",
            build_constraints={"target_length": "30000-100000字"},
        ),
        confirmed_chapters=[
            {"chapter_index": 1, "title": "极限定义", "objective": "讲清极限定义"},
        ],
        locked_titles=[
            LockedChapterTitle(chapter_index=1, confirmed_title="极限定义", enhanced_title="极限定义"),
        ],
        intent_profile=DocGenIntentProfile(depth_level="deep"),
        file_summaries=[],
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="极限定义",
                enhanced_title="极限定义",
                chapter_goal="讲清极限定义",
                required_elements=["极限定义", "邻域语言"],
                retrieval_queries=["极限定义"],
            )
        ],
        chapter_execution_briefs=[
            ChapterExecutionBrief(
                chapter_index=1,
                teaching_outline=["先直观解释，再讲形式定义"],
                content_role_targets={"concept": ["极限定义"]},
                example_coverage_plan=[{"target": "极限定义", "form": "worked_example"}],
            )
        ],
    )

    task = plan.chapters[0]
    assert task.min_word_count == 1050
    assert task.target_word_count == 1850


def test_sprint_plan_expands_one_writer_budget_for_dense_confirmed_contract() -> None:
    required_elements = [f"必备知识点 {index}" for index in range(1, 8)]
    plan = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(course_name="C 语言", digest_mode="sprint"),
        confirmed_chapters=[
            {"chapter_index": 1, "title": "循环结构训练", "objective": "覆盖循环结构与综合训练"},
        ],
        locked_titles=[
            LockedChapterTitle(chapter_index=1, confirmed_title="循环结构训练", enhanced_title="循环结构训练"),
        ],
        intent_profile=DocGenIntentProfile(depth_level="compact"),
        file_summaries=[],
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="循环结构训练",
                enhanced_title="循环结构训练",
                chapter_goal="覆盖循环结构与综合训练",
                required_elements=required_elements,
                retrieval_queries=["循环结构"],
            )
        ],
        chapter_execution_briefs=[
            ChapterExecutionBrief(
                chapter_index=1,
                teaching_outline=["按确认合同逐项讲解"],
                content_role_targets={"concept": required_elements[:4]},
                example_coverage_plan=[{"target": required_elements[0], "form": "worked_example"}],
            )
        ],
    )

    task = plan.chapters[0]
    assert task.min_word_count == 1000
    assert task.target_word_count == 1500


def test_chapter_generation_plan_preserves_planner_writing_instructions() -> None:
    plan_seed, task_seeds, _agenda = chapter_planning.compose_seed_plan_and_backbone_agenda(
        docgen_context=DocGenContext(course_name="人工智能素养", digest_mode="systematic"),
        confirmed_chapters=[
            {
                "chapter_index": 1,
                "title": "偏见如何进入模型",
                "objective": "理解训练数据与模型偏见的关系",
                "required_elements": ["样本代表性", "标签偏差"],
                "writing_instructions": "从招聘筛选案例切入，再比较数据偏差与算法偏差。",
            }
        ],
        locked_titles=[
            LockedChapterTitle(
                chapter_index=1,
                confirmed_title="偏见如何进入模型",
                enhanced_title="偏见如何进入模型",
            )
        ],
        file_summaries=[],
    )

    assert "从招聘筛选案例切入，再比较数据偏差与算法偏差。" in task_seeds[0].style_rules
    assert "从招聘筛选案例切入，再比较数据偏差与算法偏差。" in plan_seed.chapters[0].style_rules


def test_chapter_generation_plan_leaves_mermaid_structure_to_writer_llm() -> None:
    plan = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(
            course_name="高等数学",
            digest_mode="systematic",
        ),
        confirmed_chapters=[
            {"chapter_index": 1, "title": "函数与极限结构", "objective": "讲清函数、极限和连续的关系"},
        ],
        locked_titles=[
            LockedChapterTitle(chapter_index=1, confirmed_title="函数与极限结构", enhanced_title="函数与极限结构"),
        ],
        intent_profile=DocGenIntentProfile(depth_level="standard"),
        file_summaries=[],
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="函数与极限结构",
                enhanced_title="函数与极限结构",
                chapter_goal="讲清函数、极限和连续的关系",
                required_elements=["函数概念", "极限定义", "连续性", "间断点"],
                retrieval_queries=["函数与极限"],
            )
        ],
        chapter_execution_briefs=[
            ChapterExecutionBrief(
                chapter_index=1,
                teaching_outline=["先搭结构图，再讲定义和例题"],
                writing_instructions=["从函数图像变化切入，并用间断点反例收束。"],
                content_role_targets={
                    "concept": ["函数概念", "极限定义", "连续性"],
                    "procedure": ["间断点判定流程"],
                    "misconception": ["把极限存在误当作函数连续"],
                },
                concept_targets=["函数概念", "极限定义", "连续性"],
                example_coverage_plan=[{"target": "连续性", "form": "worked_example"}],
            )
        ],
    )

    task = plan.chapters[0]
    assert task.allowed_assets == []
    assert task.placeholder_requests == []
    assert task.teaching_outline == ["先搭结构图，再讲定义和例题"]
    assert "从函数图像变化切入，并用间断点反例收束。" in task.writing_rules


def test_docgen_pipeline_artifacts_keep_stage_outputs_compact() -> None:
    context = DocGenContext(
        course_name="线性代数",
        user_prompt="构建一门复习课",
        learner_profile_text="学习者容易混淆矩阵乘法和线性映射。",
        learner_profile_context={
            "has_profile": True,
            "profile_text": "学习者容易混淆矩阵乘法和线性映射。",
            "user_profile_text": "用户画像：更适合分步引导。",
            "course_profile_text": "课程画像：矩阵乘法薄弱。",
            "user_profile": {"study_frequency": "每周 3 次"},
            "course_profile": {"weak_points": ["矩阵乘法"]},
        },
    )
    evidence = [
        HighConfidenceEvidenceUnit(
            evidence_id="e1",
            text="矩阵乘法依赖行列配对",
            source_ref="local://file/f1/section/s1",
            source_title="notes.md",
            source_span="s1",
            chapter_affinity={1: 0.91},
            confidence=0.92,
        )
    ]
    affinity = [
        SourceAffinityByChapter(
            chapter_index=1,
            file_ids=["f1"],
            section_refs=["s1"],
            source_slices=[
                ChapterSourceSlice(
                    chapter_index=2,
                    file_id="f1",
                    filename="notes.md",
                    section_ref="s1",
                    section_title="矩阵乘法",
                    relevance=0.91,
                    usage="definition",
                    summary="矩阵乘法依赖行列配对",
                )
            ],
        )
    ]
    intent = build_intent_enhanced(
        intent_core={
            "learning_goal_text": "掌握矩阵和线性映射",
            "content_strategy_text": "按概念到应用组织",
            "avoid_list": ["只堆公式"],
        },
        docgen_context=context,
        chapters=[{"chapter_index": 1}, {"chapter_index": 2}],
        material_profile={"source_count": 3},
        source_affinity_by_chapter=affinity,
        high_confidence_evidence_units=evidence,
    )
    summary = build_summary_enhanced(
        file_summaries=[
            FileMaterialSummary(
                file_id="f1",
                filename="notes.md",
                concepts=["矩阵"],
                definitions=["矩阵是数表"],
                formulas=["AB"],
                examples=["矩阵乘法例题"],
                question_types=["计算题"],
            )
        ],
        source_affinity_by_chapter=affinity,
        high_confidence_evidence_units=evidence,
    )
    user_profile = build_user_profile_enhanced(docgen_context=context)
    seed = ChapterGenerationTaskSeed(
        chapter_index=1,
        confirmed_title="矩阵基础",
        enhanced_title="矩阵基础",
        chapter_goal="讲清矩阵乘法",
        required_elements=["矩阵乘法"],
        retrieval_queries=["矩阵乘法"],
        priority_file_ids=["f1"],
        priority_section_refs=["s1"],
        source_slices=[
            ChapterSourceSlice(
                chapter_index=1,
                file_id="f1",
                filename="notes.md",
                section_ref="s1",
                section_title="矩阵乘法",
                relevance=0.91,
                summary="矩阵乘法依赖行列配对",
            )
        ],
    )
    brief = ChapterExecutionBrief(
        chapter_index=1,
        teaching_outline=["先讲对象，再讲运算"],
        content_role_targets={"concept": ["矩阵乘法"]},
        example_coverage_plan=[{"target": "矩阵乘法"}],
    )
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="矩阵基础",
        enhanced_title="矩阵基础",
        objective="讲清矩阵乘法",
        required_elements=["矩阵乘法"],
        retrieval_queries=["矩阵乘法"],
        priority_file_ids=["f1"],
        priority_section_refs=["s1"],
        source_slices=[
            ChapterSourceSlice(
                chapter_index=1,
                file_id="f1",
                filename="notes.md",
                section_ref="s1",
                section_title="矩阵乘法",
                relevance=0.91,
                summary="矩阵乘法依赖行列配对",
            )
        ],
        preferred_sources=["local://file/f1/section/s1"],
        claim_targets=["矩阵乘法需要行列配对"],
    )
    backbone = DocumentBackbone(
        canonical_glossary=[
            CanonicalGlossaryItem(term="矩阵乘法", definition="按行列配对求和", target_chapters=[1])
        ],
        concept_dependency_graph=[
            ConceptDependencyEdge(from_concept="矩阵", to_concept="矩阵乘法", relation="prerequisite_for")
        ],
        canonical_claim_pool=[
            CanonicalClaim(claim_id="c1", claim_text="矩阵乘法需要行列配对", target_chapter=1)
        ],
    )

    chapters = build_chapters_enhanced(task_seeds=[seed], briefs=[brief], summary_enhanced=summary)
    guideline = build_guideline(document_backbone=backbone, writing_rules=["先定义再举例"])
    dispatch = build_dispatch_table(chapter_tasks=[task], guideline=guideline, summary_enhanced=summary)
    preliminary_kg = build_preliminary_kg(chapters_enhanced=chapters, dispatch_table=dispatch, guideline=guideline)

    assert intent["chapter_count"] == 2
    assert intent["source_count"] == 3
    assert intent["learner_profile_text"].startswith("学习者容易混淆")
    assert intent["evidence_sample"][0]["source_span"] == "s1"
    assert intent["chapter_focus"][0]["section_refs"] == ["s1"]
    assert user_profile["has_profile"] is True
    assert user_profile["prompt_addendum"].startswith("学习者容易混淆")
    assert user_profile["has_user_profile"] is True
    assert user_profile["has_course_profile"] is True
    assert user_profile["user_profile_text"] == "用户画像：更适合分步引导。"
    assert user_profile["course_profile_text"] == "课程画像：矩阵乘法薄弱。"
    assert summary["source_titles"] == ["notes.md"]
    assert summary["high_confidence_evidence_count"] == 1
    assert summary["high_confidence_evidence"][0]["chapter_indices"] == [1]
    assert summary["chapter_source_affinity"][0]["source_slices"][0]["section_ref"] == "s1"
    assert summary["chapter_evidence_map"] == [{"chapter_index": 1, "evidence_ids": ["e1"]}]
    assert chapters[0]["keywords"] == ["矩阵乘法"]
    assert chapters[0]["source_section_refs"] == ["s1"]
    assert chapters[0]["evidence_ids"] == ["e1"]
    assert chapters[0]["teaching_outline"] == ["先讲对象，再讲运算"]
    assert guideline["canonical_glossary"][0]["term"] == "矩阵乘法"
    assert guideline["claim_count"] == 1
    assert dispatch["chapter_count"] == 1
    assert dispatch["global_glossary_terms"] == ["矩阵乘法"]
    assert dispatch["items"][0]["source_section_refs"] == ["s1"]
    assert dispatch["items"][0]["source_slices"][0]["section_ref"] == "s1"
    assert dispatch["items"][0]["evidence_ids"] == ["e1"]
    assert dispatch["items"][0]["preferred_sources"] == ["local://file/f1/section/s1"]
    assert dispatch["items"][0]["max_research_rounds"] == 2
    assert any(node["name"] == "矩阵基础" and node["knowledge_unit_type_label"] == "主题模块" for node in preliminary_kg["nodes"])
    assert {node["name"] for node in preliminary_kg["nodes"]} == {"矩阵基础"}
    assert preliminary_kg["edges"] == []


def test_learner_profile_text_for_branch_deduplicates_repeated_profile_fragments() -> None:
    profile_text = learner_profile_text_for_branch(
        docgen_context_text="用户画像：基础薄弱。\n\n诊断画像：应加强例题。",
        state_profile_text="用户画像：基础薄弱。\n\n诊断画像：应加强例题。",
        user_profile={"prompt_addendum": "用户画像：基础薄弱。"},
    )

    assert profile_text.count("用户画像：基础薄弱。") == 1
    assert profile_text.count("诊断画像：应加强例题。") == 1


def test_preliminary_kg_does_not_promote_planning_targets_to_semantic_nodes() -> None:
    preliminary_kg = build_preliminary_kg(
        chapters_enhanced=[
            {
                "chapter_index": 1,
                "title": "数与式基础",
                "required_elements": [
                    "学习目标：熟练掌握有理数、实数、整式与分式运算基础，提升计算准确率",
                ],
                "concept_targets": ["有理数", "实数", "整式与分式运算基础"],
                "content_role_targets": {
                    "concept": ["绝对值", "平方根"],
                    "pitfall": ["忽略分母不为零", "符号错误"],
                },
            }
        ]
    )

    nodes_by_name = {node["name"]: node for node in preliminary_kg["nodes"]}
    assert "学习目标：熟练掌握有理数、实数、整式与分式运算基础，提升计算准确率" not in nodes_by_name
    assert "计算准确率" not in nodes_by_name
    assert set(nodes_by_name) == {"数与式基础"}


def test_preliminary_kg_does_not_turn_required_elements_into_graph_nodes() -> None:
    preliminary_kg = build_preliminary_kg(
        chapters_enhanced=[
            {
                "chapter_index": 1,
                "title": "函数的基本概念、图像与读图方法",
                "required_elements": [
                    "围绕函数讲清核心概念、图示、方法步骤、典型例题、易错点、练习、单元测试",
                    "建立函数、变量、自变量与因变量的基本概念，理解函数关系的表达方式",
                    "结合图示认识函数图像",
                    "配套例题：函数值求解",
                    "常见易错点：自变量与因变量混淆",
                    "用图示辅助理解函数性质关系",
                    "安排基础练习与小测，重点检查概念理解、读图能力与基础计算",
                    "讲后纠错与回顾，巩固函数表达、图像判断和简单应用，为后续章节打底",
                    "梳理初中几何常见对象与性质",
                    "整理",
                    "判定题",
                    "图表分析",
                ],
                "concept_targets": [
                    "函数",
                    "变量",
                    "自变量与因变量",
                    "函数图像",
                    "函数性质关系",
                    "初中几何常见对象与性质",
                ],
                "example_targets": ["函数值求解例题"],
                "pitfall_targets": ["自变量与因变量混淆"],
                "chapter_end_practice_plan": [
                    {"target": "读图能力与基础计算", "task": "基础练习"},
                ],
            }
        ]
    )

    node_names = {node["name"] for node in preliminary_kg["nodes"]}
    assert {
        "围绕函数讲清核心概念",
        "图示",
        "方法步骤",
        "单元测试",
        "安排基础练习与小测",
        "重点检查概念理解",
        "讲后纠错与回顾",
        "为后续章节打底",
        "结合图示认识函数图像",
        "配套例题：函数值求解",
        "常见易错点：自变量与因变量混淆",
        "用图示辅助理解函数性质关系",
        "梳理初中几何常见对象与性质",
        "整理",
        "判定题",
        "图表分析",
    }.isdisjoint(node_names)
    assert node_names == {"函数的基本概念、图像与读图方法"}
    assert preliminary_kg["edges"] == []


@pytest.mark.anyio
async def test_backbone_node_emits_early_dispatch_and_preliminary_kg(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_update_status(*args, **kwargs):
        del args
        captured["status_kwargs"] = kwargs

    async def fake_publish_progress(_context, *, state, stage, payload):
        del _context, state, stage
        captured["progress_payload"] = payload

    monkeypatch.setattr(build_document_backbone, "update_knowledge_build_status", fake_update_status)
    monkeypatch.setattr(build_document_backbone, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(build_document_backbone, "publish_docgen_progress", fake_publish_progress)

    async def fake_generate_document_backbone(**kwargs):
        captured["backbone_kwargs"] = kwargs
        return (
            DocumentBackbone(
                canonical_glossary=[
                    CanonicalGlossaryItem(
                        term="行列配对",
                        definition="矩阵乘法的行列配对规则。",
                        source_hint="notes.md/s1",
                        target_chapters=[1],
                    )
                ]
            ),
            [
                ChapterExecutionBrief(
                    chapter_index=1,
                    teaching_outline=["先说明维度匹配，再讲行列配对"],
                    writing_instructions=["用资料中的算例解释规则。"],
                    concept_targets=["行列配对"],
                )
            ],
            [],
        )

    monkeypatch.setattr(build_document_backbone, "generate_document_backbone", fake_generate_document_backbone)

    node = build_document_backbone.build_document_backbone_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course-early-kg"),
    )
    result = await node(
        {
            "course_id": "course-early-kg",
            "requested_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "digest_mode": "systematic",
            "chapter_task_seeds": [
                ChapterGenerationTaskSeed(
                    chapter_index=1,
                    confirmed_title="矩阵乘法",
                    enhanced_title="矩阵乘法",
                    chapter_goal="讲清矩阵乘法规则",
                    required_elements=["行列配对", "维度匹配"],
                    priority_file_ids=["f1"],
                    priority_section_refs=["s1"],
                    source_slices=[
                        ChapterSourceSlice(
                            chapter_index=1,
                            file_id="f1",
                            filename="notes.md",
                            section_ref="s1",
                            section_title="矩阵乘法",
                            relevance=0.9,
                            summary="矩阵乘法依赖行列配对",
                        )
                    ],
                ).model_dump(mode="json")
            ],
            "backbone_research_agenda": {
                "topics": ["矩阵乘法"],
                "glossary_candidates": ["行列配对"],
                "section_refs": ["s1"],
            },
            "high_confidence_evidence_units": [
                HighConfidenceEvidenceUnit(
                    evidence_id="e1",
                    text="矩阵乘法依赖行列配对。",
                    source_ref="local://file/f1/section/s1",
                    chapter_affinity={1: 0.9},
                    confidence=0.9,
                    source_title="notes.md",
                    source_span="s1",
                ).model_dump(mode="json")
            ],
            "file_summaries": [
                FileMaterialSummary(
                    file_id="f1",
                    filename="notes.md",
                    concepts=["矩阵乘法"],
                    definitions=["行列配对求和"],
                    high_value_sections=["s1"],
                ).model_dump(mode="json")
            ],
            "chapter_generation_plan_seed": {
                "writing_rules": ["先定义再举例"],
                "chapters": [],
            },
            "summary_enhanced": {
                "chapter_evidence_map": [{"chapter_index": 1, "evidence_ids": ["e1"]}],
            },
        }
    )

    assert result["guideline"]["canonical_glossary"][0]["term"] == "行列配对"
    assert result["chapter_execution_briefs"][0]["writing_instructions"] == ["用资料中的算例解释规则。"]
    assert result["chapters_enhanced"][0]["chapter_index"] == 1
    assert result["dispatch_table"]["items"][0]["source_section_refs"] == ["s1"]
    assert result["dispatch_table"]["items"][0]["evidence_ids"] == ["e1"]
    assert result["preliminary_kg"]["node_count"] == 1
    assert result["preliminary_kg"]["edge_count"] == 0
    assert captured["progress_payload"]["preliminary_kg_node_count"] == result["preliminary_kg"]["node_count"]
    status_kwargs = captured["status_kwargs"]
    assert status_kwargs["discovered_node_count"] == result["preliminary_kg"]["node_count"]
    assert status_kwargs["metrics"]["docgen_preliminary_kg_stage"] == "document_backbone_ready"
    assert captured["backbone_kwargs"]["course_name"] == ""
    assert result["llm_calls_total"] == 1


def test_docgen_kg_draft_merges_preliminary_and_reviewed_headings() -> None:
    draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {
                    "name": "矩阵运算",
                    "knowledge_unit_type": "topic",
                    "chapter_index": 1,
                    "summary": "矩阵运算章节主题。",
                },
                {
                    "name": "矩阵乘法",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "按行列配对求和。",
                    "source": "docgen_preliminary_kg",
                }
            ],
            "edges": [
                {
                    "source_name": "矩阵乘法",
                    "target_name": "矩阵运算",
                    "edge_type": "part_of",
                    "chapter_index": 1,
                    "source": "docgen_preliminary_kg",
                }
            ],
        },
        kg_refinement_items=[
            {
                "chapter_index": 1,
                "source": "docgen_review_refinement",
                "nodes": [
                    {
                        "name": "维度匹配",
                        "knowledge_unit_type": "misconception",
                        "chapter_index": 1,
                        "summary": "矩阵乘法前先检查维度。",
                        "source": "docgen_review_refinement",
                    }
                ],
                "edges": [
                    {
                        "source_name": "维度匹配",
                        "target_name": "矩阵运算",
                        "edge_type": "part_of",
                        "chapter_index": 1,
                        "source": "docgen_review_refinement",
                    }
                ],
            }
        ],
        reviewed_chapters=[
            {
                "chapter_index": 1,
                "title": "矩阵运算",
                "markdown": "# 矩阵运算\n\n## 行列配对\n\n内容\n\n## 单元测试\n\n1. 计算 AB。",
            }
        ],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )

    assert draft["stage"] == "prepare_knowledge_graph"
    assert draft["review_refinement_count"] == 1
    assert draft["chapter_coverage_ratio"] == 1.0
    assert draft["quality_status"] == "ready"
    assert draft["quality_ready"] is True
    assert draft["quality_audit"]["missing_chapter_count"] == 0
    assert draft["quality_audit"]["edge_endpoint_issue_count"] == 0
    assert draft["quality_audit"]["downstream_unit_count"] >= 1
    assert draft["quality_audit"]["exam_ready_unit_count"] >= 1
    assert draft["quality_audit"]["profile_ready_unit_count"] >= 1
    assert draft["quality_audit"]["diagnostic_unit_count"] >= 1
    assert draft["quality_audit"]["structure_edge_count"] >= 1
    assert draft["quality_audit"]["examine_profile_ready"] is True
    assert draft["fast_visible_ready"] is True
    assert draft["node_count"] >= 3
    assert any(node["name"] == "维度匹配" and node["source"] == "docgen_review_refinement" for node in draft["nodes"])
    assert any(node["name"] == "矩阵乘法" and node["source"] == "docgen_preliminary_kg" for node in draft["nodes"])
    assert any(node["name"] == "矩阵运算" and node["knowledge_unit_type"] == "topic" for node in draft["nodes"])
    assert all(node["name"] != "单元测试" for node in draft["nodes"])
    assert any(edge["source_name"] == "矩阵乘法" and edge["target_name"] == "矩阵运算" for edge in draft["edges"])


def test_docgen_kg_draft_does_not_extract_learning_bullets_as_rule_nodes() -> None:
    draft = build_docgen_kg_draft(
        reviewed_chapters=[
            {
                "chapter_index": 1,
                "title": "指针结构体文件",
                "markdown": (
                    "# 指针结构体文件\n\n"
                    "## 执行范围\n\n"
                    "- 指针变量的定义、初始化、取地址与间接访问。\n"
                    "- 文件读写流程与 fopen/fclose/printf/fscanf 的使用。\n\n"
                    "## 单元测试\n\n"
                    "- 判断 `int *p` 与 `&a` 的含义。\n"
                ),
            }
        ],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )

    node_names = {node["name"] for node in draft["nodes"]}
    assert "执行范围" not in node_names
    assert "指针变量的定义" not in node_names
    assert "文件读写流程与 fopen/fclose/printf/fscanf 的使用" not in node_names
    assert "单元测试" not in node_names
    assert "判断 `int *p` 与 `&a` 的含义" not in node_names
    assert node_names == {"指针结构体文件"}
    assert draft["quality_ready"] is False
    assert draft["fast_visible_ready"] is False


def test_prepare_knowledge_graph_chapters_keep_markdown_when_metadata_locks_title() -> None:
    chapters = prepare_knowledge_graph._chapters_for_prefetch(  # noqa: SLF001
        {
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "最终标题",
                    "summary": "标题审核后的摘要。",
                }
            ],
            "reviewed_chapter_drafts": [
                {
                    "chapter_index": 1,
                    "title": "旧标题",
                    "markdown": "# 旧标题\n\n## 单元测试\n\n- 解释核心概念。",
                }
            ],
        }
    )

    assert chapters == [
        {
            "chapter_index": 1,
            "title": "最终标题",
            "summary": "标题审核后的摘要。",
            "markdown": "# 旧标题\n\n## 单元测试\n\n- 解释核心概念。",
        }
    ]


def test_docgen_kg_draft_requires_real_learning_units_for_examine_profile_shape() -> None:
    draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {
                    "name": "课程目录",
                    "knowledge_unit_type": "topic",
                    "chapter_index": 1,
                    "summary": "只是一条材料来源。",
                    "source": "docgen_preliminary_kg",
                }
            ],
            "edges": [],
        },
        reviewed_chapters=[],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )

    assert draft["quality_status"] == "needs_catchup"
    assert draft["quality_ready"] is False
    assert draft["fast_visible_ready"] is False
    assert draft["quality_audit"]["downstream_unit_count"] == 0
    assert draft["quality_audit"]["examine_profile_ready"] is False
    assert "no_downstream_learning_unit" in draft["quality_audit"]["warnings"]


def test_docgen_kg_draft_blocks_fast_visible_when_edge_endpoint_is_missing() -> None:
    draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {
                    "name": "矩阵乘法",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "按行列配对求和。",
                    "source": "docgen_preliminary_kg",
                }
            ],
            "edges": [
                {
                    "source_name": "矩阵乘法",
                    "target_name": "不存在的章节",
                    "edge_type": "part_of",
                    "chapter_index": 1,
                    "source": "docgen_preliminary_kg",
                }
            ],
        },
        reviewed_chapters=[],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )

    assert draft["quality_status"] == "needs_catchup"
    assert draft["quality_ready"] is False
    assert draft["fast_visible_ready"] is False
    assert draft["quality_audit"]["edge_endpoint_issue_count"] == 1
    assert "edge_endpoint_issue" in draft["quality_audit"]["warnings"]


def test_docgen_kg_draft_dedupes_same_name_nodes_before_fast_visible_gate() -> None:
    draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {"name": "矩阵运算", "knowledge_unit_type": "topic", "chapter_index": 1},
                {"name": "矩阵乘法步骤", "knowledge_unit_type": "procedure", "chapter_index": 1},
                {"name": "维度匹配", "knowledge_unit_type": "concept", "chapter_index": 1},
                {"name": "维度匹配", "knowledge_unit_type": "misconception", "chapter_index": 1},
            ],
            "edges": [
                {"source_name": "矩阵乘法步骤", "target_name": "矩阵运算", "edge_type": "part_of", "chapter_index": 1},
                {"source_name": "维度匹配", "target_name": "矩阵运算", "edge_type": "part_of", "chapter_index": 1},
            ],
        },
        reviewed_chapters=[],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )

    duplicate_nodes = [node for node in draft["nodes"] if node["name"] == "维度匹配"]
    assert len(duplicate_nodes) == 1
    assert duplicate_nodes[0]["knowledge_unit_type"] == "misconception"
    assert draft["quality_status"] == "ready"
    assert draft["quality_ready"] is True
    assert draft["fast_visible_ready"] is True
    assert draft["quality_audit"]["edge_endpoint_ambiguity_count"] == 0
    assert draft["quality_audit"]["valid_relation_edge_count"] == 2
    assert "edge_endpoint_ambiguity" not in draft["quality_audit"]["warnings"]


def test_docgen_kg_draft_blocks_fast_visible_when_relation_direction_is_invalid() -> None:
    draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {"name": "矩阵运算", "knowledge_unit_type": "topic", "chapter_index": 1},
                {"name": "矩阵乘法步骤", "knowledge_unit_type": "procedure", "chapter_index": 1},
                {"name": "维度误区", "knowledge_unit_type": "misconception", "chapter_index": 1},
            ],
            "edges": [
                {"source_name": "矩阵乘法步骤", "target_name": "矩阵运算", "edge_type": "part_of", "chapter_index": 1},
                {"source_name": "矩阵运算", "target_name": "维度误区", "edge_type": "assesses", "chapter_index": 1},
            ],
        },
        reviewed_chapters=[],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )

    assert draft["quality_status"] == "needs_catchup"
    assert draft["quality_ready"] is False
    assert draft["fast_visible_ready"] is False
    assert draft["quality_audit"]["relation_direction_issue_count"] == 1
    assert draft["quality_audit"]["valid_relation_edge_count"] == 1
    assert draft["quality_audit"]["structure_edge_count"] == 1
    assert "relation_direction_issue" in draft["quality_audit"]["warnings"]


def test_docgen_kg_draft_blocks_unresolved_repair_warning_but_accepts_applied_repair() -> None:
    reviewed = ReviewedChapterDraft(
        chapter_index=1,
        title="矩阵运算",
        markdown="# 矩阵运算\n\n## 行列配对\n\n内容。\n\n## 单元测试\n\n1. 计算 AB。",
    )
    recorded_action = ReviewAction(
        action_id="repair-matrix-1",
        chapter_index=1,
        action_type="section_patch",
        severity="warning",
        reason="需要补充维度匹配提示。",
        target_anchor="行列配对",
        instruction="补充维度匹配提示。",
        status="recorded",
    )
    applied_action = recorded_action.model_copy(update={"status": "applied"})
    unresolved_refinement = build_chapter_kg_refinement_item(
        reviewed=reviewed,
        actions=[recorded_action],
    )
    applied_refinement = build_chapter_kg_refinement_item(
        reviewed=reviewed,
        actions=[applied_action],
    )

    unresolved_draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {
                    "name": "矩阵乘法",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "按行列配对求和。",
                }
            ],
            "edges": [
                {"source_name": "矩阵乘法", "target_name": "矩阵运算", "edge_type": "part_of", "chapter_index": 1}
            ],
        },
        kg_refinement_items=[unresolved_refinement],
        reviewed_chapters=[reviewed.model_dump(mode="json")],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "missing", "prefetch_ready": 0},
    )
    repaired_draft = build_docgen_kg_draft(
        preliminary_kg={
            "nodes": [
                {
                    "name": "矩阵运算",
                    "knowledge_unit_type": "topic",
                    "chapter_index": 1,
                    "summary": "矩阵运算章节主题。",
                },
                {
                    "name": "矩阵乘法",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "按行列配对求和。",
                }
            ],
            "edges": [
                {"source_name": "矩阵乘法", "target_name": "矩阵运算", "edge_type": "part_of", "chapter_index": 1}
            ],
        },
        kg_refinement_items=[unresolved_refinement, applied_refinement],
        reviewed_chapters=[reviewed.model_dump(mode="json")],
        prefetched_records=[],
        prefetch_metrics={"prefetch_status": "completed", "prefetch_ready": 1},
    )

    assert unresolved_refinement["needs_repair"] is True
    assert applied_refinement["needs_repair"] is False
    assert unresolved_draft["quality_ready"] is False
    assert unresolved_draft["fast_visible_ready"] is True
    assert "review_repair_warning" in unresolved_draft["quality_audit"]["warnings"]
    assert repaired_draft["review_refinement_needs_repair_count"] == 0
    assert repaired_draft["quality_ready"] is True
    assert "review_repair_warning" not in repaired_draft["quality_audit"]["warnings"]


@pytest.mark.anyio
async def test_chapter_brief_node_compiles_confirmed_contract_without_llm(monkeypatch) -> None:
    progress_payload: dict[str, object] = {}

    async def fake_publish(*args, **kwargs):
        progress_payload.update(dict(kwargs.get("payload") or {}))
        return None

    monkeypatch.setattr(build_chapter_execution_briefs, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(build_chapter_execution_briefs, "publish_docgen_progress", fake_publish)

    node = build_chapter_execution_briefs.build_chapter_execution_briefs_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build-brief",
            "summary_enhanced": {"concepts": ["矩阵乘法"]},
            "guideline": {"writing_rules": ["先定义再举例"]},
            "dispatch_table": {"items": [{"chapter_index": 1, "source_section_refs": ["s1"]}]},
            "preliminary_kg": {
                "nodes": [
                    {"name": "矩阵乘法", "knowledge_unit_type": "topic", "chapter_index": 1},
                    {"name": "矩阵乘法维度检查", "knowledge_unit_type": "skill", "chapter_index": 1},
                ],
                "edges": [
                    {"source_name": "矩阵乘法维度检查", "target_name": "矩阵乘法", "edge_type": "part_of", "chapter_index": 1}
                ],
            },
            "docgen_context": DocGenContext(
                course_id="course_state_contract",
                course_name="线性代数",
                digest_mode="systematic",
                plan="按概念组织",
                learner_profile_text="用户画像：基础薄弱。",
            ).model_dump(mode="json"),
            "user_profile": {"prompt_addendum": "课程画像：矩阵乘法错误率高。"},
            "chapter_task_seeds": [
                ChapterGenerationTaskSeed(
                    chapter_index=1,
                    confirmed_title="矩阵基础",
                    enhanced_title="矩阵基础",
                    chapter_goal="讲清矩阵乘法",
                    required_elements=["矩阵乘法"],
                    source_slices=[
                        ChapterSourceSlice(
                            chapter_index=1,
                            file_id="f1",
                            filename="notes.md",
                            section_ref="s1",
                            section_title="矩阵乘法",
                            summary="矩阵乘法依赖行列配对",
                        )
                    ],
                ).model_dump(mode="json")
            ],
            "document_backbone": DocumentBackbone(
                canonical_glossary=[
                    CanonicalGlossaryItem(term="矩阵乘法", definition="按行列配对求和", target_chapters=[1])
                ],
                canonical_claim_pool=[
                    CanonicalClaim(claim_id="c1", claim_text="矩阵乘法需要行列配对", target_chapter=1)
                ],
            ).model_dump(mode="json"),
            "intent_core": {"learning_goal_text": "掌握矩阵"},
            "high_confidence_evidence_units": [
                HighConfidenceEvidenceUnit(
                    evidence_id="e1",
                    text="矩阵乘法依赖行列配对",
                    chapter_affinity={1: 0.9},
                    confidence=0.9,
                    source_ref="local://file/f1/section/s1",
                ).model_dump(mode="json")
            ],
        }
    )

    brief = result["chapter_execution_briefs"][0]
    assert brief["chapter_index"] == 1
    assert brief["content_role_targets"] == {}
    assert brief["teaching_outline"] == []
    assert brief["example_coverage_plan"] == []
    assert brief["retrieval_queries"] == ["矩阵基础", "矩阵乘法"]
    assert result["kg_prefetch_status"] == "deferred_until_enhanced_chapters"
    assert result["llm_calls_total"] == 0
    assert progress_payload["kg_prefetch_started"] is False
    assert progress_payload["brief_mode"] == "compiled_from_confirmed_contract"


@pytest.mark.anyio
async def test_chapter_brief_node_rejects_missing_chapter_seeds() -> None:

    node = build_chapter_execution_briefs.build_chapter_execution_briefs_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node({"chapter_task_seeds": []})

    assert result == {"error": "缺少可生成执行 brief 的章节 seed。"}


def test_writer_context_consumes_dispatch_guideline_and_evidence() -> None:
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="矩阵基础",
        enhanced_title="矩阵基础",
        objective="讲清矩阵乘法",
        content_points=["矩阵乘法"],
        concept_targets=["行列配对"],
        retrieval_queries=["矩阵乘法"],
        priority_file_ids=["f1"],
        priority_section_refs=["s1"],
        source_slices=[
            ChapterSourceSlice(
                chapter_index=1,
                file_id="f1",
                filename="notes.md",
                section_ref="s1",
                section_title="矩阵乘法",
                summary="矩阵乘法依赖行列配对",
            )
        ],
        chapter_end_practice_plan=[{"target": "矩阵乘法", "purpose": "检查行列配对"}],
    )
    dispatch_item = {
        "chapter_index": 1,
        "source_slices": [
            {
                "file_id": "f1",
                "filename": "notes.md",
                "section_ref": "s1",
                "section_title": "矩阵乘法",
                "summary": "矩阵乘法依赖行列配对",
            }
        ],
        "preferred_sources": ["local://file/f1/section/s1"],
    }
    chapter_contract = {"chapter_index": 1, "evidence_ids": ["e1"]}
    guideline_summary = {
        "writing_rules": ["先定义再举例"],
        "canonical_glossary": [{"term": "矩阵乘法", "definition": "按行列配对求和", "target_chapters": [1]}],
        "notation_rules": [{"symbol": "AB", "meaning": "矩阵乘积", "target_chapters": [1]}],
        "confusion_checks": [],
        "global_claim_count": 1,
    }
    evidence_items = [
        {
            "evidence_id": "e1",
            "text": "矩阵乘法依赖行列配对",
            "source_title": "notes.md",
            "source_ref": "local://file/f1/section/s1",
        }
    ]

    prefix = generate_chapters._chapter_context_prefix_for_writer(
        task=task,
        dispatch_item=dispatch_item,
        chapter_contract=chapter_contract,
        guideline_summary=guideline_summary,
        evidence_items=evidence_items,
    )
    plan = generate_chapters._chapter_plan_for_writer(
        task,
        total_chapters=3,
        learner_profile_text="用户画像：矩阵乘法错误率高。",
        guideline_summary=guideline_summary,
        dispatch_item=dispatch_item,
        chapter_contract=chapter_contract,
        evidence_items=evidence_items,
    )

    assert "本章优先资料切片" in prefix
    assert "矩阵乘法依赖行列配对" in prefix
    assert "AB: 矩阵乘积" in prefix
    contract = plan["execution_contract"]
    assert contract["guideline_summary"]["canonical_glossary"][0]["term"] == "矩阵乘法"
    assert contract["dispatch_item"]["preferred_sources"] == ["local://file/f1/section/s1"]
    assert contract["chapter_contract"]["evidence_ids"] == ["e1"]
    assert contract["high_confidence_evidence"][0]["evidence_id"] == "e1"
    assert "错误率高" in contract["learner_profile"]


@pytest.mark.anyio
async def test_lock_titles_uses_course_id_state_key(monkeypatch) -> None:
    captured_course_ids: list[str] = []

    def fake_append(course_id: str, **kwargs) -> None:
        captured_course_ids.append(course_id)

    def fake_upsert(course_id: str, **kwargs) -> None:
        captured_course_ids.append(course_id)

    monkeypatch.setattr(lock_titles_for_chapters, "append_knowledge_build_recent_event", fake_append)
    monkeypatch.setattr(lock_titles_for_chapters, "upsert_knowledge_build_chapter_progress", fake_upsert)

    node = lock_titles_for_chapters.build_lock_titles_for_chapters_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "docgen_context": {
                "course_id": "course_state_contract",
                "course_name": "计算机基础",
                "digest_mode": "sprint",
                "user_prompt": "学习计算机基础",
                "plan": "按核心模块组织内容",
            },
            "chapter_assignments": [
                {
                    "chapter_index": 1,
                    "title": "计算机系统构成",
                }
            ],
        }
    )

    assert result["locked_titles"][0]["enhanced_title"] == "计算机系统构成"
    assert result["llm_calls_total"] == 0
    assert captured_course_ids == ["course_state_contract", "course_state_contract"]


def test_generation_sends_include_docgen_pipeline_artifacts() -> None:
    sends = graph.build_generation_sends(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_group_id": "group-generation-scope",
            "build_session_id": "build_generation_scope",
            "chapter_tasks": [
                {"chapter_index": 1, "confirmed_title": "矩阵基础"},
                {"chapter_index": 2, "confirmed_title": "方程组"},
            ],
            "shared_inputs": {"source_count": 2},
            "document_context": {"course": "线性代数"},
            "docgen_context": {"digest_mode": "systematic"},
            "document_backbone": {"canonical_glossary": [{"term": "矩阵"}]},
            "learner_profile_text": "学习者容易混淆行列运算。",
            "user_profile": {"prompt_addendum": "关注易错点。"},
            "summary_enhanced": {"high_confidence_evidence_units": [{"evidence_id": "e1"}]},
            "chapters_enhanced": [{"chapter_index": 1, "evidence_ids": ["e1"]}],
            "guideline": {"writing_rules": ["先定义再举例"]},
            "dispatch_table": {"items": [{"chapter_index": 1, "preferred_sources": ["local://file/f1/section/s1"]}]},
        }
    )

    assert sends != "fail"
    first = sends[0].arg
    assert first["chapter_task"]["chapter_index"] == 1
    assert first["build_group_id"] == "group-generation-scope"
    assert first["guideline"]["writing_rules"] == ["先定义再举例"]
    assert first["dispatch_table"]["items"][0]["preferred_sources"] == ["local://file/f1/section/s1"]
    assert first["summary_enhanced"]["high_confidence_evidence_units"][0]["evidence_id"] == "e1"
    assert first["chapters_enhanced"][0]["evidence_ids"] == ["e1"]
    assert first["user_profile"]["prompt_addendum"] == "关注易错点。"
    assert "chapter_tasks" not in first


def test_chapter_preview_buffer_forwards_build_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        generate_chapters,
        "upsert_knowledge_build_chapter_progress",
        lambda _course_id, **kwargs: captured.append(("progress", kwargs.get("build_group_id"))),
    )
    monkeypatch.setattr(
        generate_chapters,
        "upsert_knowledge_build_chapter_preview",
        lambda _course_id, **kwargs: captured.append(("preview", kwargs.get("build_group_id"))),
    )

    buffer = generate_chapters._ChapterPreviewPersistBuffer(
        course_id="course_state_contract",
        requested_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
        build_group_id="group-preview-buffer",
        chapter_index=1,
    )
    buffer._persist_once(
        chapter_progress={"chapter_index": 1, "status": "drafting"},
        chapter_preview={"chapter_index": 1, "excerpt": "draft"},
    )

    assert captured == [
        ("progress", "group-preview-buffer"),
        ("preview", "group-preview-buffer"),
    ]


@pytest.mark.anyio
async def test_generate_cover_node_forwards_build_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_cover(**kwargs):
        captured.update(kwargs)
        return None

    async def fake_publish_progress(*_args, **_kwargs):
        return None

    monkeypatch.setattr(generate_cover, "generate_docgen_cover_artifact", fake_generate_cover)
    monkeypatch.setattr(generate_cover, "publish_docgen_progress", fake_publish_progress)

    node = generate_cover.build_generate_cover_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_group_id": "group-cover",
            "build_session_id": "session-cover",
            "document_context": {"course_name": "线性代数"},
        }
    )

    assert captured["build_group_id"] == "group-cover"
    assert captured["build_session_id"] == "session-cover"


@pytest.mark.anyio
async def test_enhance_node_starts_whole_document_kg_prefetch(monkeypatch) -> None:
    captured_progress_payload: dict[str, object] = {}
    captured_prefetch_kwargs: dict[str, object] = {}

    async def fake_enhance_chapter_draft(draft, **kwargs):
        enhanced = EnhancedChapterDraft(
            chapter_index=draft.chapter_index,
            title=draft.title,
            markdown=f"{draft.markdown}\n\n## 增强图示\n\n变量位置已经补齐。",
            summary="增强后的章节",
        )
        return enhanced, AssetManifest(assets=[{"asset_id": "fig-1"}]), PracticeManifest(questions=[])

    monkeypatch.setattr(enhance_chapters, "enhance_chapter_draft", fake_enhance_chapter_draft)
    monkeypatch.setattr(enhance_chapters, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(enhance_chapters, "upsert_knowledge_build_chapter_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(enhance_chapters, "upsert_knowledge_build_chapter_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(enhance_chapters, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        enhance_chapters,
        "build_merged_markdown",
        lambda chapters, **kwargs: f"NORMALIZED::{chapters[0]['markdown']}",
    )

    def fake_start_docgen_kg_prefetch(**kwargs):
        captured_prefetch_kwargs.update(kwargs)
        return True

    monkeypatch.setattr(
        enhance_chapters,
        "start_docgen_kg_prefetch",
        fake_start_docgen_kg_prefetch,
    )

    async def fake_publish(*args, **kwargs):
        captured_progress_payload.update(dict(kwargs.get("payload") or {}))
        return None

    monkeypatch.setattr(enhance_chapters, "publish_docgen_progress", fake_publish)

    node = enhance_chapters.build_enhance_chapters_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build-enhance-prefetch",
            "digest_mode": "systematic",
            "unit_test_chapter_drafts": [
                ChapterDraft(
                    chapter_index=1,
                    title="变量与内存",
                    markdown="# 变量与内存\n\n正文。",
                ).model_dump(mode="json")
            ],
            "document_backbone": {"chapter_count": 1},
            "chapter_task_seeds": [{"chapter_index": 1, "confirmed_title": "变量与内存"}],
            "chapter_execution_briefs": [{"chapter_index": 1, "teaching_outline": ["变量位置"]}],
            "preliminary_kg": {"nodes": [{"name": "变量"}]},
        }
    )

    assert result["kg_prefetch_status"] == "running_from_enhanced_chapters"
    assert result["enhanced_chapter_drafts"][0]["markdown"].endswith("变量位置已经补齐。")
    assert captured_progress_payload["kg_prefetch_started"] is True
    assert captured_progress_payload["kg_prefetch_incremental_started"] is False
    assert captured_prefetch_kwargs["chapters"][0]["markdown"].startswith("NORMALIZED::")
    assert result["enhanced_chapter_drafts"][0]["markdown"].startswith("# 变量与内存")
    assert captured_prefetch_kwargs["docgen_manifest"]["kg_prefetch_phase"] == "enhanced_chapters"


def test_review_sends_only_single_chapter_payload() -> None:
    sends = graph.build_review_sends(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_group_id": "group-review-scope",
            "build_session_id": "build_review_scope",
            "enhanced_chapter_drafts": [
                {"chapter_index": 1, "title": "第一章", "markdown": "# 第一章\n\n正文"},
                {"chapter_index": 2, "title": "第二章", "markdown": "# 第二章\n\n正文"},
            ],
            "chapter_tasks": [
                {"chapter_index": 1, "confirmed_title": "第一章", "required_elements": ["A"]},
                {"chapter_index": 2, "confirmed_title": "第二章", "required_elements": ["B"]},
            ],
            "claim_ledgers": [
                {"chapter_index": 1, "items": [{"claim_id": "c1", "claim_text": "A"}]},
                {"chapter_index": 2, "items": [{"claim_id": "c2", "claim_text": "B"}]},
            ],
            "claim_evidence_maps": [
                {"chapter_index": 1, "bindings": [{"claim_id": "c1", "support_level": 0.8}]},
                {"chapter_index": 2, "bindings": [{"claim_id": "c2", "support_level": 0.2}]},
            ],
            "conflict_reports": [
                {"chapter_index": 1, "items": []},
                {"chapter_index": 2, "items": [{"severity": "warning", "detail": "冲突"}]},
            ],
            "learner_profile_text": "学习者容易漏看单位。",
            "user_profile": {"prompt_addendum": "多检查易错点。"},
            "summary_enhanced": {
                "chapter_evidence_map": [{"chapter_index": 1, "evidence_ids": ["e1"]}],
                "high_confidence_evidence": [{"evidence_id": "e1", "text": "A 来自讲义"}],
            },
            "chapters_enhanced": [{"chapter_index": 1, "evidence_ids": ["e1"]}],
            "guideline": {"writing_rules": ["先定义再例题"]},
            "dispatch_table": {"items": [{"chapter_index": 1, "source_slices": [{"section_ref": "s1"}]}]},
        }
    )

    assert sends != "fail"
    assert [item.arg["build_group_id"] for item in sends] == ["group-review-scope", "group-review-scope"]
    assert [item.arg["review_chapter_task"]["chapter_index"] for item in sends] == [1, 2]
    assert [item.arg["review_claim_ledger"]["chapter_index"] for item in sends] == [1, 2]
    assert sends[0].arg["guideline"]["writing_rules"] == ["先定义再例题"]
    assert sends[0].arg["dispatch_table"]["items"][0]["source_slices"][0]["section_ref"] == "s1"
    assert sends[0].arg["summary_enhanced"]["chapter_evidence_map"][0]["evidence_ids"] == ["e1"]
    assert sends[0].arg["chapters_enhanced"][0]["evidence_ids"] == ["e1"]
    assert sends[0].arg["user_profile"]["prompt_addendum"] == "多检查易错点。"
    assert "chapter_tasks" not in sends[0].arg
    assert "claim_ledgers" not in sends[0].arg
    assert "claim_evidence_maps" not in sends[0].arg
    assert "conflict_reports" not in sends[0].arg


@pytest.mark.anyio
async def test_review_node_outputs_overlay_without_markdown(monkeypatch) -> None:
    captured_review_kwargs: dict = {}
    captured_publish_payload: dict = {}

    async def fake_review_chapter(**kwargs):
        captured_review_kwargs.update(kwargs)
        reviewed = ReviewedChapterDraft(
            chapter_index=1,
            title="第一章",
            markdown="# 第一章\n\n正文",
            review_report_ref="ch01_review",
            warnings=["需要补例题"],
        )
        report = ChapterReviewReport(
            report_id="ch01_review",
            chapter_index=1,
            passed=False,
            warnings=["需要补例题"],
            review_mode="rule_fallback_after_llm_error",
        )
        return reviewed, report, []

    monkeypatch.setattr(review_content, "review_chapter", fake_review_chapter)
    monkeypatch.setattr(review_content, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "upsert_knowledge_build_chapter_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "upsert_knowledge_build_chapter_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    async def fake_publish(*args, **kwargs):
        captured_publish_payload.update(dict(kwargs.get("payload") or {}))
        return None

    monkeypatch.setattr(review_content, "publish_docgen_progress", fake_publish)
    node = review_content.build_review_chapter_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build-review",
            "enhanced_chapter_draft": {"chapter_index": 1, "title": "第一章", "markdown": "# 第一章\n\n正文"},
            "review_chapter_task": {"chapter_index": 1, "confirmed_title": "第一章"},
            "review_claim_ledger": {"chapter_index": 1, "items": []},
            "review_claim_evidence_map": {"chapter_index": 1, "bindings": []},
            "review_conflict_report": {"chapter_index": 1, "items": []},
            "learner_profile_text": "学习者容易漏看单位。",
            "user_profile": {"prompt_addendum": "多检查易错点。"},
            "summary_enhanced": {
                "chapter_evidence_map": [{"chapter_index": 1, "evidence_ids": ["e1"]}],
                "high_confidence_evidence": [
                    {
                        "evidence_id": "e1",
                        "text": "矩阵乘法依赖行列配对",
                        "source_ref": "local://file/f1/section/s1",
                    }
                ],
            },
            "chapters_enhanced": [{"chapter_index": 1, "evidence_ids": ["e1"], "teaching_outline": ["先定义再例题"]}],
            "guideline": {
                "writing_rules": ["先定义再例题"],
                "canonical_glossary": [{"term": "矩阵乘法", "definition": "按行列配对求和", "target_chapters": [1]}],
            },
            "dispatch_table": {
                "items": [
                    {
                        "chapter_index": 1,
                        "source_slices": [{"section_ref": "s1", "section_title": "矩阵乘法"}],
                    }
                ]
            },
            "document_backbone": {"chapter_count": 1},
        }
    )

    assert "reviewed_chapter_draft_items" not in result
    assert result["reviewed_chapter_overlay_items"] == [
        {
            "chapter_index": 1,
            "review_report_ref": "ch01_review",
            "warnings": ["需要补例题"],
            "patched": False,
        }
    ]
    assert result["kg_refinement_items"][0]["chapter_index"] == 1
    assert result["llm_calls_total"] == 0
    assert result["kg_refinement_items"][0]["node_count"] >= 1
    assert result["kg_refinement_items"][0]["needs_repair"] is False
    assert captured_review_kwargs["guideline_summary"]["canonical_glossary"][0]["term"] == "矩阵乘法"
    assert captured_review_kwargs["dispatch_item"]["source_slices"][0]["section_ref"] == "s1"
    assert captured_review_kwargs["chapter_contract"]["evidence_ids"] == ["e1"]
    assert captured_review_kwargs["evidence_items"][0]["evidence_id"] == "e1"
    assert "学习者容易漏看单位" in captured_review_kwargs["learner_profile_text"]
    assert "多检查易错点" in captured_review_kwargs["learner_profile_text"]
    assert captured_publish_payload["kg_prefetch_incremental_started"] is False


@pytest.mark.anyio
async def test_document_consistency_llm_review_adds_document_actions(monkeypatch) -> None:
    captured_kwargs: dict = {}
    captured_messages: list[dict[str, str]] = []
    async def fake_completion(*args, **kwargs):
        captured_messages.extend(args[0])
        captured_kwargs.update(kwargs)
        return LLMDocumentConsistencyReviewResult(
            passed=False,
            issues=[
                {
                    "severity": "warning",
                    "issue_type": "notation_drift",
                    "detail": "第 2 章使用 A 表示面积，但第 1 章使用 A 表示矩阵。",
                }
            ],
            glossary_warnings=["A 的符号含义跨章不一致。"],
            actions=[
                ReviewAction(
                    action_type="section_patch",
                    chapter_index=2,
                    severity="warning",
                    reason="跨章符号含义不一致",
                    target_anchor="符号说明",
                    instruction="补充本章 A 的含义并避免和矩阵符号混淆。",
                    expected_effect="后续章节和考试题能稳定定位符号含义。",
                )
            ],
        )

    monkeypatch.setattr(quality, "acompletion_with_fallback", fake_completion)
    report, actions, llm_calls = await quality.review_document_consistency_with_llm(
        reviewed_chapters=[
            ReviewedChapterDraft(
                chapter_index=1,
                title="矩阵基础",
                markdown="# 矩阵基础\n\n## 符号说明\n\nA 表示矩阵。",
            ),
            ReviewedChapterDraft(
                chapter_index=2,
                title="面积计算",
                markdown="# 面积计算\n\n## 符号说明\n\nA 表示面积。",
            ),
        ],
        document_backbone=DocumentBackbone(),
        expected_chapter_count=2,
        digest_mode="systematic",
        guideline={"notation_rules": [{"symbol": "A", "meaning": "矩阵", "target_chapters": [1]}]},
        dispatch_table={"items": [{"chapter_index": 2, "source_section_refs": ["s2"]}]},
        learner_profile_text="学习者容易混淆符号。",
    )

    assert llm_calls == 1
    assert captured_kwargs["response_model"] is LLMDocumentConsistencyReviewResult
    assert "A 表示矩阵" in captured_messages[1]["content"]
    assert "A 表示面积" in captured_messages[1]["content"]
    assert "markdown_excerpt" not in captured_messages[1]["content"]
    assert report.passed is False
    assert report.source_summary["document_review_mode"] == "llm_structured_with_rule_guardrails"
    assert report.source_summary["llm_action_count"] == 1
    assert "A 的符号含义跨章不一致。" in report.glossary_warnings
    assert actions[0].action_id == "document_review_01_section_patch"
    assert actions[0].chapter_index == 2
    assert actions[0].status == "recorded"


@pytest.mark.anyio
async def test_document_consistency_node_keeps_rule_actions_with_single_llm_review(monkeypatch) -> None:
    monkeypatch.setattr(review_content, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)

    async def fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(review_content, "publish_docgen_progress", fake_publish)

    async def fake_document_review(**kwargs):
        del kwargs
        return (
            DocumentConsistencyReport(
                source_summary={"document_review_mode": "llm_structured_with_rule_guardrails"}
            ),
            [],
            1,
        )

    monkeypatch.setattr(review_content, "review_document_consistency_with_llm", fake_document_review)
    node = review_content.build_document_consistency_review_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "digest_mode": "systematic",
            "enhanced_chapter_drafts": [
                {"chapter_index": 1, "title": "第一章", "markdown": "# 第一章\n\n正文"},
                {"chapter_index": 2, "title": "第二章", "markdown": "# 第二章\n\n正文"},
            ],
            "reviewed_chapter_overlay_items": [],
            "review_action_items": [
                ReviewAction(
                    action_id="chapter_review_record",
                    action_type="record_only",
                    chapter_index=1,
                    severity="info",
                    reason="已记录章节提示。",
                ).model_dump(mode="json")
            ],
            "chapter_tasks": [
                {"chapter_index": 1, "confirmed_title": "第一章"},
                {"chapter_index": 2, "confirmed_title": "第二章"},
            ],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "guideline": {"writing_rules": ["统一符号"]},
            "dispatch_table": {"items": [{"chapter_index": 1}, {"chapter_index": 2}]},
            "learner_profile_text": "学习者容易混淆符号。",
        }
    )

    assert result["review_decision"] == "publish_with_warnings"
    assert result["llm_calls_total"] == 1
    assert [item["action_id"] for item in result["review_actions"]] == [
        "chapter_review_record",
    ]
    assert result["document_consistency_report"]["source_summary"]["document_review_mode"] == (
        "llm_structured_with_rule_guardrails"
    )


@pytest.mark.anyio
async def test_document_consistency_node_preserves_enhanced_kg_prefetch_status(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_publish(*args, **kwargs):
        captured["progress_payload"] = kwargs.get("payload")

    monkeypatch.setattr(review_content, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "publish_docgen_progress", fake_publish)

    async def fake_document_review(**kwargs):
        del kwargs
        return (
            DocumentConsistencyReport(
                source_summary={"document_review_mode": "llm_structured_with_rule_guardrails"}
            ),
            [],
            1,
        )

    monkeypatch.setattr(review_content, "review_document_consistency_with_llm", fake_document_review)

    node = review_content.build_document_consistency_review_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_reviewed_prefetch",
            "digest_mode": "systematic",
            "enhanced_chapter_drafts": [
                {
                    "chapter_index": 1,
                    "title": "矩阵乘法",
                    "markdown": "# 矩阵乘法\n\n## 行列配对\n\nreview 后正文。",
                }
            ],
            "reviewed_chapter_overlay_items": [
                {"chapter_index": 1, "warnings": [], "patched": False, "review_report_ref": "review://1"}
            ],
            "review_action_items": [],
            "kg_refinement_items": [{"chapter_index": 1, "nodes": [{"name": "行列配对"}]}],
            "chapter_tasks": [{"chapter_index": 1, "confirmed_title": "矩阵乘法"}],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "guideline": {"writing_rules": ["统一符号"]},
            "dispatch_table": {"items": [{"chapter_index": 1}]},
            "preliminary_kg": {"nodes": [{"name": "矩阵乘法"}]},
            "learner_profile_text": "学习者容易混淆矩阵乘法。",
            "kg_prefetch_status": "running_from_enhanced_chapters",
        }
    )

    assert result["kg_prefetch_status"] == "running_from_enhanced_chapters"
    assert result["llm_calls_total"] == 1
    assert result["document_consistency_report"]["source_summary"]["document_review_mode"] == (
        "llm_structured_with_rule_guardrails"
    )
    assert captured["progress_payload"]["kg_prefetch_status"] == "running_from_enhanced_chapters"


@pytest.mark.anyio
async def test_repair_node_preserves_enhanced_kg_prefetch_status(monkeypatch) -> None:
    repaired_chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="矩阵乘法",
        markdown="# 矩阵乘法\n\n## 核心概念\n\n新增了维度匹配的易错提醒。",
        patched=True,
    )
    action = ReviewAction(
        action_id="repair_kg_1",
        action_type="section_patch",
        chapter_index=1,
        reason="缺少易错提醒。",
        status="applied",
    )
    trace = RepairTraceItem(
        trace_id="trace_1",
        action_id=action.action_id,
        action_type=action.action_type,
        chapter_index=1,
        status="applied",
        changed=True,
    )

    captured_repair_kwargs: dict[str, object] = {}

    async def fake_repair_or_route_review_actions(*args, **kwargs):
        captured_repair_kwargs.update(kwargs)
        return [repaired_chapter], [action], [], [trace]

    captured_progress: dict[str, object] = {}

    async def fake_publish_docgen_progress(*args, **kwargs):
        captured_progress["payload"] = kwargs.get("payload")

    monkeypatch.setattr(repair_or_route, "repair_or_route_review_actions", fake_repair_or_route_review_actions)
    monkeypatch.setattr(repair_or_route, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(repair_or_route, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(repair_or_route, "publish_docgen_progress", fake_publish_docgen_progress)

    node = repair_or_route.build_repair_or_route_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_kg_refresh",
            "digest_mode": "systematic",
            "reviewed_chapter_drafts": [
                ReviewedChapterDraft(
                    chapter_index=1,
                    title="矩阵乘法",
                    markdown="# 矩阵乘法\n\n## 核心概念\n\n旧内容。",
                ).model_dump(mode="json")
            ],
            "review_actions": [action.model_dump(mode="json")],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "intent_enhanced": {"learning_goal_text": "学会矩阵乘法"},
            "summary_enhanced": {"concepts": ["矩阵乘法"]},
            "chapters_enhanced": [{"chapter_index": 1, "title": "矩阵乘法"}],
            "guideline": {"writing_rules": ["先定义再举例"]},
            "dispatch_table": {"items": [{"chapter_index": 1}]},
            "preliminary_kg": {"nodes": [{"name": "矩阵乘法"}]},
            "kg_prefetch_status": "running_from_enhanced_chapters",
        }
    )

    assert result["kg_prefetch_status"] == "running_from_enhanced_chapters"
    assert captured_repair_kwargs["allow_llm_patches"] is True
    assert result["kg_refinement_items"][0]["chapter_index"] == 1
    assert result["kg_refinement_items"][0]["node_count"] >= 1
    assert result["kg_refinement_items"][0]["source"] == "docgen_review_refinement"
    assert captured_progress["payload"]["kg_prefetch_status"] == "running_from_enhanced_chapters"


@pytest.mark.anyio
async def test_repair_node_does_not_reextract_unchanged_chapters(monkeypatch) -> None:
    reviewed_chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="矩阵乘法",
        markdown="# 矩阵乘法\n\n## 核心概念\n\nreview 后正文。",
    )
    action = ReviewAction(
        action_id="repair_kg_no_patch",
        action_type="record_only",
        chapter_index=1,
        reason="记录图谱风险。",
        status="recorded",
    )
    trace = RepairTraceItem(
        trace_id="trace_no_patch",
        action_id=action.action_id,
        action_type=action.action_type,
        chapter_index=1,
        status="recorded",
        changed=False,
    )

    captured_repair_kwargs: dict[str, object] = {}

    async def fake_repair_or_route_review_actions(*args, **kwargs):
        captured_repair_kwargs.update(kwargs)
        return [reviewed_chapter], [action], [], [trace]

    captured_prefetch: dict[str, object] = {}

    async def fake_publish_docgen_progress(*args, **kwargs):
        captured_prefetch["progress_payload"] = kwargs.get("payload")

    monkeypatch.setattr(repair_or_route, "repair_or_route_review_actions", fake_repair_or_route_review_actions)
    monkeypatch.setattr(repair_or_route, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(repair_or_route, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(repair_or_route, "publish_docgen_progress", fake_publish_docgen_progress)

    node = repair_or_route.build_repair_or_route_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_kg_no_patch",
            "digest_mode": "sprint",
            "reviewed_chapter_drafts": [reviewed_chapter.model_dump(mode="json")],
            "review_actions": [action.model_dump(mode="json")],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "intent_enhanced": {"learning_goal_text": "学会矩阵乘法"},
            "summary_enhanced": {"concepts": ["矩阵乘法"]},
            "chapters_enhanced": [{"chapter_index": 1, "title": "矩阵乘法"}],
            "guideline": {"writing_rules": ["先定义再举例"]},
            "dispatch_table": {"items": [{"chapter_index": 1}]},
            "preliminary_kg": {"nodes": [{"name": "矩阵乘法"}]},
            "kg_refinement_items": [{"chapter_index": 1, "nodes": [{"name": "核心概念"}]}],
            "kg_prefetch_status": "running_from_enhanced_chapters",
        }
    )

    assert result["kg_prefetch_status"] == "running_from_enhanced_chapters"
    assert captured_repair_kwargs["allow_llm_patches"] is False
    assert result["kg_refinement_items"] == []
    assert captured_prefetch["progress_payload"]["kg_prefetch_status"] == "running_from_enhanced_chapters"


@pytest.mark.anyio
async def test_prepare_knowledge_graph_starts_missing_prefetch_but_defers_quality_ready_draft(monkeypatch) -> None:
    snapshot_calls = 0
    captured: dict[str, object] = {}

    def fake_snapshot_docgen_kg_prefetch(*args, **kwargs):
        nonlocal snapshot_calls
        del args, kwargs
        snapshot_calls += 1
        if snapshot_calls == 1:
            return [], {
                "prefetch_status": "missing",
                "prefetch_section_count": 0,
                "prefetch_failed_section_count": 0,
                "prefetch_ready": 0,
            }
        return [], {
            "prefetch_status": "running",
            "prefetch_section_count": 0,
            "prefetch_failed_section_count": 0,
            "prefetch_ready": 0,
        }

    def fake_start_docgen_kg_prefetch(**kwargs):
        captured.update(kwargs)
        return True

    async def fake_publish_docgen_progress(*args, **kwargs):
        captured["progress_payload"] = kwargs.get("payload")

    monkeypatch.setattr(
        prepare_knowledge_graph,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(sync_after_docgen=True, prefetch_during_docgen=True)
        ),
    )
    monkeypatch.setattr(
        prepare_knowledge_graph,
        "snapshot_docgen_kg_prefetch",
        fake_snapshot_docgen_kg_prefetch,
    )
    monkeypatch.setattr(
        prepare_knowledge_graph,
        "start_docgen_kg_prefetch",
        fake_start_docgen_kg_prefetch,
    )
    monkeypatch.setattr(prepare_knowledge_graph, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "publish_docgen_progress", fake_publish_docgen_progress)

    node = prepare_knowledge_graph.build_prepare_knowledge_graph_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_kg_prepare",
            "digest_mode": "systematic",
            "reviewed_chapter_drafts": [
                ReviewedChapterDraft(
                    chapter_index=1,
                    title="矩阵乘法",
                    markdown="# 矩阵乘法\n\n## 行列配对\n\n修补后的章节内容。\n\n## 单元测试\n\n1. 计算 AB。",
                    patched=True,
                ).model_dump(mode="json")
            ],
            "enhanced_chapter_drafts": [
                ReviewedChapterDraft(
                    chapter_index=1,
                    title="矩阵乘法",
                    markdown="# 矩阵乘法\n\n旧增强内容。\n\n## 单元测试\n\n1. 计算 AB。",
                ).model_dump(mode="json")
            ],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "preliminary_kg": {
                "nodes": [
                    {"name": "矩阵乘法", "knowledge_unit_type": "topic", "chapter_index": 1},
                    {"name": "矩阵乘法维度检查", "knowledge_unit_type": "skill", "chapter_index": 1},
                ],
                "edges": [
                    {"source_name": "矩阵乘法维度检查", "target_name": "矩阵乘法", "edge_type": "part_of", "chapter_index": 1}
                ],
            },
        }
    )

    assert result["kg_prefetch_status"] == "running"
    assert result["kg_prefetch_ready"] is False
    assert result["kg_prefetch_metrics"]["prefetch_section_count"] == 0
    assert result["docgen_kg_draft"]["node_count"] >= 2
    assert result["docgen_kg_draft"]["nodes"][0]["name"]
    assert result["docgen_kg_draft"]["fast_visible_ready"] is True
    assert result["docgen_kg_draft"]["quality_status"] == "ready"
    assert result["kg_prefetch_metrics"]["docgen_kg_quality_status"] == "ready"
    assert int(result["kg_prefetch_metrics"]["docgen_kg_quality_warning_count"]) >= 0
    assert result["kg_prefetch_metrics"]["docgen_kg_exam_ready_unit_count"] >= 1
    assert result["kg_prefetch_metrics"]["docgen_kg_profile_ready_unit_count"] >= 1
    assert result["kg_prefetch_metrics"]["docgen_kg_structure_edge_count"] >= 1
    assert result["kg_prefetch_metrics"]["docgen_kg_examine_profile_ready"] == 1
    assert result["kg_draft_early_persist_metrics"] == {
        "ok": True,
        "skipped": True,
        "skip_reason": "deferred_until_document_publish",
        "persisted": 0,
        "unit_count": 0,
        "created_unit_count": 0,
        "updated_unit_count": 0,
        "edge_count": 0,
        "created_edge_count": 0,
        "updated_edge_count": 0,
    }
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_unit_count"] == 0
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_edge_count"] == 0
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_persisted"] == 0
    assert snapshot_calls == 2
    assert "修补后的章节内容。" in captured["chapters"][0]["markdown"]
    assert captured["docgen_manifest"]["preliminary_kg"]["nodes"][0]["name"] == "矩阵乘法"
    assert captured["progress_payload"]["kg_prefetch_ready"] is False
    assert captured["progress_payload"]["docgen_kg_draft_node_count"] >= 2
    assert captured["progress_payload"]["docgen_kg_quality_status"] == "ready"
    assert captured["progress_payload"]["docgen_kg_quality_audit"]["missing_chapter_count"] == 0
    assert captured["progress_payload"]["docgen_kg_examine_profile_ready"] is True
    assert captured["progress_payload"]["docgen_kg_pre_publish_unit_count"] == 0
    assert captured["progress_payload"]["docgen_kg_pre_publish_edge_count"] == 0
    assert captured["progress_payload"]["docgen_kg_pre_publish_persisted"] == 0


def _prepare_knowledge_graph_finalize_failure_case(
    monkeypatch: pytest.MonkeyPatch,
    *,
    progress_failure: BaseException,
):
    prefetch_metrics = {
        "prefetch_status": "completed",
        "prefetch_section_count": 1,
        "prefetch_failed_section_count": 0,
        "prefetch_ready": 1,
    }
    draft = {
        "node_count": 1,
        "edge_count": 0,
        "chapter_coverage_ratio": 1.0,
        "fast_visible_ready": True,
        "quality_ready": True,
        "quality_status": "ready",
        "quality_score": 1.0,
        "quality_audit": {},
    }

    async def fail_progress(*_args, **_kwargs):
        raise progress_failure

    monkeypatch.setattr(
        prepare_knowledge_graph,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(sync_after_docgen=True, prefetch_during_docgen=True)
        ),
    )
    monkeypatch.setattr(
        prepare_knowledge_graph,
        "snapshot_docgen_kg_prefetch",
        lambda **_kwargs: ([], dict(prefetch_metrics)),
    )
    monkeypatch.setattr(prepare_knowledge_graph, "build_docgen_kg_draft", lambda **_kwargs: dict(draft))
    monkeypatch.setattr(prepare_knowledge_graph, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "publish_docgen_progress", fail_progress)

    node = prepare_knowledge_graph.build_prepare_knowledge_graph_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    state = {
        "course_id": "course_state_contract",
        "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
        "build_group_id": "build-group-finalize",
        "build_session_id": "build-session-finalize",
        "digest_mode": "systematic",
    }
    return node, state


@pytest.mark.anyio
async def test_prepare_knowledge_graph_routes_finalize_failure_to_rollback(monkeypatch) -> None:
    node, state = _prepare_knowledge_graph_finalize_failure_case(
        monkeypatch,
        progress_failure=RuntimeError("progress store unavailable"),
    )

    result = await node(state)

    assert result["error"] == "knowledge_graph_prepare_finalize_failed"
    assert result["cancel_after_rollback"] is False
    assert result["kg_draft_early_persist_metrics"]["skip_reason"] == "deferred_until_document_publish"
    assert result["kg_draft_early_persist_metrics"]["persisted"] == 0
    assert graph.route_after_step(result) == "fail"


@pytest.mark.anyio
async def test_prepare_knowledge_graph_routes_cancellation_to_rollback_state(monkeypatch) -> None:
    node, state = _prepare_knowledge_graph_finalize_failure_case(
        monkeypatch,
        progress_failure=asyncio.CancelledError(),
    )

    result = await node(state)

    assert result["error"] == "knowledge_build_cancelled"
    assert result["cancel_after_rollback"] is True
    assert result["kg_draft_early_persist_metrics"]["skip_reason"] == "deferred_until_document_publish"
    assert result["kg_draft_early_persist_metrics"]["persisted"] == 0
    assert graph.route_after_step(result) == "fail"


@pytest.mark.anyio
async def test_prepare_knowledge_graph_preserves_running_enhanced_prefetch(monkeypatch) -> None:
    snapshot_calls = 0
    captured: dict[str, object] = {}
    call_order: list[str] = []

    def fake_snapshot_docgen_kg_prefetch(*args, **kwargs):
        nonlocal snapshot_calls
        del args, kwargs
        call_order.append("snapshot")
        snapshot_calls += 1
        return [], {
            "prefetch_status": "running",
            "prefetch_section_count": 0,
            "prefetch_failed_section_count": 0,
            "prefetch_ready": 0,
        }

    def fake_start_docgen_kg_prefetch(**kwargs):
        del kwargs
        raise AssertionError("running enhanced-document prefetch must not be restarted")

    async def fake_publish_docgen_progress(*args, **kwargs):
        captured["progress_payload"] = kwargs.get("payload")

    monkeypatch.setattr(
        prepare_knowledge_graph,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(sync_after_docgen=True, prefetch_during_docgen=True)
        ),
    )
    monkeypatch.setattr(
        prepare_knowledge_graph,
        "snapshot_docgen_kg_prefetch",
        fake_snapshot_docgen_kg_prefetch,
    )
    monkeypatch.setattr(
        prepare_knowledge_graph,
        "start_docgen_kg_prefetch",
        fake_start_docgen_kg_prefetch,
    )
    monkeypatch.setattr(prepare_knowledge_graph, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "publish_docgen_progress", fake_publish_docgen_progress)

    node = prepare_knowledge_graph.build_prepare_knowledge_graph_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_kg_final_titles",
            "digest_mode": "systematic",
            "title_review_report": {"changed_count": 0},
            "final_chapter_titles": [
                {
                    "chapter_index": 1,
                    "before": "最终矩阵运算",
                    "after": "最终矩阵运算",
                    "changed": False,
                }
            ],
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "最终矩阵运算",
                    "markdown": "# 最终矩阵运算\n\n## 行列配对\n\n最终锁题后的正文。\n\n## 单元测试\n\n1. 计算 AB。",
                    "summary": "讲清矩阵乘法。",
                    "source_scope": {"source_file_ids": ["f1"]},
                }
            ],
            "reviewed_chapter_drafts": [
                ReviewedChapterDraft(
                    chapter_index=1,
                    title="最终矩阵运算",
                    markdown="# 最终矩阵运算\n\n## 行列配对\n\n锁题前正文。\n\n## 单元测试\n\n1. 计算 AB。",
                ).model_dump(mode="json")
            ],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "preliminary_kg": {
                "nodes": [
                    {"name": "最终矩阵运算", "knowledge_unit_type": "topic", "chapter_index": 1},
                    {"name": "矩阵乘法", "knowledge_unit_type": "concept", "chapter_index": 1},
                    {"name": "矩阵乘法维度检查", "knowledge_unit_type": "skill", "chapter_index": 1},
                ],
                "edges": [
                    {"source_name": "矩阵乘法", "target_name": "最终矩阵运算", "edge_type": "part_of", "chapter_index": 1},
                    {"source_name": "矩阵乘法维度检查", "target_name": "矩阵乘法", "edge_type": "assesses", "chapter_index": 1},
                ],
            },
        }
    )

    assert snapshot_calls == 1
    assert call_order == ["snapshot"]
    assert result["kg_prefetch_status"] == "running"
    assert result["docgen_kg_draft"]["covered_chapter_indices"] == [1]
    assert result["docgen_kg_draft"]["fast_visible_ready"] is True
    assert result["kg_draft_early_persist_metrics"]["skip_reason"] == "deferred_until_document_publish"
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_persisted"] == 0


@pytest.mark.anyio
async def test_prepare_knowledge_graph_uses_ready_draft_when_prefetch_is_still_running(monkeypatch) -> None:
    snapshot_calls = 0
    captured: dict[str, object] = {}
    payload = SectionExtractionPayload(
        units=[
            MarkdownKnowledgeUnit(
                anchor="ku_matrix_topic",
                name="矩阵基础",
                knowledge_unit_type="topic",
                summary="矩阵基础章节主题。",
                body_markdown="矩阵基础章节主题。",
                chapter_index=1,
                quote_text="矩阵基础",
            ),
            MarkdownKnowledgeUnit(
                anchor="ku_matrix_multiply",
                name="矩阵乘法",
                knowledge_unit_type="concept",
                summary="按行列配对求和。",
                body_markdown="按行列配对求和。",
                chapter_index=1,
                quote_text="按行列配对求和。",
            ),
            MarkdownKnowledgeUnit(
                anchor="ku_dimension_check",
                name="维度匹配检查",
                knowledge_unit_type="skill",
                summary="矩阵乘法前检查行列维度是否匹配。",
                body_markdown="矩阵乘法前检查行列维度是否匹配。",
                chapter_index=1,
                quote_text="矩阵乘法前检查行列维度是否匹配。",
            ),
        ],
        pending_edges=[
            PendingMarkdownExtractedEdge(
                source_candidate_id="concept",
                target_candidate_id="topic",
                source_name="矩阵乘法",
                target_name="矩阵基础",
                edge_type="part_of",
                description="矩阵乘法属于矩阵基础。",
                chapter_index=1,
            ),
            PendingMarkdownExtractedEdge(
                source_candidate_id="dimension_check",
                target_candidate_id="concept",
                source_name="维度匹配检查",
                target_name="矩阵乘法",
                edge_type="assesses",
                description="维度匹配检查用于判断矩阵乘法掌握情况。",
                chapter_index=1,
            )
        ],
        candidate_id_to_anchor={
            "topic": "ku_matrix_topic",
            "concept": "ku_matrix_multiply",
            "dimension_check": "ku_dimension_check",
        },
        anchors_by_name={
            "矩阵基础": ["ku_matrix_topic"],
            "矩阵乘法": ["ku_matrix_multiply"],
            "维度匹配检查": ["ku_dimension_check"],
        },
        anchors_by_normalized_name={
            "矩阵基础": ["ku_matrix_topic"],
            "矩阵乘法": ["ku_matrix_multiply"],
            "维度匹配检查": ["ku_dimension_check"],
        },
        node_contexts_by_anchor={},
        section_context=SectionExtractionContext(
            section_index=1,
            title="矩阵乘法",
            header_path="矩阵基础 / 矩阵乘法",
            body_markdown="按行列配对求和。",
            primary_anchor="ku_matrix_multiply",
            primary_name="矩阵乘法",
            primary_type="concept",
        ),
        diagnostics={
            "section_count": 1,
            "successful_section_count": 1,
            "failed_section_count": 0,
            "llm_section_count": 1,
            "markdown_short_circuit_section_count": 0,
            "llm_error_count": 0,
            "empty_llm_result_count": 0,
            "empty_repair_attempt_count": 0,
            "empty_repair_success_count": 0,
            "total_extracted_node_count": 3,
            "total_extracted_edge_count": 2,
        },
    )
    record = SectionExtractionRecord(
        section_key="chapter:1",
        content_hash="hash-ready",
        task_index=1,
        source_chapter_index=1,
        source_kind="chapter_final",
        title="矩阵乘法",
        payload=payload,
    )

    def fake_snapshot_docgen_kg_prefetch(*args, **kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return [record], {
            "prefetch_status": "running",
            "prefetch_section_count": 1,
            "prefetch_failed_section_count": 0,
            "prefetch_ready": 0,
        }

    async def fake_publish_docgen_progress(*args, **kwargs):
        captured["progress_payload"] = kwargs.get("payload")

    monkeypatch.setattr(
        prepare_knowledge_graph,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(sync_after_docgen=True, prefetch_during_docgen=True)
        ),
    )
    monkeypatch.setattr(prepare_knowledge_graph, "snapshot_docgen_kg_prefetch", fake_snapshot_docgen_kg_prefetch)
    monkeypatch.setattr(prepare_knowledge_graph, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_knowledge_graph, "publish_docgen_progress", fake_publish_docgen_progress)

    node = prepare_knowledge_graph.build_prepare_knowledge_graph_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_kg_quality_recheck",
            "digest_mode": "systematic",
            "reviewed_chapter_drafts": [
                ReviewedChapterDraft(
                    chapter_index=1,
                    title="矩阵基础",
                    markdown="# 矩阵基础\n\n## 核心讲解\n\n只包含普通概念，还缺诊断形状。",
                ).model_dump(mode="json")
            ],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "preliminary_kg": {
                "nodes": [
                    {
                        "name": "矩阵乘法",
                        "knowledge_unit_type": "concept",
                        "chapter_index": 1,
                        "summary": "按行列配对求和。",
                    }
                ]
            },
        }
    )

    assert snapshot_calls == 1
    assert result["kg_prefetch_metrics"]["docgen_kg_quality_recheck_waited"] == 0
    assert result["kg_prefetch_ready"] is False
    assert result["docgen_kg_draft"]["quality_ready"] is True
    assert result["docgen_kg_draft"]["quality_status"] == "ready"
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_unit_count"] == 0
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_edge_count"] == 0
    assert result["kg_prefetch_metrics"]["docgen_kg_pre_publish_persisted"] == 0
    assert result["kg_draft_early_persist_metrics"]["skip_reason"] == "deferred_until_document_publish"
    assert captured["progress_payload"]["docgen_kg_quality_status"] == "ready"


@pytest.mark.anyio
async def test_evidence_patch_is_recorded_without_llm_rewrite(monkeypatch) -> None:
    async def fail_if_called(*args, **kwargs):
        del args, kwargs
        raise AssertionError("evidence warning must not call the LLM patcher")

    monkeypatch.setattr(repair, "acompletion_with_fallback", fail_if_called)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="矩阵乘法",
        markdown="# 矩阵乘法\n\n## 核心规则\n\n矩阵乘法按行列配对。\n",
    )
    action = ReviewAction(
        action_id="evidence_1",
        action_type="evidence_patch",
        chapter_index=1,
        reason="主张证据支撑低于阈值。",
        target_anchor="核心规则",
    )

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=[action],
    )

    assert repaired[0].markdown == chapter.markdown
    assert updated_actions[0].status == "recorded"
    assert len(unresolved) == 1
    assert traces[0].changed is False
    assert traces[0].llm_attempted is False


@pytest.mark.anyio
async def test_repair_patch_applies_local_snippet(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown="## 易错补充\n\n- 先看单位，再代入公式。",
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\n面积表示平面的大小。\n\n## 本章小结\n\n记住公式。\n",
    )
    action = ReviewAction(
        action_id="a1",
        action_type="section_patch",
        chapter_index=1,
        reason="缺少易错提醒",
        target_anchor="核心概念",
        instruction="补充单位易错点。",
    )

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=[action],
    )

    assert unresolved == []
    assert updated_actions[0].status == "applied"
    assert traces[0].changed is True
    assert "## 易错补充" in repaired[0].markdown
    assert repaired[0].markdown.index("## 易错补充") < repaired[0].markdown.index("## 本章小结")


@pytest.mark.anyio
async def test_repair_rejects_patch_that_repeats_existing_h2(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown="## 核心概念\n\n- 把已有小节再写一遍。",
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\n面积表示平面的大小。\n\n## 本章小结\n\n记住公式。\n",
    )
    action = ReviewAction(
        action_id="a1",
        action_type="section_patch",
        chapter_index=1,
        reason="缺少补充说明",
        target_anchor="核心概念",
        instruction="补充说明。",
    )

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=[action],
    )

    assert repaired[0].markdown == chapter.markdown
    assert updated_actions[0].status == "downgraded"
    assert unresolved
    assert traces[0].changed is False
    assert "Rejected unsafe LLM local patch" in traces[0].detail


@pytest.mark.anyio
async def test_repair_appends_unit_test_patch_to_chapter_end(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            target_anchor="核心概念",
            patch_markdown=(
                "## 单元测试\n\n"
                "> [!QUESTION]\n"
                "> **题目/任务**：判断面积单位是否统一。\n>\n"
                "> **答案/结论**：必须先统一单位再计算。\n"
            ),
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\n面积表示平面的大小。\n\n## 本章小结\n\n记住公式。\n",
    )
    action = ReviewAction(
        action_id="review_ch01_unit_test",
        action_type="section_patch",
        chapter_index=1,
        reason="缺少固定的章末 `## 单元测试` 模块。",
        target_anchor="核心概念",
        instruction="在本章末尾补齐固定二级标题 `## 单元测试`。",
        constraints=["`## 单元测试` 必须是本章最后一个二级标题。"],
    )

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=[action],
    )

    markdown = repaired[0].markdown
    assert unresolved == []
    assert updated_actions[0].status == "applied"
    assert traces[0].changed is True
    assert markdown.index("## 本章小结") < markdown.index("## 单元测试")
    assert markdown.rstrip().endswith("> **答案/结论**：必须先统一单位再计算。")


@pytest.mark.anyio
async def test_repair_batches_multiple_actions_into_one_llm_patch(monkeypatch) -> None:
    calls = 0

    async def fake_completion(*args, **kwargs):
        nonlocal calls
        calls += 1
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown="## 综合补充\n\n- 同一段 patch 同时补充易错提醒和第二个例题。",
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\n面积表示平面的大小。\n\n## 本章小结\n\n记住公式。\n",
    )
    actions = [
        ReviewAction(
            action_id="a1",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少易错提醒",
            target_anchor="核心概念",
            instruction="补充单位易错点。",
        ),
        ReviewAction(
            action_id="a2",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少第二个例题",
            target_anchor="核心概念",
            instruction="补充第二个例题。",
        ),
    ]

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=actions,
    )

    assert calls == 1
    assert [action.status for action in updated_actions] == ["applied", "applied"]
    assert unresolved == []
    assert [trace.changed for trace in traces] == [True, True]
    assert [trace.llm_attempted for trace in traces] == [True, True]
    assert len({trace.llm_call_group for trace in traces if trace.llm_call_group}) == 1
    assert "## 综合补充" in repaired[0].markdown


@pytest.mark.anyio
async def test_repair_can_continue_when_model_leaves_actions_for_next_round(monkeypatch) -> None:
    calls = 0

    async def fake_completion(*args, **kwargs):
        nonlocal calls
        calls += 1
        covered = ["a1"] if calls == 1 else ["a2"]
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown=f"## 补充 {calls}\n\n- 第 {calls} 轮局部补充。",
            covered_action_ids=covered,
        )

    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ROUNDS_PER_CHAPTER", 2)
    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\n面积表示平面的大小。\n\n## 本章小结\n\n记住公式。\n",
    )
    actions = [
        ReviewAction(
            action_id="a1",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少易错提醒",
            target_anchor="核心概念",
            instruction="补充单位易错点。",
        ),
        ReviewAction(
            action_id="a2",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少第二个例题",
            target_anchor="核心概念",
            instruction="补充第二个例题。",
        ),
    ]

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=actions,
    )

    assert calls == 2
    assert [action.status for action in updated_actions] == ["applied", "applied"]
    assert unresolved == []
    assert [trace.changed for trace in traces] == [True, True]
    assert [trace.llm_attempted for trace in traces] == [True, True]
    assert len({trace.llm_call_group for trace in traces if trace.llm_call_group}) == 2
    assert "## 补充 1" in repaired[0].markdown
    assert "## 补充 2" in repaired[0].markdown


@pytest.mark.anyio
async def test_repair_uses_covered_action_anchor_when_patch_target_missing(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown="## 应用补充\n\n- 先识别题目给出的边长，再选择面积公式。",
            covered_action_ids=["a2"],
        )

    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ROUNDS_PER_CHAPTER", 1)
    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown=(
            "# 面积\n\n"
            "## 核心概念\n\n"
            "面积表示平面的大小。\n\n"
            "## 应用练习\n\n"
            "先做基础题。\n\n"
            "## 本章小结\n\n"
            "记住公式。\n"
        ),
    )
    actions = [
        ReviewAction(
            action_id="a1",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少概念易错提醒",
            target_anchor="核心概念",
            instruction="补充单位易错点。",
        ),
        ReviewAction(
            action_id="a2",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少应用题步骤",
            target_anchor="应用练习",
            instruction="补充应用题步骤。",
        ),
    ]

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=actions,
    )

    markdown = repaired[0].markdown
    assert [action.status for action in updated_actions] == ["skipped", "applied"]
    assert len(unresolved) == 1
    assert [trace.changed for trace in traces] == [False, True]
    assert markdown.index("## 应用练习") < markdown.index("## 应用补充")
    assert markdown.index("## 应用补充") < markdown.index("## 本章小结")


@pytest.mark.anyio
async def test_deterministic_rendering_patch_does_not_consume_llm_patch_limit(monkeypatch) -> None:
    calls = 0

    async def fake_completion(*args, **kwargs):
        nonlocal calls
        calls += 1
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown="## 易错补充\n\n- 先看单位，再代入公式。",
        )

    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ROUNDS_PER_CHAPTER", 1)
    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    monkeypatch.setattr(
        repair,
        "find_docgen_presentation_issues",
        lambda markdown: ["Markdown 渲染结构异常"] if "BROKEN_TABLE" in markdown else [],
    )
    monkeypatch.setattr(
        repair,
        "normalize_docgen_presentation",
        lambda markdown, **kwargs: markdown.replace("BROKEN_TABLE", "FIXED_TABLE"),
    )
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\nBROKEN_TABLE\n\n## 本章小结\n\n记住公式。\n",
    )
    actions = [
        ReviewAction(
            action_id="a1",
            action_type="surface_patch",
            chapter_index=1,
            reason="Markdown 渲染结构异常：表格损坏",
            target_anchor="核心概念",
            instruction="修复表格。",
        ),
        ReviewAction(
            action_id="a2",
            action_type="section_patch",
            chapter_index=1,
            reason="缺少易错提醒",
            target_anchor="核心概念",
            instruction="补充单位易错点。",
        ),
    ]

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=actions,
    )

    assert calls == 1
    assert [action.status for action in updated_actions] == ["applied", "applied"]
    assert unresolved == []
    assert [trace.changed for trace in traces] == [True, True]
    assert [trace.llm_attempted for trace in traces] == [False, True]
    assert "FIXED_TABLE" in repaired[0].markdown
    assert "## 易错补充" in repaired[0].markdown


@pytest.mark.anyio
async def test_repair_rejects_patch_that_adds_presentation_regression(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown=(
                "## 易错补充\n\n"
                "- 先看定义。\n"
                "- 再看条件。\n"
                "- 检查符号。\n"
                "- 检查单位。\n"
                "- 代入公式。\n"
                "- 验证边界。\n"
                "- 对照反例。\n"
                "- 回看题干。\n"
                "- 写出结论。\n"
            ),
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="函数与极限",
        markdown="# 函数与极限\n\n## 核心概念\n\n极限描述变量逼近时的趋势。\n\n## 本章小结\n\n抓住趋势。\n",
    )
    action = ReviewAction(
        action_id="a1",
        action_type="section_patch",
        chapter_index=1,
        reason="缺少易错提醒",
        target_anchor="核心概念",
        instruction="补充一个局部易错提醒。",
    )

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=[action],
    )

    assert repaired[0].markdown == chapter.markdown
    assert updated_actions[0].status == "downgraded"
    assert unresolved
    assert "新增展示结构问题" in traces[0].detail
