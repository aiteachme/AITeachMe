from __future__ import annotations

import pytest

from app.workflows.digest.docgen.lib import repair


def test_explicit_h2_replacement_preserves_same_named_chapter_and_other_sections():
    original = (
        "# 整数减法\n\n章前导读保留。\n\n"
        "## 整数减法\n\n原公式。\n\n### 方法边界\n\n原小节说明。\n\n"
        "## 单元测试\n\n测试内容保留。\n"
    )
    patched = repair._insert_local_patch(
        original, "## 整数减法\n\n正确公式。", target_anchor="## 整数减法",
        chapter_title="整数减法", replace_section=True,
    )
    assert patched == (
        "# 整数减法\n\n章前导读保留。\n\n"
        "## 整数减法\n\n正确公式。\n\n"
        "## 单元测试\n\n测试内容保留。\n"
    )


@pytest.mark.parametrize("anchor,expected", [
    ("## 运算法则", "## 运算法则\n\n二级规则。\n\n### 运算法则\n\n三级细节。\n\n"),
    ("### 运算法则", "### 运算法则\n\n三级细节。\n\n"),
])
def test_explicit_anchor_selects_exact_level_when_titles_repeat(anchor, expected):
    markdown = "# 运算法则\n\n## 运算法则\n\n二级规则。\n\n### 运算法则\n\n三级细节。\n\n## 其它内容\n\n保留。\n"
    section = repair._find_heading_section(markdown, anchor=anchor, chapter_title="运算法则")
    assert section is not None
    assert markdown[section[0]:section[1]] == expected


@pytest.mark.parametrize("anchor", ["### 整数减法", "## 整数"])
def test_explicit_anchor_does_not_fall_back_to_another_level_or_partial_title(anchor):
    markdown = "# 整数减法\n\n## 整数减法\n\n已有讲解。\n"
    assert repair._find_heading_section(markdown, anchor=anchor, chapter_title="整数减法") is None


@pytest.mark.parametrize("anchor", ["整数减法", "减法"])
def test_plain_anchor_retains_legacy_section_matching(anchor):
    markdown = "# 整数运算\n\n## 整数减法\n\n已有讲解。\n\n## 单元测试\n\n保留。\n"
    section = repair._find_heading_section(markdown, anchor=anchor, chapter_title="整数运算")
    assert section is not None
    assert markdown[section[0]:section[1]] == "## 整数减法\n\n已有讲解。\n\n"


def test_plain_chapter_title_keeps_existing_whole_chapter_guard():
    markdown = "# 整数减法\n\n## 整数减法\n\n已有讲解。\n"
    assert repair._find_heading_section(markdown, anchor="整数减法", chapter_title="整数减法") is None
