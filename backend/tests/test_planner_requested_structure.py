from __future__ import annotations

from app.workflows.digest.planner.lib.requested_structure import (
    extract_explicit_chapter_titles,
    extract_explicit_learning_topic,
    extract_requested_chapter_count,
)


def test_extract_inline_chapter_list_from_user_requested_structure() -> None:
    prompt = "我想系统复习初中数学，14天学完，按数与式、方程与不等式、函数、几何、统计与概率分成5个章节。"

    assert extract_explicit_learning_topic(prompt) == "初中数学"
    assert extract_requested_chapter_count(prompt) == 5
    assert extract_explicit_chapter_titles(prompt) == [
        "数与式",
        "方程与不等式",
        "函数",
        "几何",
        "统计与概率",
    ]
