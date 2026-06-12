"""Prompts for composing Planner output."""

from __future__ import annotations

import json
from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.lib.plans import planner_mode_label, render_planner_chapter_contract
from app.workflows.digest.planner.prompts.context import (
    render_latest_feedback,
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
)

PLAN_START = "<PLAN>"
PLAN_END = "</PLAN>"
SUGGESTION_START = "<SUGGESTION>"
SUGGESTION_END = "</SUGGESTION>"
CHAPTERS_START = "<CHAPTERS_JSON>"
CHAPTERS_END = "</CHAPTERS_JSON>"


def build_planner_stream_messages(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    planning_note: str,
    material_note: str,
    message_history: list[str],
    latest_feedback: str | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build the single streaming prompt for suggestion, plan and chapters."""

    is_revision = bool(latest_plan and str(latest_feedback or "").strip())
    mode_label = planner_mode_label(digest_mode)
    plan_fields = _render_previous_planner(latest_plan)
    revision_rules = (
        """
这是调整已有方案，不是重新识别 planning_note、course_name 或 course_icon。
你只能生成新的 suggestion、plan、chapters：
- 必须参考最近对话、用户本轮修改意见和上一版 planner。
- 未被用户修改的核心边界应保持稳定。
- 如果用户要求改范围、改章数、增删重点，chapters 必须可见地体现变化。
- 不要重新输出 planning_note、course_name 或 course_icon。
""".strip()
        if is_revision
        else """
这是第一次生成方案的第二阶段。
你要基于上一步的规划判断和资料边界，生成 suggestion、plan、chapters。
""".strip()
    )
    system_prompt = f"""
你是 AITeachMe 的课程规划输出器。
你必须严格按照三个标签输出，不能输出额外标签、Markdown 标题、代码块或解释。
{PLAN_START} 到 {PLAN_END} 之间是用户可见的 plan 字段，会被实时 SSE 展示；这段要自然、有判断力，像最终方案顶部的黑体说明。
{SUGGESTION_START} 到 {SUGGESTION_END} 之间是 suggestion 字段，写用户后续可以继续怎么改。
{CHAPTERS_START} 到 {CHAPTERS_END} 之间只能放合法 JSON 数组，数组元素只能包含 title 和 key_points。
""".strip()
    prompt = f"""
请生成方案的 suggestion、plan、chapters。

课程/主题：{course_name}
用户原始输入：{user_prompt or "未提供"}
模式：{mode_label}

规划判断：
{planning_note or "暂无"}

资料边界：
{material_note or "暂无"}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

最近对话：
{render_message_history(message_history)}

本轮修改意见：
{render_latest_feedback(latest_feedback)}

上一版 planner：
{plan_fields}

上一版方案摘要：
{render_latest_plan(latest_plan)}

{revision_rules}

章节规划合同：
{render_planner_chapter_contract(digest_mode)}

输出内容要求：
1. plan：180-360 字，讲清学习范围、模块拆分、先后顺序，以及练习/易错/应用如何嵌入各模块。
2. suggestion：2-4 句，给出用户可继续调整的方向，例如偏考试、延长周期、增加例题密度、减少拓展、改章节数。
3. chapters：输出完整章节列表；title 用清楚直观的课程目录名，通常 6-18 字，聚焦一个核心知识对象、方法任务、题型技能或应用场景；key_points 2-4 条承接细节、例题、练习或测验。
4. 标题保留必要限定词，细节枚举放进 key_points；资料来源、文件名、页码、天数等元信息只放上下文，不进标题。
5. 用户已经列出的模块/知识点是 chapters 的主边界；章节名优先对齐这些边界。练习、检测、错因复盘进入对应模块的 key_points；用户明确要综合卷、跨模块训练或考前模拟时，再把综合训练单独列成章节。
6. 没有资料时按用户目标和通用课程常识规划。
7. 如果用户明确要求 N 章，chapters 数量必须等于 N；如果要求 A-B 章，chapters 数量必须落在这个范围内。

严格按以下格式输出：
{PLAN_START}
plan 字段正文
{PLAN_END}
{SUGGESTION_START}
suggestion 字段正文
{SUGGESTION_END}
{CHAPTERS_START}
[{{"title":"章节标题","key_points":["关键词或任务1","关键词或任务2"]}}]
{CHAPTERS_END}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_composer",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "planning_note_chars": len(planning_note or ""),
            "material_note_chars": len(material_note or ""),
            "message_history_count": len(message_history),
            "latest_feedback_chars": len(latest_feedback or ""),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
        },
        output=messages,
    )


def build_planner_repair_messages(
    *,
    original_messages: list[dict[str, str]],
    invalid_output: str,
    error: str,
) -> list[dict[str, str]]:
    repair_prompt = f"""
上一次输出不符合 planner 标签协议，不能保存。
错误：{error}

请基于同一上下文重新输出完整结果。
必须严格包含：
{PLAN_START}...{PLAN_END}
{SUGGESTION_START}...{SUGGESTION_END}
{CHAPTERS_START}合法 JSON 数组{CHAPTERS_END}

上一轮错误输出：
{invalid_output[:6000]}
""".strip()
    return [*original_messages, {"role": "user", "content": repair_prompt}]


def _render_previous_planner(latest_plan: dict[str, Any] | None) -> str:
    if not latest_plan:
        return "暂无上一版方案"
    payload = {
        "planning_note": str(latest_plan.get("planning_note") or ""),
        "course_name": str(latest_plan.get("course_name") or ""),
        "course_icon": str(latest_plan.get("course_icon") or ""),
        "suggestion": str(latest_plan.get("suggestion") or ""),
        "plan": str(latest_plan.get("plan") or ""),
        "chapters": list(latest_plan.get("chapters") or []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = [
    "CHAPTERS_END",
    "CHAPTERS_START",
    "PLAN_END",
    "PLAN_START",
    "SUGGESTION_END",
    "SUGGESTION_START",
    "build_planner_repair_messages",
    "build_planner_stream_messages",
]
