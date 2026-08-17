from __future__ import annotations

from app.workflows.digest.planner.lib.requested_structure import (
    extract_explicit_chapter_titles,
    extract_explicit_course_title,
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


def test_extract_explicit_course_title_before_coverage_topics() -> None:
    prompt = "我想构建一门大学高数期末复习课，覆盖极限、导数、中值定理、不定积分、定积分和定积分应用。"

    assert extract_explicit_course_title(prompt) == "大学高数期末复习"
    assert extract_explicit_learning_topic(prompt) == "大学高数期末复习"


def test_learning_plan_phrase_is_not_mistaken_for_course_topic() -> None:
    prompt = "跳过前置诊断。请严格生成三章学习方案，依次覆盖：C语言变量与数据类型、流程控制、指针与数组。不要扩展章节。"

    assert extract_explicit_learning_topic(prompt) == ""
    assert extract_requested_chapter_count(prompt) == 3


def test_coverage_list_first_item_is_not_mistaken_for_whole_course() -> None:
    prompt = "请设计课程，覆盖人工智能原理、训练数据偏见、生成式 AI 局限和隐私保护。"

    assert extract_explicit_learning_topic(prompt) == ""


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


def test_repeated_ordinal_adjustment_does_not_inflate_requested_chapter_count() -> None:
    prompt = (
        "创建一门只有两章的线性代数微型课程：第一章讲矩阵乘法，第二章讲行列式。"
        "用户最新调整：正式生成两章方案，第二章必须讲清行列式的面积缩放与方向含义。"
    )

    assert extract_explicit_chapter_titles(prompt) == ["讲矩阵乘法", "讲行列式"]
    assert extract_requested_chapter_count(prompt) == 2


def test_latest_explicit_chapter_count_overrides_an_earlier_count() -> None:
    prompt = "先生成三章课程。用户最新调整：内容太散，请改为只有两章。"

    assert extract_requested_chapter_count(prompt) == 2
