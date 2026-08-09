"""Prompts for composing Planner output."""

from __future__ import annotations

import json
from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.common.diagnose_policy import render_diagnose_action_policy
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

    has_previous_formal_plan = bool(
        latest_plan
        and str(latest_plan.get("plan") or "").strip()
        and list(latest_plan.get("chapters") or [])
    )
    is_revision = bool(has_previous_formal_plan and str(latest_feedback or "").strip())
    mode_label = planner_mode_label(digest_mode)
    plan_fields = _render_previous_planner(latest_plan)
    diagnose_action_policy = render_diagnose_action_policy(
        list((latest_plan or {}).get("diagnose") or []),
        status=str((latest_plan or {}).get("diagnose_status") or ""),
    )
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
- 一级章节 title 写成真实课程目录名：短、具体、能独立看懂；不要写成“模块：目标/方法/应用”的长标题。
- title 通常 4-12 个中文字符，最多不超过 14 个中文字符；细节、训练、检测、应用场景放进 key_points。
- 过宽的目录词只补一个核心对象或方法词，示例：“实数与代数式化简”“函数图像与解析式”“几何图形与证明”；不要补成长串。
- 用户明确给出 A/B/C 知识块并要求按它们划分时，title 序列与 A/B/C 对齐；如果列表项本身过宽，可保留原词并补一个短限定。
- key_points 描述所属章节内部的目标、概念、例题、易错点、练习、检测、纠错、巩固和时间安排。
- key_points 中能进入知识图谱的内容必须写成具体课程对象、方法名、题型名或错因名；不要把“图示”“方法步骤”“单元测试”“讲后纠错与回顾”“为后续章节打底”“整理”“判定题”“图表分析”作为独立要点。若用户要求图示/测试/纠错/整理/判定题/图表分析，要落成对象化表达，例如“函数图像读图”“函数值求解例题”“自变量与因变量混淆”“函数综合练习题型”“统计数据整理方法”“几何判定条件识别”“图表分析结论表达”。
- 用户同时给出学习天数时，天数按 A/B/C 的学习量分配到各知识块。
- 最后一个列表项与其他列表项保持同等授课粒度，围绕其自身的核心概念、例题、小测和纠错展开。
- 全程巩固、检测和纠错按服务对象拆入各章节；plan 结尾落到最后一个知识块自身的学习内容。
- 上一版 planner 中的前置诊断选择只作为生成参数：影响讲解起点、章节内篇幅侧重、例题/练习密度和文档内解析写法；不要把诊断选项变成一级章节、固定二级标题、章节数量或全章重复模板，除非用户明确这样要求。

输出内容由三个标签组成。
{PLAN_START} 到 {PLAN_END} 之间是用户可见的 plan 字段，会被实时 SSE 展示；这段要自然、有判断力，像最终方案顶部的黑体说明。
{SUGGESTION_START} 到 {SUGGESTION_END} 之间是 suggestion 字段，写成可调整参数：章节边界、每章时长、讲解深度、例题数量、练习密度、文档内小测题量和练后解析粒度。
{CHAPTERS_START} 到 {CHAPTERS_END} 之间放合法 JSON 数组，数组元素包含 title 和 key_points；用户指定知识块列表时，数组顺序与列表顺序一致。
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

前置诊断执行策略：
{diagnose_action_policy}

上一版方案摘要：
{render_latest_plan(latest_plan)}

{revision_rules}

章节规划合同：
{render_planner_chapter_contract(digest_mode)}

输出内容要求：
1. plan：180-360 字，讲清学习范围、模块拆分和先后顺序；用户给出 A/B/C 列表时，按 A/B/C 的名称逐项展开，全段优先使用具体模块名和具体学习任务；最后一个列表项与前面列表项保持同等粒度，结尾说明它自身的核心概念、例题、小测与纠错。
2. suggestion：2-4 句，直接给出可继续调整的具体参数，围绕范围、周期、讲解深度、例题密度、练习密度、文档内小测题量、练后解析粒度或章节数。
3. chapters：输出完整章节列表；title 写成学生能直接识别的课程目录名，通常 4-12 字，最多 14 字；只保留“核心主题 + 一个必要限定”，不要使用冒号、破折号或长副标题。
4. 每个一级章节负责一块可展开讲解的内容；例题、练习、测验、纠错和巩固安排进入 key_points，用来说明这一章的概念、方法、题型和易错点怎样练、怎样查。
4a. key_points 不能输出泛容器或教学动作当知识点：禁止独立写“图示”“方法步骤”“单元测试”“重点检查概念理解”“讲后纠错与回顾”“为后续章节打底”“整理”“判定题”“图表分析”。必须改写为本章具体课程对象，例如“函数图像读图”“辅助线证明思路”“函数值求解例题”“自变量与因变量混淆”“函数综合练习题型”“统计数据整理方法”“几何判定条件识别”“图表分析结论表达”；找不到具体对象时不要写该项。
5. title 保留必要限定词；细节枚举、资料来源、文件名、页码、天数、进度、训练和检测安排进入 plan 或 key_points。标题示例：实数与代数式化简、方程与不等式求解、函数图像与解析式、几何图形与证明、数据分析与概率应用。
6. 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单；chapters 与 A/B/C 逐项对应：第 i 个 chapter 负责第 i 个列表项，数组长度等于列表项数量；如果列表项已是清晰知识块名称，title 等于该列表项；如果只有宽泛类别，title 可在保留原词的基础上补一个短限定，进度、训练和检测安排放进 key_points。
7. 用户列出的学习活动按其服务的内容模块放进对应 key_points；plan 的顺序以用户给出的列表项为完整路径，各模块内部再安排练习、纠错和小测；最后一个列表项的检测也围绕该列表项自身的题型和易错点。
8. 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算；最后一个列表项按它自身的具体对象、方法和练习安排展开。
9. 没有资料时按用户目标和通用课程常识规划。
10. 如果用户明确要求 N 章，chapters 数量必须等于 N；如果要求 A-B 章，chapters 数量必须落在这个范围内；没有明确章数时参考章节规划合同，紧凑节奏也要拆出足够的可授课模块，但资料很少或目标很窄时可以合理少于参考下限。

严格按以下格式输出：
{PLAN_START}
plan 字段正文
{PLAN_END}
{SUGGESTION_START}
suggestion 字段正文
{SUGGESTION_END}
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
        "diagnose_status": str(latest_plan.get("diagnose_status") or ""),
        "diagnose_note": str(latest_plan.get("diagnose_note") or ""),
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
