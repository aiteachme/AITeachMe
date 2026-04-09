from __future__ import annotations

from app.shared.infra.skills import list_skills
from app.teaching.documents import ensure_chapter_learning_scaffold
from app.workflows.digest.observability import DigestTokenSummary, build_docgen_lane_summary
from app.workflows.digest.planner.models import build_fallback_plan
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


def test_sprint_fallback_plan_uses_dynamic_topic_structure() -> None:
    plan = build_fallback_plan(
        subject="高等数学",
        user_goal="考前冲刺偏导数",
        digest_mode="sprint",
        tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )

    assert plan.digest_mode == "sprint"
    assert 3 <= len(plan.chapter_plan) <= 6
    assert plan.chapter_plan[0].title.startswith("偏导数")
    assert plan.chapter_plan[1].title.startswith("梯度")
    assert plan.chapter_plan[2].title.startswith("方向导数")
    assert plan.build_constraints["target_chapter_count"] == len(plan.chapter_plan)
    assert "fixed_chapter_count" not in plan.build_constraints
    assert "冲刺型知识文档" in plan.plan_summary


def test_systematic_fallback_plan_uses_dynamic_topic_structure() -> None:
    plan = build_fallback_plan(
        subject="高等数学",
        user_goal="系统学习偏导数",
        digest_mode="systematic",
        tone="professional",
        shared_inputs=_build_shared_inputs(),
    )

    assert plan.digest_mode == "systematic"
    assert 5 <= len(plan.chapter_plan) <= 12
    assert plan.chapter_plan[0].title.startswith("偏导数")
    assert plan.chapter_plan[1].title.startswith("梯度")
    assert plan.chapter_plan[2].title.startswith("方向导数")
    assert plan.build_constraints["min_chapters"] == 5
    assert plan.build_constraints["max_chapters"] == 12


def test_learning_scaffold_enforces_sprint_sections() -> None:
    markdown = "# 概念破冰\n\n这里先给一段简单内容。"
    enriched = ensure_chapter_learning_scaffold(
        markdown,
        title="概念破冰",
        objective="快速建立偏导数的直觉。",
        required_elements=["核心概念", "直观类比", "易错点"],
        digest_mode="sprint",
        source_count=2,
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
    markdown = "# 全景导论\n\n本章先从整体结构讲起。"
    enriched = ensure_chapter_learning_scaffold(
        markdown,
        title="全景导论",
        objective="建立整体知识地图。",
        required_elements=["知识全景", "学习路径", "概念关系"],
        digest_mode="systematic",
        source_count=3,
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
            "chapter_materials": [
                {
                    "chapter_index": 1,
                    "title": "全景导论",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                    "local_hits": 2,
                    "web_hits": 1,
                    "fallback_used": True,
                    "curated_source_count": 2,
                    "trusted_source_count": 1,
                    "retriever_stats": {"local_rag": {"query_count": 1}, "bing": {"query_count": 1}},
                    "research_ms": 120,
                }
            ],
            "chapter_drafts": [
                {
                    "chapter_index": 1,
                    "title": "全景导论",
                    "draft_ms": 80,
                    "word_count": 320,
                    "placeholder_count": 1,
                }
            ],
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "全景导论",
                    "sources": ["local://chunk/1", "https://example.edu/math"],
                }
            ],
            "merged_markdown": "# 文档\n\n一些内容",
            "exam_questions": [{"question_index": 1}],
            "doc_ids": [101],
        },
        token_summary=DigestTokenSummary(),
    )

    assert summary["local_hit_count"] == 2
    assert summary["web_hit_count"] == 1
    assert summary["fallback_chapter_count"] == 1
    assert summary["curated_source_count"] == 2
    assert summary["trusted_source_count"] == 1
    assert summary["retriever_names"] == ["bing", "local_rag"]
    assert summary["placeholder_count"] == 1
    assert "cleanse_ms" not in summary
    assert "outline_ms" not in summary
    assert "review_ms" not in summary
    assert "metadata_ms" not in summary


def test_teaching_skills_are_registered() -> None:
    skill_names = {item["name"] for item in list_skills()}
    assert "solve_step_by_step" in skill_names
    assert "generate_similar_problems" in skill_names
    assert "explain_formula" in skill_names
    assert "compare_concepts" in skill_names
