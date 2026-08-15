import pytest

from app.workflows.digest.docgen.lib import title_lock as title_lock_module
from app.workflows.digest.docgen.lib.models import LockedChapterTitle
from app.workflows.digest.docgen.lib.asset_requests import build_asset_request_block
from app.workflows.digest.docgen.lib.title_lock import (
    _resolve_locked_title,
    lock_title_for_chapter,
)
from app.workflows.digest.docgen.lib.publish import _prepare_chapter_markdown, build_merged_markdown
from app.workflows.digest.docgen.nodes.sync_locked_titles import _locked_title


def test_title_lock_preserves_specific_titles_and_rejects_unusable_shapes() -> None:
    cases = [
        ("objective anchored", "洛必达法则的使用边界", "极限计算", "洛必达法则的使用边界", False),
        ("semantic title", "换元失败时先看条件", "极限计算", "换元失败时先看条件", False),
        ("specific expansion", "函数连续性与间断点判定", "连续性", "函数连续性与间断点判定", False),
        ("mechanical enumeration", "罗尔定理、拉格朗日中值定理与柯西中值定理", "中值定理", "中值定理", True),
        ("short confirmed title", "函数连续性与间断点判断", "连续", "函数连续性与间断点判断", False),
        ("numeric title", "2", "极限计算", "极限计算", True),
        ("placeholder title", "本章内容", "极限计算", "极限计算", True),
    ]

    for case_name, candidate, confirmed, expected, expects_warning in cases:
        resolved, warning = _resolve_locked_title(candidate, confirmed_title=confirmed)

        assert resolved == expected, case_name
        assert (warning is not None) is expects_warning, case_name


def test_sync_locked_title_selects_the_semantically_safe_source() -> None:
    cases = [
        (1, "函数、极限与常用运算", "函数与极限", "函数、极限与常用运算", "函数与极限", "confirmed_plan_title"),
        (5, "导数应", "导数应用", "导数应", "导数应用", "confirmed_plan_title"),
        (
            4,
            "导数的定义、几何意义与求导法则",
            "导数的定义、几何意义与求导法则",
            "导数基础",
            "导数基础",
            "locked_compact_title",
        ),
    ]

    for chapter_index, draft_title, confirmed_title, enhanced_title, expected_title, expected_source in cases:
        title, source = _locked_title(
            chapter={
                "chapter_index": chapter_index,
                "title": draft_title,
                "resolved_title": draft_title,
            },
            chapter_index=chapter_index,
            locked_title={
                "chapter_index": chapter_index,
                "confirmed_title": confirmed_title,
                "enhanced_title": enhanced_title,
            },
        )

        assert (title, source) == (expected_title, expected_source), draft_title


def test_publish_markdown_uses_locked_title_and_demotes_extra_h1() -> None:
    markdown = _prepare_chapter_markdown(
        "# 导数应\n\n导数应用的核心是用导数分析函数。\n\n# 保存用户姓名\n\nname = \"小明\"",
        title="导数应用",
    )

    assert markdown.splitlines()[0] == "# 导数应用"
    assert "\n# 保存用户姓名" not in markdown
    assert "\n## 保存用户姓名" in markdown


def test_publish_markdown_strips_internal_asset_requests() -> None:
    raw = (
        "# 函数图像\n\n"
        "正文。\n\n"
        f"{build_asset_request_block('mermaid', '画出函数图像与解析式的关系')}\n"
    )

    markdown = _prepare_chapter_markdown(raw, title="函数图像")

    assert "ATM_DOCGEN_ASSET_REQUEST" not in markdown
    assert "atm-docgen-internal-asset-request" not in markdown
    assert "正文。" in markdown


def test_merged_markdown_keeps_application_title_suffix() -> None:
    markdown = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "读图解题与实际应用",
                "resolved_title": "读图解题与实际应用",
                "markdown": "# 读图解题与实际应用\n\n用图像读懂实际问题。",
            }
        ],
    )

    assert markdown.splitlines()[0] == "# 读图解题与实际应用"


def test_merged_markdown_replaces_placeholder_h1_with_numeric_fallback_titles() -> None:
    markdown = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "本章内容",
                "markdown": "# 本章内容\n\n第一章正文。",
            },
            {
                "chapter_index": 2,
                "title": "本章内容",
                "markdown": "# 本章内容\n\n第二章正文。",
            },
        ],
    )

    root_headings = [line for line in markdown.splitlines() if line.startswith("# ")]

    assert root_headings == ["# 第 1 章", "# 第 2 章"]
    assert markdown.count("# 本章内容") == 0


@pytest.mark.anyio
async def test_lock_title_for_chapter_falls_back_when_llm_call_fails(monkeypatch) -> None:
    async def fake_completion(*_args, **_kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(title_lock_module, "acompletion_with_fallback", fake_completion)

    locked = await lock_title_for_chapter(
        course_name="高等数学",
        digest_mode="sprint",
        user_prompt="期末速查",
        plan="围绕极限计算题型组织复习文档。",
        chapter={
            "chapter_index": 2,
            "title": "极限计算",
            "objective": "掌握 0/0 型、等价无穷小替换、洛必达法则的选择顺序。",
            "required_elements": ["0/0 型", "等价无穷小", "洛必达法则"],
        },
    )

    assert locked.chapter_index == 2
    assert locked.enhanced_title == "极限计算"
    assert locked.fallback_used is True
    assert locked.plan_mismatch_warnings

@pytest.mark.anyio
async def test_lock_title_for_chapter_falls_back_when_llm_title_is_placeholder(monkeypatch) -> None:
    async def fake_completion(*_args, **_kwargs):
        return LockedChapterTitle(
            chapter_index=2,
            confirmed_title="极限计算",
            enhanced_title="本章内容",
        )

    monkeypatch.setattr(title_lock_module, "acompletion_with_fallback", fake_completion)

    locked = await lock_title_for_chapter(
        course_name="高等数学",
        digest_mode="sprint",
        user_prompt="期末速查",
        plan="围绕极限计算题型组织复习文档。",
        chapter={
            "chapter_index": 2,
            "title": "极限计算",
            "objective": "掌握 0/0 型、等价无穷小替换、洛必达法则的选择顺序。",
            "required_elements": ["0/0 型", "等价无穷小", "洛必达法则"],
        },
    )

    assert locked.chapter_index == 2
    assert locked.enhanced_title == "极限计算"
    assert locked.fallback_used is True
    assert locked.plan_mismatch_warnings


@pytest.mark.anyio
async def test_lock_title_for_chapter_falls_back_when_llm_schema_is_invalid(monkeypatch) -> None:
    async def fake_completion(*_args, **_kwargs):
        return {"chapter_index": "not-an-int", "enhanced_title": "极限计算"}

    monkeypatch.setattr(title_lock_module, "acompletion_with_fallback", fake_completion)

    locked = await lock_title_for_chapter(
        course_name="高等数学",
        digest_mode="sprint",
        user_prompt="期末速查",
        plan="围绕极限计算题型组织复习文档。",
        chapter={
            "chapter_index": 2,
            "title": "极限计算",
            "objective": "掌握 0/0 型、等价无穷小替换、洛必达法则的选择顺序。",
            "required_elements": ["0/0 型", "等价无穷小", "洛必达法则"],
        },
    )

    assert locked.chapter_index == 2
    assert locked.enhanced_title == "极限计算"
    assert locked.fallback_used is True
    assert locked.plan_mismatch_warnings
