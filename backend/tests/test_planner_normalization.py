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
                normalized_content="\u6781\u9650\u3001\u8fde\u7eed\u3001\u5bfc\u6570\u3001\u5fae\u5206\u4e0e\u5178\u578b\u9898\u578b",
                char_count=200,
                has_formulas=True,
                has_tables=False,
                has_images=False,
            )
        ],
        fast_hints=FastTopicHints(
            chapter_candidates=["\u6781\u9650", "\u8fde\u7eed", "\u5bfc\u6570", "\u5fae\u5206"]
        ),
        subject_profile=SubjectProfile(
            subject_name="\u9ad8\u7b49\u6570\u5b66",
            discipline="\u6570\u5b66",
            sub_discipline="\u5fae\u79ef\u5206",
            key_topics=["\u6781\u9650", "\u8fde\u7eed", "\u5bfc\u6570", "\u5fae\u5206"],
            has_heavy_formulas=True,
        ),
    )


def test_normalize_planner_draft_repairs_sprint_contract() -> None:
    normalized = normalize_planner_draft(
        {
            "subject": "\u9ad8\u7b49\u6570\u5b66",
            "user_goal": "\u8003\u524d\u51b2\u523a",
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
        subject="\u9ad8\u7b49\u6570\u5b66",
        user_goal="\u8003\u524d\u51b2\u523a",
        requested_digest_mode="sprint",
        requested_tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )

    assert normalized.digest_mode == "sprint"
    assert len(normalized.chapter_plan) == 4
    assert normalized.chapter_plan[0].title.startswith("\u6781\u9650")
    assert normalized.chapter_plan[1].title.startswith("\u8fde\u7eed")
    assert normalized.chapter_plan[2].title.startswith("\u5bfc\u6570")
    assert normalized.chapter_plan[3].title.startswith("\u5fae\u5206")
    assert normalized.build_constraints["target_chapter_count"] == len(normalized.chapter_plan)
    assert "fixed_chapter_count" not in normalized.build_constraints
    assert "\u5feb\u901f" in normalized.chapter_plan[0].objective
    assert "\u51b2\u523a\u578b\u77e5\u8bc6\u6587\u6863" in normalized.plan_summary


def test_normalize_planner_draft_repairs_systematic_contract_from_previous_plan() -> None:
    previous_plan = {
        "subject": "\u9ad8\u7b49\u6570\u5b66",
        "user_goal": "\u7cfb\u7edf\u5b66\u4e60\u5bfc\u6570",
        "digest_mode": "systematic",
        "tone": "professional",
        "chapter_plan": [
            {
                "chapter_index": 1,
                "title": "\u5168\u666f\u5bfc\u8bba",
                "objective": "\u5efa\u7acb\u6574\u4f53\u5730\u56fe",
                "required_elements": ["\u77e5\u8bc6\u5168\u666f"],
                "search_queries": ["\u9ad8\u7b49\u6570\u5b66 \u5bfc\u6570 \u77e5\u8bc6\u6846\u67b6"],
                "writing_instructions": "\u5148\u8bb2\u6574\u4f53\u7ed3\u6784",
                "media_hints": {"images": [], "mermaid": ["\u5bfc\u6570\u5168\u666f\u56fe"], "interactive": []},
            },
            {
                "chapter_index": 2,
                "title": "\u6781\u9650\uff1a\u6838\u5fc3\u5b9a\u4e49\u4e0e\u65b9\u6cd5",
                "objective": "\u7406\u89e3\u6781\u9650\u5b9a\u4e49",
                "required_elements": ["\u524d\u7f6e\u77e5\u8bc6"],
                "search_queries": ["\u9ad8\u7b49\u6570\u5b66 \u6781\u9650 \u5b9a\u4e49"],
                "writing_instructions": "\u6309\u6559\u5b66\u7ed3\u6784\u5c55\u5f00",
                "media_hints": {"images": [], "mermaid": [], "interactive": []},
            },
            {
                "chapter_index": 3,
                "title": "\u8fde\u7eed\uff1a\u6838\u5fc3\u5b9a\u4e49\u4e0e\u65b9\u6cd5",
                "objective": "\u7406\u89e3\u8fde\u7eed\u6761\u4ef6",
                "required_elements": ["\u6838\u5fc3\u5b9a\u4e49"],
                "search_queries": ["\u9ad8\u7b49\u6570\u5b66 \u8fde\u7eed \u5b9a\u4e49"],
                "writing_instructions": "\u6309\u6559\u5b66\u7ed3\u6784\u5c55\u5f00",
                "media_hints": {"images": [], "mermaid": [], "interactive": []},
            },
            {
                "chapter_index": 4,
                "title": "\u5bfc\u6570\uff1a\u6838\u5fc3\u5b9a\u4e49\u4e0e\u65b9\u6cd5",
                "objective": "\u7406\u89e3\u5bfc\u6570\u5b9a\u4e49",
                "required_elements": ["\u63a8\u7406\u6216\u8bc1\u660e"],
                "search_queries": ["\u9ad8\u7b49\u6570\u5b66 \u5bfc\u6570 \u5b9a\u4e49"],
                "writing_instructions": "\u6309\u6559\u5b66\u7ed3\u6784\u5c55\u5f00",
                "media_hints": {"images": [], "mermaid": [], "interactive": []},
            },
            {
                "chapter_index": 5,
                "title": "\u5fae\u5206\uff1a\u6838\u5fc3\u5b9a\u4e49\u4e0e\u65b9\u6cd5",
                "objective": "\u7406\u89e3\u5fae\u5206\u5e94\u7528",
                "required_elements": ["\u5e94\u7528\u793a\u4f8b"],
                "search_queries": ["\u9ad8\u7b49\u6570\u5b66 \u5fae\u5206 \u5e94\u7528"],
                "writing_instructions": "\u6309\u6559\u5b66\u7ed3\u6784\u5c55\u5f00",
                "media_hints": {"images": [], "mermaid": [], "interactive": []},
            },
            {
                "chapter_index": 6,
                "title": "\u603b\u7ed3\u4e0e\u5ef6\u5c55",
                "objective": "\u56de\u6536\u5168\u6587\u4e3b\u7ebf",
                "required_elements": ["\u8fdb\u9636\u8def\u5f84"],
                "search_queries": ["\u9ad8\u7b49\u6570\u5b66 \u5bfc\u6570 \u603b\u7ed3"],
                "writing_instructions": "\u56de\u987e\u5168\u6587\u5e76\u7ed9\u51fa\u5ef6\u5c55",
                "media_hints": {"images": [], "mermaid": ["\u5bfc\u6570\u56de\u987e\u56fe"], "interactive": []},
            },
        ],
        "research_queries": ["\u9ad8\u7b49\u6570\u5b66 \u5bfc\u6570 \u77e5\u8bc6\u6846\u67b6", "\u9ad8\u7b49\u6570\u5b66 \u5bfc\u6570 \u603b\u7ed3"],
        "media_plan": {"enable_mermaid": True, "enable_images": False, "enable_interactive_html": False},
        "build_constraints": {"min_chapters": 6, "max_chapters": 10, "include_exercises": True, "include_sources": True},
        "plan_summary": "\u7cfb\u7edf\u5316\u6784\u5efa\u5bfc\u6570\u77e5\u8bc6\u6587\u6863\uff0c\u5148\u642d\u77e5\u8bc6\u5730\u56fe\uff0c\u518d\u9010\u5c42\u5c55\u5f00\u3002",
    }

    normalized = normalize_planner_draft(
        {
            "subject": "\u9ad8\u7b49\u6570\u5b66",
            "user_goal": "\u7cfb\u7edf\u5b66\u4e60\u5bfc\u6570",
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
        subject="\u9ad8\u7b49\u6570\u5b66",
        user_goal="\u7cfb\u7edf\u5b66\u4e60\u5bfc\u6570",
        requested_digest_mode="systematic",
        requested_tone="professional",
        shared_inputs=_build_shared_inputs(),
        latest_plan=previous_plan,
    )

    assert normalized.digest_mode == "systematic"
    assert len(normalized.chapter_plan) == 6
    assert normalized.chapter_plan[0].title == "\u5168\u666f\u5bfc\u8bba"
    assert normalized.chapter_plan[-1].title == "\u603b\u7ed3\u4e0e\u5ef6\u5c55"
    assert normalized.chapter_plan[1].title.startswith("\u6781\u9650\uff1a")
    assert normalized.build_constraints["min_chapters"] == 5
    assert normalized.build_constraints["max_chapters"] == 12
    assert normalized.build_constraints["target_chapter_count"] == len(normalized.chapter_plan)
    assert "\u7cfb\u7edf\u578b\u77e5\u8bc6\u6587\u6863" in normalized.plan_summary
    assert "\u9ad8\u7b49\u6570\u5b66 \u5bfc\u6570 \u603b\u7ed3" in normalized.research_queries


def test_normalize_planner_draft_replaces_subject_slug_in_user_visible_fields() -> None:
    normalized = normalize_planner_draft(
        {
            "subject": "subj_math",
            "user_goal": "\u5b66\u4e60\u5bfc\u6570",
            "digest_mode": "systematic",
            "tone": "encouraging",
            "chapter_plan": [
                {
                    "chapter_index": 1,
                    "title": "subj_math \u5168\u666f",
                    "objective": "subj_math \u57fa\u672c\u7ed3\u6784\u68b3\u7406",
                    "required_elements": [],
                    "search_queries": ["subj_math \u5168\u666f"],
                    "writing_instructions": "subj_math \u524d\u7f6e\u77e5\u8bc6\u68b3\u7406",
                    "media_hints": {},
                }
            ],
            "research_queries": ["subj_math \u5bfc\u6570 \u603b\u7ed3"],
            "media_plan": {},
            "build_constraints": {},
            "plan_summary": "subj_math \u7cfb\u7edf\u5b66\u4e60\u89c4\u5212",
        },
        subject="subj_math",
        user_goal="\u5b66\u4e60\u5bfc\u6570",
        requested_digest_mode="systematic",
        requested_tone="encouraging",
        shared_inputs=_build_shared_inputs(),
    )

    assert "subj_" not in normalized.plan_summary
    assert all("subj_" not in chapter.title for chapter in normalized.chapter_plan)
    assert all("subj_" not in chapter.objective for chapter in normalized.chapter_plan)
    assert all("subj_" not in query for query in normalized.research_queries)
