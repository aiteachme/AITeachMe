"""Prompt builder for planner-created course display names."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.lib.plans import planner_mode_label

COURSE_NAME_EXAMPLES = (
    ("高数帮我系统理一下，我现在学得有点乱。", "高数主线重建"),
    ("线代快考试了，帮我整理成能冲刺复习的那种。", "线代考前抓手"),
    ("Python 数据分析想学到能做作业。", "Python作业通关"),
    ("心理学导论想系统学一下。", "心理学入门地图"),
    ("物理实验这块帮我整理点资料，我现在还是只会照着做。", "实验原理复盘"),
    ("C 语言从零开始，想能自己写小程序。", "C语言起步路径"),
    ("概率统计一到综合题就不会连。", "概率综合串联"),
    ("财务管理考试前帮我抓重点。", "财管冲刺清单"),
    ("设计史想按时间线和风格流派整理。", "设计史脉络"),
    ("机器学习作业老卡在模型和代码之间。", "机器学习实战桥"),
)


def _render_course_name_examples() -> str:
    return "\n".join(f"- 用户目标：{source} -> 标题：{title}" for source, title in COURSE_NAME_EXAMPLES)


def build_course_name_prompt(
    *,
    user_prompt: str,
    filenames: list[str],
    digest_mode: str,
    plan_intent: str = "",
    planner_brief: str = "",
    topic_hints: list[str] | None = None,
) -> str:
    """Build the short-title prompt used when creating a new learning space."""

    normalized_topic_hints = [str(item).strip() for item in list(topic_hints or []) if str(item).strip()]
    brief = " ".join(str(planner_brief or "").split()).strip()
    intent = " ".join(str(plan_intent or "").split()).strip()
    mode_label = planner_mode_label(digest_mode)
    prompt = f"""
请根据用户学习目标、规划意图、资料线索和主题提示，生成一个中文学习空间标题。
要求：
- 2 到 10 个汉字为佳，最多 16 个字符。
- 像常见对话标题一样简洁自然。
- 不要输出引号、编号、解释、标点。
- 不要写“新课程”“未命名”“学习资料”这类空泛标题。
- 不要总是写成“某某学习”“某某复习”“某某课程”“某某资料”；只有特别自然时才可使用这些后缀。
- 优先概括“这门内容到底在学什么、要解决什么卡点、面向什么任务”，不要直接照抄用户原话。
- 可以略微有记忆点，但不能像广告标题、营销口号或玩梗标题。
- 请先在心里生成 4 个不同角度的候选：学科对象、学习任务、能力断点、时间/场景；最后只输出最好的一项。
用户提示：{user_prompt or '未提供'}
资料名：{'、'.join(filenames) or '暂无'}
模式：{mode_label}
规划意图：{intent or '暂无'}
主题提示：{'、'.join(normalized_topic_hints) or '暂无'}
思考线索：{brief or '暂无'}

参考示例：
{_render_course_name_examples()}
""".strip()
    return trace_prompt_build(
        "planner_course_name",
        inputs={
            "user_prompt_chars": len(user_prompt or ""),
            "filename_count": len(filenames),
            "digest_mode": digest_mode,
            "plan_intent_chars": len(intent),
            "topic_hint_count": len(normalized_topic_hints),
            "planner_brief_chars": len(brief),
        },
        output=prompt,
    )


__all__ = ["build_course_name_prompt"]
