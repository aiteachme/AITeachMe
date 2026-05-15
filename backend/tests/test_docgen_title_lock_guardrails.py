from app.workflows.digest.docgen.lib.title_lock import _resolve_locked_title
from app.workflows.digest.docgen.prompts.title_lock import build_title_lock_messages


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
    )

    assert resolved == "样品预处理流程"
    assert warning is None


def test_title_lock_does_not_keyword_match_semantic_titles() -> None:
    resolved, warning = _resolve_locked_title(
        "完全无关的新主题",
        confirmed_title="样品预处理流程",
    )

    assert resolved == "完全无关的新主题"
    assert warning is None


def test_title_lock_rejects_placeholder_title_shape() -> None:
    resolved, warning = _resolve_locked_title(
        "第 2 章",
        confirmed_title="样品预处理流程",
    )

    assert resolved == "样品预处理流程"
    assert warning is not None


def test_title_lock_prompt_discourages_repeated_abstract_sprint_titles() -> None:
    messages = build_title_lock_messages(
        course_name="极限、连续与常见极限题",
        digest_mode="sprint",
        user_prompt="期末速成",
        plan_summary="围绕极限计算题型组织。",
        chapter={
            "chapter_index": 1,
            "title": "建立极限的基本语言与常见题",
            "objective": "掌握 0/0 型、无穷比无穷型和等价无穷小替换。",
            "required_elements": ["0/0 型", "等价无穷小替换", "洛必达法则"],
        },
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "风格示例：洛必达法则、等价无穷小替换、分部积分、闭区间最值、矩阵分解" in prompt
    assert "这些只是长度和清晰度示例，不是候选词表" in prompt
    assert "不要从固定标签、关键词或示例里拼标题" in prompt
