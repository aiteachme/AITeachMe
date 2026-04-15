from __future__ import annotations

import re

from app.shared.infra.skills import (
    collect_recommended_tool_tags,
    collect_skillpack_defaults,
    list_skills,
    render_prompt_scoped_skillpacks,
    render_skill,
)
from app.shared.infra.tools import list_agent_tools
from app.workflows.digest._shared.pedagogy import (
    analyze_chapter_heading_quality,
    coerce_resolved_chapter_title,
    ensure_chapter_learning_scaffold,
)
from app.workflows.digest.docgen.lib.reporting import build_docgen_lane_summary
from app.workflows.digest.shared.metrics import DigestTokenSummary
from app.workflows.digest.planner.lib.plans import build_fallback_plan
from app.workflows.digest.docgen.prompts import build_docgen_writer_messages
from app.workflows.digest.planner.prompts import build_planner_chapter_title_messages
from app.workflows.digest.shared.contracts import parse_digest_confirmed_plan_contract
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SourcePacket, SubjectProfile


def _build_shared_inputs() -> SharedInputs:
    return SharedInputs(
        source_packets=[
            SourcePacket(
                file_id=1,
                filename="demo.md",
                filetype="markdown",
                markdown_path="demo.md",
                asset_dir="assets",
                normalized_content="偏导数、梯度、方向导数与例题。",
                char_count=120,
                has_formulas=True,
                has_tables=False,
                has_images=False,
            )
        ],
        fast_hints=FastTopicHints(chapter_candidates=["偏导数", "梯度", "方向导数"]),
        subject_profile=SubjectProfile(
            subject_name="高等数学",
            discipline="数学",
            sub_discipline="多元微积分",
            key_topics=["偏导数", "梯度", "方向导数"],
            has_heavy_formulas=True,
        ),
    )


def test_fallback_plan_uses_specific_provisional_titles() -> None:
    plan = build_fallback_plan(
        subject="高等数学",
        user_goal="考前冲刺偏导数",
        digest_mode="sprint",
        tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )

    assert plan.digest_mode == "sprint"
    assert 3 <= len(plan.chapter_plan) <= 6
    assert all("：" in chapter.title for chapter in plan.chapter_plan[:3])
    assert all(not re.fullmatch(r"第\s*\d+\s*章", chapter.title) for chapter in plan.chapter_plan)
    assert len({chapter.title for chapter in plan.chapter_plan}) == len(plan.chapter_plan)
    assert plan.build_constraints["target_chapter_count"] == len(plan.chapter_plan)
    assert "fixed_chapter_count" not in plan.build_constraints
    assert "冲刺型知识文档" in plan.plan_summary


def test_fallback_plan_cleans_request_style_goal_and_dedupes_titles() -> None:
    shared_inputs = _build_shared_inputs().model_copy(deep=True)
    shared_inputs.subject_profile.subject_name = ""
    shared_inputs.fast_hints.chapter_candidates = ["线性代数", "行列式", "特征值", "正交投影"]
    shared_inputs.subject_profile.key_topics = ["线性代数", "行列式", "特征值", "正交投影"]

    plan = build_fallback_plan(
        subject="subj_demo",
        user_goal="帮我整理下线性代数的相关知识",
        digest_mode="sprint",
        tone="encouraging",
        shared_inputs=shared_inputs,
    )

    titles = [chapter.title for chapter in plan.chapter_plan]
    assert all("帮我整理" not in title for title in titles)
    assert len(set(titles)) == len(titles)


def test_learning_scaffold_enforces_sprint_sections() -> None:
    markdown = "# 偏导数直觉建立\n\n这里先给一段简单内容。"
    enriched = ensure_chapter_learning_scaffold(
        markdown,
        title="偏导数直觉建立",
        objective="快速建立偏导数的直觉。",
        required_elements=["核心概念", "直观类比", "易错点"],
        digest_mode="sprint",
        source_count=2,
        chapter_index=1,
        chapter_count=5,
    )

    assert "## 这章先拿下什么" in enriched
    assert "## 本章概念先对齐" in enriched
    assert "## 学完这章你要会什么" in enriched
    assert "的得分抓手" in enriched
    assert "题怎么拆" in enriched
    assert "## 临考前最该记什么" in enriched
    assert "最容易错在哪" in enriched
    assert "## 考前最后 3 分钟回看什么" in enriched
    assert "## 本章导读" not in enriched


def test_learning_scaffold_enforces_systematic_sections_and_mermaid() -> None:
    markdown = "# 多元函数变化图景\n\n本章先从整体结构讲起。"
    enriched = ensure_chapter_learning_scaffold(
        markdown,
        title="多元函数变化图景",
        objective="建立整体知识地图。",
        required_elements=["知识全景", "学习路径", "概念关系"],
        digest_mode="systematic",
        source_count=3,
        chapter_index=1,
        chapter_count=6,
    )

    assert "## 先用什么视角进入《多元函数变化图景》" in enriched
    assert "## 关键概念先对齐" in enriched
    assert "## 学完《多元函数变化图景》后你应该会什么" in enriched
    assert "## 学《多元函数变化图景》前要补什么" in enriched
    assert "## 为什么要学《多元函数变化图景》" in enriched
    assert "的定义与结构" in enriched
    assert "怎么走到应用" in enriched
    assert "## 《多元函数变化图景》在整门课里的位置" in enriched
    assert "## 《多元函数变化图景》真正要带走什么" in enriched
    assert "<!-- [MERMAID:" in enriched
    assert "## 本章要点" not in enriched


def test_learning_scaffold_does_not_duplicate_support_sections() -> None:
    markdown = "# 偏导数\n\n偏导数描述多元函数沿坐标方向的变化率。"
    enriched_once = ensure_chapter_learning_scaffold(
        markdown,
        title="偏导数",
        objective="建立偏导数和梯度的基本联系。",
        required_elements=["偏导数", "梯度"],
        digest_mode="systematic",
        source_count=1,
    )
    enriched_twice = ensure_chapter_learning_scaffold(
        enriched_once,
        title="偏导数",
        objective="建立偏导数和梯度的基本联系。",
        required_elements=["偏导数", "梯度"],
        digest_mode="systematic",
        source_count=1,
    )

    assert enriched_twice.count("## 关键概念先对齐") == 1
    assert enriched_twice.count("## 学完《偏导数》后你应该会什么") == 1


def test_title_resolution_keeps_more_specific_planner_title() -> None:
    chapter = {
        "chapter_index": 1,
        "title": "偏导数：高频题型突破",
    }

    resolved = coerce_resolved_chapter_title("题型突破", chapter=chapter, chapter_index=1)

    assert resolved == "偏导数：高频题型突破"


def test_docgen_lane_summary_uses_new_fields_only() -> None:
    summary = build_docgen_lane_summary(
        {
            "digest_mode": "systematic",
            "course_type": "systematic",
            "chapter_materials": [
                {
                    "chapter_index": 1,
                    "title": "多元函数变化图景",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                    "local_hits": 2,
                    "web_hits": 1,
                    "fallback_used": True,
                    "curated_source_count": 2,
                    "trusted_source_count": 1,
                    "retrieval_profile": "docgen_systematic",
                    "requested_profile": "docgen_systematic",
                    "applied_profile": "docgen_systematic",
                    "teaching_action": "chapter_research",
                    "retriever_stats": {"local_rag": {"query_count": 1}, "bing": {"query_count": 1}},
                    "research_round_count": 2,
                    "research_rounds": [{"round_index": 1}, {"round_index": 2}],
                    "gaps_remaining": ["边界条件"],
                    "coverage_score": 0.75,
                    "source_class_breakdown": {"local": 1, "academic": 1},
                    "research_ms": 120,
                }
            ],
            "chapter_drafts": [
                {
                    "chapter_index": 1,
                    "title": "多元函数变化图景",
                    "draft_ms": 80,
                    "word_count": 320,
                    "placeholder_count": 1,
                    "interactive_block_count": 1,
                    "coverage_score": 0.8,
                    "quality_score": 0.86,
                    "repair_applied": True,
                    "teaching_action": "chapter_write",
                }
            ],
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "多元函数变化图景",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                }
            ],
            "mermaid_block_count": 1,
            "image_block_count": 1,
            "asset_count": 3,
            "asset_summary": {"mermaid": 1, "image": 1, "interactive_html": 1, "animation": 0},
            "merged_markdown": "# 文档\n\n一些内容",
            "exam_questions": [{"question_index": 1}],
            "practice_count": 4,
            "doc_ids": [101],
        },
        token_summary=DigestTokenSummary(),
    )

    assert summary["local_hit_count"] == 2
    assert summary["web_hit_count"] == 1
    assert summary["fallback_chapter_count"] == 1
    assert summary["curated_source_count"] == 2
    assert summary["trusted_source_count"] == 1
    assert summary["course_type"] == "systematic"
    assert summary["retrieval_profiles"] == ["docgen_systematic"]
    assert summary["teaching_actions"] == ["chapter_research", "chapter_write"]
    assert summary["retriever_names"] == ["bing", "local_rag"]
    assert summary["placeholder_count"] == 1
    assert summary["requested_profiles"] == ["docgen_systematic"]
    assert summary["applied_profiles"] == ["docgen_systematic"]
    assert summary["research_round_count_total"] == 2
    assert summary["gaps_remaining"] == ["边界条件"]
    assert summary["source_class_breakdown"] == {"academic": 1, "local": 1}
    assert summary["mermaid_count"] == 1
    assert summary["image_count"] == 1
    assert summary["asset_count"] == 3
    assert summary["asset_summary"] == {"mermaid": 1, "image": 1, "interactive_html": 1, "animation": 0}
    assert summary["interactive_block_count"] == 1
    assert summary["practice_count"] == 4
    assert summary["coverage_score"] == 0.775
    assert summary["quality_score"] == 0.86
    assert summary["quality_summary"]["repaired_chapter_count"] == 1
    assert summary["quality_summary"]["asset_count"] == 3
    assert "cleanse_ms" not in summary
    assert "outline_ms" not in summary
    assert "review_ms" not in summary
    assert "metadata_ms" not in summary


def test_confirmed_plan_contract_builds_execution_ready_chapter_contracts() -> None:
    contract = parse_digest_confirmed_plan_contract(
        {
            "subject": "高等数学",
            "user_goal": "系统整理偏导数",
            "digest_mode": "systematic",
            "chapter_plan": [
                {
                    "chapter_index": 1,
                    "title": "第 1 章",
                    "objective": "建立偏导数的几何直觉，并连接到定义。",
                    "required_elements": ["几何直觉", "偏导数定义"],
                    "search_queries": ["偏导数 几何意义"],
                    "media_hints": {"mermaid": ["偏导数整体关系图"], "interactive": ["偏导数公式推导展开器"]},
                }
            ],
            "media_plan": {"enable_mermaid": True, "enable_interactive_html": True},
            "build_constraints": {"target_total_words": 12000, "min_coverage_score": 0.8},
        }
    )

    assignments = contract.to_chapter_assignments(default_source_file_ids=[1])
    execution_contract = assignments[0]["execution_contract"]

    assert execution_contract["target_word_count"] >= 1100
    assert execution_contract["min_word_count"] >= 750
    assert execution_contract["min_coverage_score"] == 0.8
    assert execution_contract["media_quota"]["mermaid"] >= 1
    assert execution_contract["media_quota"]["interactive_html"] >= 1
    assert execution_contract["practice_quota"]["reasoning"] >= 2
    assert "几何直觉" in execution_contract["coverage_requirements"]


def test_docgen_writer_prompt_uses_module_contract_instead_of_fixed_headings() -> None:
    messages = build_docgen_writer_messages(
        title="偏导数与梯度",
        objective="把偏导数与梯度的联系讲清楚。",
        tone="encouraging",
        digest_mode="systematic",
        required_elements=["偏导数定义", "梯度方向"],
        writing_instructions="不要写空话。",
        source_count=3,
        dense_context="偏导数和梯度都与变化率有关。",
        chapter_index=1,
        chapter_count=5,
    )

    prompt = messages[1]["content"]
    assert "标题文案可以自行命名" in prompt
    assert "必须显式出现这些二级标题" not in prompt


def test_heading_quality_analysis_flags_sparse_markdown_for_agent_repair() -> None:
    analysis = analyze_chapter_heading_quality(
        "# 偏导数\n\n这里只写了一小段正文。",
        digest_mode="systematic",
    )

    assert analysis["needs_agent_repair"] is True
    assert analysis["needs_scaffold_fallback"] is True
    assert "recap" in analysis["missing_modules"]


def test_heading_quality_analysis_recognizes_scaffolded_markdown() -> None:
    enriched = ensure_chapter_learning_scaffold(
        "# 偏导数与梯度\n\n先给一个非常短的开头。",
        title="偏导数与梯度",
        objective="建立偏导数与梯度之间的联系。",
        required_elements=["偏导数定义", "梯度方向"],
        digest_mode="systematic",
        source_count=1,
        chapter_index=1,
        chapter_count=5,
    )

    analysis = analyze_chapter_heading_quality(enriched, digest_mode="systematic")

    assert analysis["needs_scaffold_fallback"] is False
    assert analysis["h2_count"] >= 5


def test_planner_title_prompt_requires_agent_generated_chapter_titles() -> None:
    messages = build_planner_chapter_title_messages(
        subject="线性代数",
        user_goal="考前梳理线性代数重点",
        digest_mode="sprint",
        chapters=[
            {
                "chapter_index": 1,
                "title": "线性代数：核心概念与高频考点",
                "task_hint": "矩阵与线性变换的核心概念",
                "objective": "先把矩阵、向量与线性变换讲清楚。",
                "required_elements": ["矩阵", "向量", "线性变换"],
                "search_queries": ["线性代数 矩阵 向量 线性变换"],
            }
        ],
    )

    prompt = messages[1]["content"]
    assert "不要输出“第 N 章”" in prompt
    assert "各章节标题之间必须有区分度" in prompt


def test_builtin_skillpacks_are_discoverable() -> None:
    skill_names = {item["name"] for item in list_skills()}
    assert "find_resources" in skill_names
    assert "explain_with_analogy" in skill_names
    assert "review_mistakes" in skill_names


def test_skillpack_render_binds_parameters() -> None:
    rendered = render_skill("find_resources", topic="linear algebra", difficulty="intro")

    assert "# Skill: find_resources" in rendered
    assert "- topic: linear algebra" in rendered
    assert "- difficulty: intro" in rendered
    assert "linear algebra" in rendered


def test_skillpack_scope_defaults_and_tool_tags_are_exposed() -> None:
    rendered = render_prompt_scoped_skillpacks(
        ["find_resources", "explain_with_analogy"],
        prompt_scope="digest.docgen.writer",
        bindings={"topic": "偏导数", "concept": "偏导数"},
    )

    assert "explain_with_analogy" in rendered
    assert "find_resources" not in rendered
    assert collect_skillpack_defaults(["find_resources"], prompt_scope="digest.docgen.research") == {
        "difficulty": "入门"
    }
    assert collect_recommended_tool_tags(["find_resources"], prompt_scope="digest.docgen.research") == [
        "retrieval",
        "web_search",
        "knowledge_lookup",
    ]


def test_fallback_plan_preserves_selected_skillpacks() -> None:
    plan = build_fallback_plan(
        subject="高等数学",
        user_goal="系统整理偏导数",
        digest_mode="systematic",
        tone="encouraging",
        selected_skillpacks=["find_resources", "explain_with_analogy", "find_resources"],
        shared_inputs=_build_shared_inputs(),
    )

    assert plan.selected_skillpacks == ["find_resources", "explain_with_analogy"]


def test_teaching_tools_are_registered_as_agent_tools() -> None:
    tool_names = {item["name"] for item in list_agent_tools()}
    assert "solve_step_by_step" in tool_names
    assert "generate_similar_problems" in tool_names
    assert "explain_formula" in tool_names
    assert "compare_concepts" in tool_names
