"""Prompt builder for planner course name and icon identity."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.lib.plans import planner_mode_label
from app.workflows.support.courses.icons import COURSE_ICON_OPTIONS

COURSE_NAME_EXAMPLES = (
    ("高数帮我系统理一下，我现在学得有点乱。", "高数主线重建", "sigma"),
    ("线代快考试了，帮我整理成能冲刺复习的那种。", "线代考前抓手", "calculator"),
    ("Python 数据分析想学到能做作业。", "Python作业通关", "code"),
    ("心理学导论想系统学一下。", "心理学入门地图", "brain"),
    ("财务管理考试前帮我抓重点。", "财管重点清单", "chart-line"),
)


def _render_course_name_examples() -> str:
    return "\n".join(
        f"- 用户目标：{source} -> course_name：{title}，course_icon：{icon}"
        for source, title, icon in COURSE_NAME_EXAMPLES
    )


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
    mode_label = planner_mode_label(digest_mode)
    options_text = ", ".join(COURSE_ICON_OPTIONS)
    system_prompt = """
你是 AITeachMe 的课程命名与图标选择器。你只输出合法 JSON，不输出解释、Markdown 或额外文本。
""".strip()
    prompt = f"""
请根据用户学习目标、规划判断、资料线索和主题提示，生成课程展示身份。

字段要求：
- course_name：2 到 10 个汉字为佳，最多 16 个字符；像真实对话标题一样自然。
- course_name 不要写“新课程”“学习资料”“未命名”，不要总是套“学习/课程/资料”后缀。
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

参考示例：
{_render_course_name_examples()}

只输出 JSON：
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
