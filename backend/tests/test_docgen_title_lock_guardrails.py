import pytest

from app.workflows.digest.docgen.lib.title_lock import DocGenTitleLockError, _resolve_locked_title
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


def test_title_lock_rejects_placeholder_title_shape() -> None:
    with pytest.raises(DocGenTitleLockError):
        _resolve_locked_title(
            "2",
            confirmed_title="极限计算",
        )


def test_title_lock_prompt_discourages_repeated_abstract_sprint_titles() -> None:
    messages = build_title_lock_messages(
        course_name="高等数学",
        digest_mode="sprint",
        user_prompt="期末速查",
        plan_summary="围绕极限计算题型组织快速复习文档。",
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
