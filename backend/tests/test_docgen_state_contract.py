from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen import graph
from app.workflows.digest.docgen.lib import quality, repair
from app.workflows.digest.docgen.lib.models import (
    CanonicalClaim,
    CanonicalGlossaryItem,
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    ChapterReviewReport,
    ChapterSourceSlice,
    ConceptDependencyEdge,
    DocGenContext,
    DocumentBackbone,
    DocumentConsistencyReport,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    LLMDocumentConsistencyReviewResult,
    LockedChapterTitle,
    ReviewAction,
    ReviewedChapterDraft,
    SourceAffinityByChapter,
)
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_chapters_enhanced,
    build_dispatch_table,
    build_guideline,
    build_intent_enhanced,
    build_preliminary_kg,
    build_summary_enhanced,
    build_user_profile_enhanced,
)
from app.workflows.digest.docgen.nodes import generate_chapters
from app.workflows.digest.docgen.nodes import build_chapter_execution_briefs, lock_titles_for_chapters, review_content


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


def test_docgen_pipeline_artifacts_keep_stage_outputs_compact() -> None:
    context = DocGenContext(
        course_name="线性代数",
        user_prompt="构建一门复习课",
        learner_profile_text="学习者容易混淆矩阵乘法和线性映射。",
        learner_profile_context={
            "has_profile": True,
            "profile_text": "学习者容易混淆矩阵乘法和线性映射。",
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
                    chapter_index=1,
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
    assert any(node["name"] == "矩阵乘法" and node["knowledge_unit_type_label"] == "概念术语" for node in preliminary_kg["nodes"])
    assert any(edge["source_name"] == "矩阵乘法" and edge["edge_type_label"] == "归属" for edge in preliminary_kg["edges"])


def test_preliminary_kg_splits_labeled_contract_items_into_short_chinese_nodes() -> None:
    preliminary_kg = build_preliminary_kg(
        chapters_enhanced=[
            {
                "chapter_index": 1,
                "title": "数与式基础",
                "required_elements": [
                    "学习目标：熟练掌握有理数、实数、整式与分式运算基础，提升计算准确率",
                ],
                "content_role_targets": {
                    "concept": ["核心概念：绝对值、平方根"],
                    "pitfall": ["易错点：忽略分母不为零、符号错误"],
                },
            }
        ]
    )

    nodes_by_name = {node["name"]: node for node in preliminary_kg["nodes"]}
    assert "学习目标：熟练掌握有理数、实数、整式与分式运算基础，提升计算准确率" not in nodes_by_name
    assert "计算准确率" not in nodes_by_name
    assert {"有理数", "实数", "整式与分式运算基础", "绝对值", "平方根", "忽略分母不为零", "符号错误"} <= set(nodes_by_name)
    assert nodes_by_name["忽略分母不为零"]["knowledge_unit_type"] == "misconception"
    assert nodes_by_name["绝对值"]["knowledge_unit_type"] == "concept"


@pytest.mark.anyio
async def test_chapter_brief_node_receives_dispatch_sources_evidence_and_profile(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_build_chapter_execution_brief(**kwargs):
        captured.update(kwargs)
        return ChapterExecutionBrief(
            chapter_index=1,
            teaching_outline=["先讲定义"],
            content_role_targets={"concept": ["矩阵乘法"]},
            example_coverage_plan=[{"target": "矩阵乘法"}],
            chapter_end_practice_plan=[{"target": "矩阵乘法"}],
            retrieval_queries=["矩阵乘法"],
        )

    async def fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(build_chapter_execution_briefs, "build_chapter_execution_brief", fake_build_chapter_execution_brief)
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

    assert result["chapter_execution_briefs"][0]["chapter_index"] == 1
    assert captured["source_slices"][0]["section_ref"] == "s1"
    assert captured["evidence_items"][0]["evidence_id"] == "e1"
    assert "基础薄弱" in str(captured["learner_profile_text"])
    assert "错误率高" in str(captured["learner_profile_text"])


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

    async def fake_lock_title_for_chapter(**kwargs):
        chapter = kwargs["chapter"]
        return LockedChapterTitle(
            chapter_index=int(chapter["chapter_index"]),
            confirmed_title=str(chapter["title"]),
            enhanced_title=str(chapter["title"]),
            fallback_used=True,
        )

    def fake_append(course_id: str, **kwargs) -> None:
        captured_course_ids.append(course_id)

    def fake_upsert(course_id: str, **kwargs) -> None:
        captured_course_ids.append(course_id)

    monkeypatch.setattr(lock_titles_for_chapters, "lock_title_for_chapter", fake_lock_title_for_chapter)
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
    assert captured_course_ids == ["course_state_contract", "course_state_contract"]


def test_generation_sends_include_docgen_pipeline_artifacts() -> None:
    sends = graph.build_generation_sends(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
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
    assert first["guideline"]["writing_rules"] == ["先定义再举例"]
    assert first["dispatch_table"]["items"][0]["preferred_sources"] == ["local://file/f1/section/s1"]
    assert first["summary_enhanced"]["high_confidence_evidence_units"][0]["evidence_id"] == "e1"
    assert first["chapters_enhanced"][0]["evidence_ids"] == ["e1"]
    assert first["user_profile"]["prompt_addendum"] == "关注易错点。"
    assert "chapter_tasks" not in first


def test_review_sends_only_single_chapter_payload() -> None:
    sends = graph.build_review_sends(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
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
        )
        return reviewed, report, []

    monkeypatch.setattr(review_content, "review_chapter", fake_review_chapter)
    monkeypatch.setattr(review_content, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "upsert_knowledge_build_chapter_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "upsert_knowledge_build_chapter_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)

    async def fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(review_content, "publish_docgen_progress", fake_publish)
    node = review_content.build_review_chapter_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
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
    assert captured_review_kwargs["guideline_summary"]["canonical_glossary"][0]["term"] == "矩阵乘法"
    assert captured_review_kwargs["dispatch_item"]["source_slices"][0]["section_ref"] == "s1"
    assert captured_review_kwargs["chapter_contract"]["evidence_ids"] == ["e1"]
    assert captured_review_kwargs["evidence_items"][0]["evidence_id"] == "e1"
    assert "学习者容易漏看单位" in captured_review_kwargs["learner_profile_text"]
    assert "多检查易错点" in captured_review_kwargs["learner_profile_text"]


@pytest.mark.anyio
async def test_document_consistency_llm_review_adds_document_actions(monkeypatch) -> None:
    captured_kwargs: dict = {}
    scheduler_call: dict = {}

    async def fake_completion(*args, **kwargs):
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

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        scheduler_call["items"] = list(items)
        scheduler_call["max_concurrent"] = max_concurrent
        results = []
        for index, item in enumerate(scheduler_call["items"]):
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            results.append(result)
        return results

    monkeypatch.setattr(quality, "acompletion_with_fallback", fake_completion)
    monkeypatch.setattr(quality, "run_llm_tasks", fake_run_llm_tasks)
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
    assert scheduler_call == {"items": [None], "max_concurrent": 1}
    assert captured_kwargs["response_model"] is LLMDocumentConsistencyReviewResult
    assert report.passed is False
    assert report.source_summary["document_review_mode"] == "llm_structured_with_rule_guardrails"
    assert report.source_summary["llm_action_count"] == 1
    assert "A 的符号含义跨章不一致。" in report.glossary_warnings
    assert actions[0].action_id == "document_review_01_section_patch"
    assert actions[0].chapter_index == 2
    assert actions[0].status == "recorded"


@pytest.mark.anyio
async def test_document_consistency_node_merges_document_review_actions(monkeypatch) -> None:
    async def fake_document_review(**kwargs):
        return (
            DocumentConsistencyReport(
                passed=False,
                issues=[{"severity": "warning", "issue_type": "notation_drift", "detail": "符号不一致。"}],
                source_summary={"document_review_mode": "llm_structured_with_rule_guardrails"},
            ),
            [
                ReviewAction(
                    action_id="document_review_01_section_patch",
                    action_type="section_patch",
                    chapter_index=1,
                    severity="warning",
                    reason="跨章符号不一致",
                    target_anchor="符号说明",
                    instruction="补充符号边界。",
                )
            ],
            1,
        )

    monkeypatch.setattr(review_content, "review_document_consistency_with_llm", fake_document_review)
    monkeypatch.setattr(review_content, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)

    async def fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(review_content, "publish_docgen_progress", fake_publish)
    node = review_content.build_document_consistency_review_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "digest_mode": "systematic",
            "enhanced_chapter_drafts": [
                {"chapter_index": 1, "title": "第一章", "markdown": "# 第一章\n\n正文"}
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
            "chapter_tasks": [{"chapter_index": 1, "confirmed_title": "第一章"}],
            "document_backbone": DocumentBackbone().model_dump(mode="json"),
            "guideline": {"writing_rules": ["统一符号"]},
            "dispatch_table": {"items": [{"chapter_index": 1}]},
            "learner_profile_text": "学习者容易混淆符号。",
        }
    )

    assert result["review_decision"] == "needs_repair"
    assert result["llm_calls_total"] == 1
    assert [item["action_id"] for item in result["review_actions"]] == [
        "chapter_review_record",
        "document_review_01_section_patch",
    ]
    assert result["document_consistency_report"]["source_summary"]["document_review_mode"] == (
        "llm_structured_with_rule_guardrails"
    )


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
async def test_repair_appends_unit_test_patch_to_chapter_end(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            target_anchor="核心概念",
            patch_markdown=(
                "## 单元测试\n\n"
                "> [!PRACTICE]\n"
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
