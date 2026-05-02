from app.workflows.digest.docgen.lib.title_lock import _chapter_title_anchor_text
from app.workflows.digest.docgen.lib.title_lock import _resolve_locked_title


def test_title_lock_accepts_objective_anchored_specific_title() -> None:
    chapter = {
        "chapter_index": 2,
        "title": "本章内容",
        "objective": "掌握样品预处理流程的步骤和质量检查方法。",
        "required_elements": ["取样方式", "预处理流程", "质量检查"],
    }

    resolved, warning = _resolve_locked_title(
        "样品预处理流程",
        confirmed_title="本章内容",
        user_prompt="学习这门课的核心内容",
        plan_summary="",
        chapter_anchor_text=_chapter_title_anchor_text(chapter, fallback_title="本章内容"),
    )

    assert resolved == "样品预处理流程"
    assert warning is None


def test_title_lock_rejects_unanchored_new_topic() -> None:
    resolved, warning = _resolve_locked_title(
        "完全无关的新主题",
        confirmed_title="样品预处理流程",
        user_prompt="学习规范操作",
        plan_summary="取样方式、预处理流程、质量检查",
        chapter_anchor_text="取样方式 预处理流程 质量检查",
    )

    assert resolved == "样品预处理流程"
    assert warning is not None
