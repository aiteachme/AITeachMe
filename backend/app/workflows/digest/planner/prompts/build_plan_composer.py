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
DIAGNOSE_START = "<DIAGNOSE_JSON>"
DIAGNOSE_END = "</DIAGNOSE_JSON>"
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
这是调整已有方案。
沿用上一版 planning_note、course_name 和 course_icon。
生成新的 suggestion、plan、chapters：
- 参考最近对话、用户本轮修改意见和上一版 planner。
- 保持用户未修改的核心边界稳定。
- 用户要求改范围、改章数、增删重点时，chapters 可见地体现变化。
""".strip()
        if is_revision
        else """
这是第一次生成方案的第二阶段。
你要基于上一步的规划判断和资料边界，生成 suggestion、plan、chapters。
""".strip()
    )
    system_prompt = f"""
你是 AITeachMe 的课程规划输出器。
高优先级规划规则：
- 用户给出 A/B/C 列表时，A/B/C 是唯一一级章节路径。
- 一级章节 title 采用知识目录名；用户列出 A/B/C 知识块时，title 序列等于 A/B/C。
- 章节内的练习、检测、纠错、回看和时间安排写入 key_points。
- 用户同时给出学习天数时，天数只分配到 A/B/C 内，最后一天落到最后一个列表项。
- 最后一个列表项的章节任务围绕该列表项自身的核心概念、例题、小测和纠错。

输出内容由四个标签组成。
{PLAN_START} 到 {PLAN_END} 之间是用户可见的 plan 字段，会被实时 SSE 展示；这段要自然、有判断力，像最终方案顶部的黑体说明。
{SUGGESTION_START} 到 {SUGGESTION_END} 之间是 suggestion 字段，写用户后续可以继续怎么改。
{DIAGNOSE_START} 到 {DIAGNOSE_END} 之间放合法 JSON 数组，作为前置诊断提问；每项包含 question、purpose、sample_answers。
{CHAPTERS_START} 到 {CHAPTERS_END} 之间放合法 JSON 数组，数组元素包含 title 和 key_points。
当用户指定按 A、B、C 知识块划分时，chapters 形如：
[{{"title":"A","key_points":["A 的学习目标、例题、练习或检测安排"]}}, {{"title":"B","key_points":["B 的学习目标、例题、练习或检测安排"]}}, {{"title":"C","key_points":["C 的学习目标、例题、练习或检测安排"]}}]
""".strip()
    prompt = f"""
请生成方案的 suggestion、plan、diagnose、chapters。

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
1. plan：180-360 字，讲清学习范围、模块拆分和先后顺序；用户给出 A/B/C 列表时，按 A/B/C 的名称逐项展开，全段优先使用具体模块名和具体学习任务，末尾落到最后一个列表项的核心概念、典型例题、小测与纠错。
2. suggestion：2-4 句，给出用户可继续调整的方向，围绕范围、周期、讲解深度、例题密度或章节数。
3. diagnose：输出 5-10 个前置诊断问题，优先覆盖章节主线、先修基础、薄弱点和学习偏好；每项 question 要像在和用户追问，purpose 写内部诊断目标，sample_answers 给 3-4 个可快速点击的示例回答。
4. chapters：输出完整章节列表；title 用清楚直观的课程目录名，通常 6-18 字，命名一个可授课的知识对象、方法模块、题型技能或应用场景。
5. 每个一级章节负责一块可展开讲解的内容；例题、练习、测验、纠错和巩固安排进入 key_points，用来说明这一章怎样练、怎样查漏。
6. 标题保留必要限定词，细节枚举放进 key_points；资料来源、文件名、页码、天数等元信息作为上下文处理，标题只呈现目录名。
7. 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单；chapters 与 A/B/C 逐项对应：第 i 个 chapter 负责第 i 个列表项，数组长度等于列表项数量；如果列表项已是知识块名称，title 等于该列表项，学习动作、周期和训练安排放进 key_points。
8. 用户列出的学习活动按其服务的内容模块放进对应 key_points；plan 的顺序以用户给出的列表项为完整路径，各模块内部再安排练习、纠错和小测。
9. 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算，末尾时间仍落到最后一个列表项的具体对象、方法和练习安排。
10. 没有资料时按用户目标和通用课程常识规划。
11. 如果用户明确要求 N 章，chapters 数量必须等于 N；如果要求 A-B 章，chapters 数量必须落在这个范围内。

严格按以下格式输出：
{PLAN_START}
plan 字段正文
{PLAN_END}
{SUGGESTION_START}
suggestion 字段正文
{SUGGESTION_END}
{DIAGNOSE_START}
[{{"question":"你对这一主题最熟的是哪一块？","purpose":"识别已有基础","sample_answers":["基础概念还可以","会做例题但不会变式","几乎没学过"]}}]
{DIAGNOSE_END}
{CHAPTERS_START}
[{{"title":"知识块名称","key_points":["学习目标、例题、练习或检测安排"]}}]
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
上一次输出需要按 planner 标签协议修复。
错误：{error}

请基于同一上下文重新输出完整结果。
必须严格包含：
{PLAN_START}...{PLAN_END}
{SUGGESTION_START}...{SUGGESTION_END}
{DIAGNOSE_START}合法 JSON 数组{DIAGNOSE_END}
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
        "diagnose": list(latest_plan.get("diagnose") or []),
        "chapters": list(latest_plan.get("chapters") or []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = [
    "CHAPTERS_END",
    "CHAPTERS_START",
    "DIAGNOSE_END",
    "DIAGNOSE_START",
    "PLAN_END",
    "PLAN_START",
    "SUGGESTION_END",
    "SUGGESTION_START",
    "build_planner_repair_messages",
    "build_planner_stream_messages",
]
