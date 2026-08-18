from __future__ import annotations

import pytest

from app.workflows.digest.planner.lib.requested_structure import (
    extract_explicit_chapter_titles,
    extract_explicit_course_title,
    extract_explicit_learning_topic,
    extract_requested_chapter_constraint,
    extract_requested_chapter_count,
    requests_preserved_chapter_structure,
    requests_preserved_knowledge_boundaries,
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


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "请生成 3-5 章课程。用户最新调整：请严格调整为 6 章。",
            (6, None),
        ),
        (
            "请生成 3-5 章课程。用户最新调整：请调整为 7-9 章。",
            (None, (7, 9)),
        ),
        (
            "请生成 6 章课程。用户最新调整：请调整为 3-5 章。",
            (None, (3, 5)),
        ),
        (
            "请把原来的 3-5 章方案改为严格 6 章。",
            (6, None),
        ),
        (
            "请生成 6 章课程。用户最新调整：第 1 章集合，第 2 章函数，第 3 章导数。",
            (3, None),
        ),
        (
            "请生成 5-7 章课程。用户最新调整：第 1 章集合，第 2 章函数，第 3 章导数。",
            (3, None),
        ),
    ],
)
def test_latest_chapter_constraint_overrides_earlier_count_or_range(
    prompt: str,
    expected: tuple[int | None, tuple[int, int] | None],
) -> None:
    assert extract_requested_chapter_constraint(prompt) == expected


def test_chapter_range_is_not_mistaken_for_its_upper_bound() -> None:
    assert extract_requested_chapter_constraint("请生成 3-5 章课程。") == (None, (3, 5))
    assert extract_requested_chapter_count("请生成 3-5 章课程。") is None


def test_latest_complete_chapter_title_list_overrides_an_earlier_list() -> None:
    prompt = (
        "第 1 章旧集合，第 2 章旧函数，第 3 章旧导数。"
        "用户最新调整：第 1 章矩阵，第 2 章行列式。"
    )

    assert extract_explicit_chapter_titles(prompt) == ["矩阵", "行列式"]
    assert extract_requested_chapter_constraint(prompt) == (2, None)


def test_partial_chapter_title_revision_does_not_change_total_count() -> None:
    prompt = "请生成 3 章课程。用户最新调整：第 2 章必须增加行列式的几何意义。"

    assert extract_requested_chapter_constraint(prompt) == (3, None)


@pytest.mark.parametrize(
    ("feedback", "expected"),
    [
        ("保持章节结构，只调整例题。", True),
        ("不要调整章节结构，只增加练习。", True),
        ("不要再调整章节结构。", True),
        ("不得修改章节结构。", True),
        ("禁止改变大纲结构。", True),
        ("不能修改章节结构。", True),
        ("章节结构不要修改。", True),
        ("不需要保持章节结构，请重新拆分。", False),
        ("不必再保持章节结构，请重新规划。", False),
        ("不能保持章节结构，请重新拆分。", False),
        ("无法维持章节结构，请重新规划。", False),
        ("不要保留大纲结构，全部重做。", False),
        ("请重新拆分章节结构。", False),
    ],
)
def test_chapter_structure_preservation_respects_negation(feedback: str, expected: bool) -> None:
    assert requests_preserved_chapter_structure(feedback) is expected


@pytest.mark.parametrize(
    ("feedback", "expected"),
    [
        ("保留知识点边界，只调整讲解顺序。", True),
        ("不要修改知识点范围。", True),
        ("不要继续修改知识点范围。", True),
        ("不得增删知识点。", True),
        ("禁止改变知识边界。", True),
        ("勿再修改知识范围。", True),
        ("知识边界保持不变。", True),
        ("不保留知识边界，请重新规划。", False),
        ("禁止保留知识边界，请重新规划。", False),
        ("无需维持知识点范围。", False),
        ("请扩展知识点范围。", False),
    ],
)
def test_knowledge_boundary_preservation_respects_negation(feedback: str, expected: bool) -> None:
    assert requests_preserved_knowledge_boundaries(feedback) is expected
