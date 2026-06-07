import pytest

from app.workflows.digest.docgen.lib import title_lock as title_lock_module
from app.workflows.digest.docgen.lib.models import LockedChapterTitle
from app.workflows.digest.docgen.lib.title_lock import _resolve_locked_title, lock_title_for_chapter
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


def test_title_lock_prompt_discourages_repeated_abstract_sprint_titles() -> None:
    messages = build_title_lock_messages(
        course_name="高等数学",
        digest_mode="sprint",
        user_prompt="期末速查",
        plan="围绕极限计算题型组织快速复习文档。",
        chapter={
            "chapter_index": 1,
            "title": "极限计算",
            "objective": "掌握 0/0 型、等价无穷小替换、洛必达法则的选择顺序。",
            "required_elements": ["0/0 型", "等价无穷小", "洛必达法则"],
        },
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "不要" in prompt
    assert "标题" in prompt
    assert "速查" in prompt or "快速" in prompt
    assert "不是候选词表" in prompt
    assert "不能照抄" in prompt
    assert "如果本章领域与示例不同" in prompt
    assert "现金流表" in prompt
