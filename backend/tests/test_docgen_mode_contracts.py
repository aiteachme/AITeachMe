from __future__ import annotations

from app.shared.infra.skills import (
    collect_recommended_tool_tags,
    collect_skillpack_defaults,
    list_skills,
    render_prompt_scoped_skillpacks,
    render_skill,
)
from app.shared.infra.tools import list_agent_tools
from app.teaching.documents import ensure_chapter_learning_scaffold
from app.workflows.digest.observability import DigestTokenSummary, build_docgen_lane_summary
from app.workflows.digest.planner.models import build_fallback_plan
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


def test_fallback_plan_uses_neutral_provisional_titles() -> None:
    plan = build_fallback_plan(
        subject="高等数学",
        user_goal="考前冲刺偏导数",
        digest_mode="sprint",
        tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )

    assert plan.digest_mode == "sprint"
    assert 3 <= len(plan.chapter_plan) <= 6
    assert [chapter.title for chapter in plan.chapter_plan[:3]] == ["第 1 章", "第 2 章", "第 3 章"]
    assert plan.build_constraints["target_chapter_count"] == len(plan.chapter_plan)
    assert "fixed_chapter_count" not in plan.build_constraints
    assert "冲刺型知识文档" in plan.plan_summary


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

    for heading in (
        "## 本章导读",
        "## 术语速览",
        "## 学习目标对照",
        "## 核心抓手",
        "## 题型拆解",
        "## 本章速记卡",
        "## 易错提醒",
        "## 快速回顾",
    ):
        assert heading in enriched


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

    for heading in (
        "## 本章导读",
        "## 术语速览",
        "## 学习目标对照",
        "## 前置知识",
        "## 动机引入",
        "## 核心定义与定理",
        "## 推理与应用",
        "## 本章要点",
    ):
        assert heading in enriched
    assert "## 全局脉络图" in enriched
    assert "<!-- [MERMAID:" in enriched


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

    assert enriched_twice.count("## 术语速览") == 1
    assert enriched_twice.count("## 学习目标对照") == 1


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
