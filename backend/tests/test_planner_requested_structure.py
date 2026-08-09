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


def test_learning_plan_phrase_is_not_mistaken_for_course_topic() -> None:
    prompt = "跳过前置诊断。请严格生成三章学习方案，依次覆盖：C语言变量与数据类型、流程控制、指针与数组。不要扩展章节。"

    assert extract_explicit_learning_topic(prompt) == "C语言变量与数据类型"
    assert extract_requested_chapter_count(prompt) == 3


def test_ordinal_titles_ignore_negative_extra_chapter_constraint() -> None:
    prompt = (
        "请基于上传的 C 语言材料先做必要的前置诊断，随后生成严格三章的学习方案："
        "第一章变量与数据类型，第二章流程控制，第三章指针与数组。"
        "不得增加第四章，且每章要明确列出必须覆盖的知识要素。"
    )

    assert extract_explicit_chapter_titles(prompt) == [
        "变量与数据类型",
        "流程控制",
        "指针与数组",
    ]
    assert extract_explicit_learning_topic(prompt) == "C 语言"
    assert extract_requested_chapter_count(prompt) == 3
