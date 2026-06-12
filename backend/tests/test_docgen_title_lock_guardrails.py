import pytest

from app.workflows.digest.docgen.lib import title_lock as title_lock_module
from app.workflows.digest.docgen.lib.models import LockedChapterTitle
from app.workflows.digest.docgen.lib.title_lock import (
    _resolve_locked_title,
    lock_title_for_chapter,
    prefer_confirmed_catalog_title,
)
from app.workflows.digest.docgen.lib.publish import _prepare_chapter_markdown
from app.workflows.digest.docgen.nodes.sync_locked_titles import _locked_title
from app.workflows.digest.docgen.prompts.title_lock import build_title_lock_messages


def test_title_lock_accepts_objective_anchored_specific_title() -> None:
    resolved, warning = _resolve_locked_title(
        "洛必达法则的使用边界",
        confirmed_title="极限计算",
    )

    assert resolved == "洛必达法则的使用边界"
    assert warning is None


def test_title_lock_does_not_keyword_match_semantic_titles() -> None:
    resolved, warning = _resolve_locked_title(
        "换元失败时先看条件",
        confirmed_title="极限计算",
    )

    assert resolved == "换元失败时先看条件"
    assert warning is None


def test_title_lock_keeps_informative_specific_expansion() -> None:
    assert not prefer_confirmed_catalog_title(
        confirmed_title="连续性",
        candidate_title="函数连续性与间断点判定",
    )

    resolved, warning = _resolve_locked_title(
        "函数连续性与间断点判定",
        confirmed_title="连续性",
    )

    assert resolved == "函数连续性与间断点判定"
    assert warning is None


def test_title_lock_prefers_catalog_title_for_mechanical_enumeration() -> None:
    resolved, warning = _resolve_locked_title(
        "罗尔定理、拉格朗日中值定理与柯西中值定理",
        confirmed_title="中值定理",
    )

    assert resolved == "中值定理"
    assert warning is not None


def test_title_lock_keeps_specific_title_over_too_short_confirmed_title() -> None:
    resolved, warning = _resolve_locked_title(
        "函数连续性与间断点判断",
        confirmed_title="连续",
    )

    assert resolved == "函数连续性与间断点判断"
    assert warning is None


def test_title_lock_falls_back_for_unusable_title_shape() -> None:
    resolved, warning = _resolve_locked_title(
        "2",
        confirmed_title="极限计算",
    )

    assert resolved == "极限计算"
    assert warning is not None


def test_title_lock_falls_back_for_generic_placeholder_title() -> None:
    resolved, warning = _resolve_locked_title(
        "本章内容",
        confirmed_title="极限计算",
    )

    assert resolved == "极限计算"
    assert warning is not None


def test_sync_locked_title_prefers_confirmed_catalog_title_over_long_draft_title() -> None:
    title, source = _locked_title(
        chapter={
            "chapter_index": 1,
            "title": "函数、极限与常用运算",
            "resolved_title": "函数、极限与常用运算",
        },
        chapter_index=1,
        locked_title={
            "chapter_index": 1,
            "confirmed_title": "函数与极限",
            "enhanced_title": "函数、极限与常用运算",
        },
    )

    assert title == "函数与极限"
    assert source == "confirmed_plan_title"


def test_sync_locked_title_never_shortens_confirmed_application_title() -> None:
    title, source = _locked_title(
        chapter={
            "chapter_index": 5,
            "title": "导数应",
            "resolved_title": "导数应",
        },
        chapter_index=5,
        locked_title={
            "chapter_index": 5,
            "confirmed_title": "导数应用",
            "enhanced_title": "导数应",
        },
    )

    assert title == "导数应用"
    assert source == "confirmed_plan_title"


def test_sync_locked_title_allows_compact_locked_title_for_enumerated_confirmed_title() -> None:
    title, source = _locked_title(
        chapter={
            "chapter_index": 4,
            "title": "导数的定义、几何意义与求导法则",
            "resolved_title": "导数的定义、几何意义与求导法则",
        },
        chapter_index=4,
        locked_title={
            "chapter_index": 4,
            "confirmed_title": "导数的定义、几何意义与求导法则",
            "enhanced_title": "导数基础",
        },
    )

    assert title == "导数基础"
    assert source == "locked_compact_title"


def test_publish_markdown_uses_locked_title_over_existing_h1() -> None:
    markdown = _prepare_chapter_markdown(
        "# 导数应\n\n导数应用的核心是用导数分析函数。",
        title="导数应用",
    )

    assert markdown.splitlines()[0] == "# 导数应用"


@pytest.mark.anyio
async def test_lock_title_for_chapter_falls_back_when_llm_call_fails(monkeypatch) -> None:
    async def fake_completion(*_args, **_kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(title_lock_module, "acompletion_with_fallback", fake_completion)

    locked = await lock_title_for_chapter(
        course_name="高等数学",
        digest_mode="sprint",
        user_prompt="期末速查",
        plan="围绕极限计算题型组织快速复习文档。",
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
        plan="围绕极限计算题型组织快速复习文档。",
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
        plan="围绕极限计算题型组织快速复习文档。",
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
