from __future__ import annotations

from app.workflows.digest.planner.models import normalize_planner_draft
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SourcePacket, SubjectProfile


def _build_shared_inputs() -> SharedInputs:
    return SharedInputs(
        source_packets=[
            SourcePacket(
                file_id=1,
                filename="math.md",
                filetype="markdown",
                markdown_path="math.md",
                asset_dir="assets",
                normalized_content="极限、连续、导数、微分与典型题型。",
                char_count=200,
                has_formulas=True,
                has_tables=False,
                has_images=False,
            )
        ],
        fast_hints=FastTopicHints(chapter_candidates=["极限", "连续", "导数", "微分"]),
        subject_profile=SubjectProfile(
            subject_name="高等数学",
            discipline="数学",
            sub_discipline="微积分",
            key_topics=["极限", "连续", "导数", "微分"],
            has_heavy_formulas=True,
        ),
    )


def test_normalize_planner_draft_repairs_sprint_contract() -> None:
    normalized = normalize_planner_draft(
        {
            "subject": "高等数学",
            "user_goal": "考前冲刺",
            "digest_mode": "sprint",
            "tone": "encouraging",
            "chapter_plan": [
                {
                    "chapter_index": 7,
                    "title": "Chapter 1",
                    "objective": "Explain basics",
                    "required_elements": ["clear explanation"],
                    "search_queries": [],
                    "writing_instructions": "Explain clearly",
                    "media_hints": {},
                }
            ],
            "research_queries": [],
            "media_plan": {},
            "build_constraints": {},
            "plan_summary": "English summary only",
        },
        subject="高等数学",
        user_goal="考前冲刺",
        requested_digest_mode="sprint",
        requested_tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )

    assert normalized.digest_mode == "sprint"
    assert len(normalized.chapter_plan) == 4
    assert normalized.chapter_plan[0].title.startswith("极限：")
    assert normalized.chapter_plan[1].title.startswith("连续：")
    assert normalized.chapter_plan[2].title.startswith("导数：")
    assert normalized.chapter_plan[3].title.startswith("微分：")
    assert normalized.build_constraints["fixed_chapter_count"] == 4
    assert "快速建立" in normalized.chapter_plan[0].objective
    assert "冲刺型知识文档" in normalized.plan_summary


def test_normalize_planner_draft_repairs_systematic_contract_from_previous_plan() -> None:
    previous_plan = {
        "subject": "高等数学",
        "user_goal": "系统学习导数",
        "digest_mode": "systematic",
        "tone": "professional",
        "chapter_plan": [
            {"chapter_index": 1, "title": "全景导论", "objective": "建立整体地图", "required_elements": ["知识全景"], "search_queries": ["高等数学 导数 知识框架"], "writing_instructions": "先讲整体结构。", "media_hints": {"images": [], "mermaid": ["导数全景图"], "interactive": []}},
            {"chapter_index": 2, "title": "极限：核心定义与方法", "objective": "理解极限定义", "required_elements": ["前置知识"], "search_queries": ["高等数学 极限 定义"], "writing_instructions": "按教学结构展开。", "media_hints": {"images": [], "mermaid": [], "interactive": []}},
            {"chapter_index": 3, "title": "连续：核心定义与方法", "objective": "理解连续条件", "required_elements": ["核心定义"], "search_queries": ["高等数学 连续 定义"], "writing_instructions": "按教学结构展开。", "media_hints": {"images": [], "mermaid": [], "interactive": []}},
            {"chapter_index": 4, "title": "导数：核心定义与方法", "objective": "理解导数定义", "required_elements": ["推理或证明"], "search_queries": ["高等数学 导数 定义"], "writing_instructions": "按教学结构展开。", "media_hints": {"images": [], "mermaid": [], "interactive": []}},
            {"chapter_index": 5, "title": "微分：核心定义与方法", "objective": "理解微分应用", "required_elements": ["应用示例"], "search_queries": ["高等数学 微分 应用"], "writing_instructions": "按教学结构展开。", "media_hints": {"images": [], "mermaid": [], "interactive": []}},
            {"chapter_index": 6, "title": "总结与延展", "objective": "回收全文主线", "required_elements": ["进阶路径"], "search_queries": ["高等数学 导数 总结"], "writing_instructions": "回顾全文并给出延展。", "media_hints": {"images": [], "mermaid": ["导数回顾图"], "interactive": []}},
        ],
        "research_queries": ["高等数学 导数 知识框架", "高等数学 导数 总结"],
        "media_plan": {"enable_mermaid": True, "enable_images": False, "enable_interactive_html": False},
        "build_constraints": {"min_chapters": 6, "max_chapters": 10, "include_exercises": True, "include_sources": True},
        "plan_summary": "系统化构建导数知识文档，先搭知识地图，再逐层展开。",
    }

    normalized = normalize_planner_draft(
        {
            "subject": "高等数学",
            "user_goal": "系统学习导数",
            "digest_mode": "systematic",
            "tone": "professional",
            "chapter_plan": [
                {"chapter_index": 1, "title": "Intro", "objective": "English intro"},
                {"chapter_index": 2, "title": "Definitions", "objective": "English middle"},
                {"chapter_index": 3, "title": "Ending", "objective": "English ending"},
            ],
            "research_queries": [],
            "media_plan": {},
            "build_constraints": {},
            "plan_summary": "bad summary",
        },
        subject="高等数学",
        user_goal="系统学习导数",
        requested_digest_mode="systematic",
        requested_tone="professional",
        shared_inputs=_build_shared_inputs(),
        latest_plan=previous_plan,
    )

    assert normalized.digest_mode == "systematic"
    assert len(normalized.chapter_plan) == 6
    assert normalized.chapter_plan[0].title == "全景导论"
    assert normalized.chapter_plan[-1].title == "总结与延展"
    assert normalized.chapter_plan[1].title == "极限：定义与方法"
    assert normalized.build_constraints["min_chapters"] == 6
    assert normalized.build_constraints["max_chapters"] == 10
    assert "系统型知识文档" in normalized.plan_summary
    assert "高等数学 导数 总结" in normalized.research_queries
