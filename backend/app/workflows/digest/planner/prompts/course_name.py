"""Prompt builder for planner course name and icon identity."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.support.courses.icons import COURSE_ICON_OPTIONS


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
    options_text = ", ".join(COURSE_ICON_OPTIONS)
    system_prompt = """
你是 AITeachMe 的课程命名与图标选择器。输出合法 JSON。
""".strip()
    prompt = f"""
请根据用户学习目标、规划判断、资料线索和主题提示，生成课程展示身份。

字段要求：
- course_name：用于课程列表的稳定标题，最多 16 个字符。
- course_name 直接命名学习主题，优先覆盖用户要学的学段、学科、知识对象、资料名或考试科目。
- 进度、训练、用途和其他安排写入 plan、suggestion 或 key_points，course_name 保持为主题本身。
- 用户同时给出主题和章节清单时，course_name 取主题，章节清单进入章节规划。
- course_icon：只能从候选图标 key 中选一个，必须是英文 key。

用户输入：{user_prompt or '未提供'}
资料名：{'、'.join(filenames) or '暂无'}
主题提示：{'、'.join(normalized_topic_hints) or '暂无'}

候选 course_icon：
{options_text}

输出 JSON：
{{"course_name":"主题名","course_icon":"book-open"}}
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
