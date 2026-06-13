"""Prompt builder for planner course name and icon identity."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.support.courses.icons import COURSE_ICON_OPTIONS


def _identity_mode_note(digest_mode: str) -> str:
    return "紧凑节奏" if str(digest_mode or "").strip().lower() == "sprint" else "系统节奏"


def build_course_identity_messages(
    *,
    user_prompt: str,
    filenames: list[str],
    digest_mode: str,
    planning_note: str = "",
    material_note: str = "",
    topic_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build the structured identity prompt used when creating a new learning space."""

    normalized_topic_hints = [str(item).strip() for item in list(topic_hints or []) if str(item).strip()]
    mode_label = _identity_mode_note(digest_mode)
    options_text = ", ".join(COURSE_ICON_OPTIONS)
    system_prompt = """
你是 AITeachMe 的课程命名与图标选择器。输出合法 JSON。
""".strip()
    prompt = f"""
请根据用户学习目标、规划判断、资料线索和主题提示，生成课程展示身份。

字段要求：
- course_name：2 到 10 个汉字为佳，最多 16 个字符；像真实对话标题一样自然。
- course_name 直接命名学习对象、知识范围、能力卡点或任务目标，适合显示在课程列表。
- course_name 读起来应像用户自己会给课程起的短标题，保留必要的学科与目标信息。
- course_icon：只能从候选图标 key 中选一个，必须是英文 key。
- 优先概括“这门内容在学什么、解决什么卡点、服务什么任务”。

用户输入：{user_prompt or '未提供'}
资料名：{'、'.join(filenames) or '暂无'}
模式：{mode_label}
规划判断：{planning_note or '暂无'}
资料边界：{material_note or '暂无'}
主题提示：{'、'.join(normalized_topic_hints) or '暂无'}

候选 course_icon：
{options_text}

输出 JSON：
{{"course_name":"短课程名","course_icon":"book-open"}}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_course_identity",
        inputs={
            "user_prompt_chars": len(user_prompt or ""),
            "filename_count": len(filenames),
            "digest_mode": digest_mode,
            "planning_note_chars": len(planning_note or ""),
            "material_note_chars": len(material_note or ""),
            "topic_hint_count": len(normalized_topic_hints),
            "icon_option_count": len(COURSE_ICON_OPTIONS),
        },
        output=messages,
    )


__all__ = ["build_course_identity_messages"]
