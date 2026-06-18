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

    has_previous_formal_plan = bool(
        latest_plan
        and str(latest_plan.get("plan") or "").strip()
        and list(latest_plan.get("chapters") or [])
    )
    is_revision = bool(has_previous_formal_plan and str(latest_feedback or "").strip())
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
- 一级章节 title 写成真实课程目录名：短、具体、能独立看懂；不要写成“模块：目标/方法/应用”的长标题。
- title 通常 4-12 个中文字符，最多不超过 14 个中文字符；细节、训练、检测、应用场景放进 key_points。
- 过宽的目录词只补一个核心对象或方法词，示例：“实数与代数式化简”“函数图像与解析式”“几何图形与证明”；不要补成长串。
- 用户明确给出 A/B/C 知识块并要求按它们划分时，title 序列与 A/B/C 对齐；如果列表项本身过宽，可保留原词并补一个短限定。
- key_points 描述所属章节内部的目标、概念、例题、易错点、练习、检测、纠错、巩固和时间安排。
- 用户同时给出学习天数时，天数按 A/B/C 的学习量分配到各知识块。
- 最后一个列表项与其他列表项保持同等授课粒度，围绕其自身的核心概念、例题、小测和纠错展开。
- 全程巩固、检测和纠错按服务对象拆入各章节；plan 结尾落到最后一个知识块自身的学习内容。
- 上一版 planner 中的前置诊断选择是本次正式方案的约束，plan、suggestion、chapters 按这些选择组织。

输出内容由三个标签组成。
{PLAN_START} 到 {PLAN_END} 之间是用户可见的 plan 字段，会被实时 SSE 展示；这段要自然、有判断力，像最终方案顶部的黑体说明。
{SUGGESTION_START} 到 {SUGGESTION_END} 之间是 suggestion 字段，写成可调整参数：章节边界、每章时长、讲解深度、例题数量、练习密度、测试题量和测后反馈粒度。
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

上一版方案摘要：
{render_latest_plan(latest_plan)}

{revision_rules}

章节规划合同：
{render_planner_chapter_contract(digest_mode)}

输出内容要求：
1. plan：180-360 字，讲清学习范围、模块拆分和先后顺序；用户给出 A/B/C 列表时，按 A/B/C 的名称逐项展开，全段优先使用具体模块名和具体学习任务；最后一个列表项与前面列表项保持同等粒度，结尾说明它自身的核心概念、例题、小测与纠错。
2. suggestion：2-4 句，直接给出可继续调整的具体参数，围绕范围、周期、讲解深度、例题密度、练习密度、测试题量、测后反馈粒度或章节数。
3. chapters：输出完整章节列表；title 写成学生能直接识别的课程目录名，通常 4-12 字，最多 14 字；只保留“核心主题 + 一个必要限定”，不要使用冒号、破折号或长副标题。
4. 每个一级章节负责一块可展开讲解的内容；例题、练习、测验、纠错和巩固安排进入 key_points，用来说明这一章的概念、方法、题型和易错点怎样练、怎样查。
5. title 保留必要限定词；细节枚举、资料来源、文件名、页码、天数、进度、训练和检测安排进入 plan 或 key_points。标题示例：实数与代数式化简、方程与不等式求解、函数图像与解析式、几何图形与证明、数据分析与概率应用。
6. 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单；chapters 与 A/B/C 逐项对应：第 i 个 chapter 负责第 i 个列表项，数组长度等于列表项数量；如果列表项已是清晰知识块名称，title 等于该列表项；如果只有宽泛类别，title 可在保留原词的基础上补一个短限定，进度、训练和检测安排放进 key_points。
7. 用户列出的学习活动按其服务的内容模块放进对应 key_points；plan 的顺序以用户给出的列表项为完整路径，各模块内部再安排练习、纠错和小测；最后一个列表项的检测也围绕该列表项自身的题型和易错点。
8. 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算；最后一个列表项按它自身的具体对象、方法和练习安排展开。
9. 没有资料时按用户目标和通用课程常识规划。
10. 如果用户明确要求 N 章，chapters 数量必须等于 N；如果要求 A-B 章，chapters 数量必须落在这个范围内。

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


def build_planner_diagnosis_messages(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    planning_note: str,
    material_note: str,
    message_history: list[str],
) -> list[dict[str, str]]:
    """Build the first-stage prompt that only asks useful planner/docgen questions."""

    mode_label = planner_mode_label(digest_mode)
    system_prompt = f"""
你是 AITeachMe 的前置诊断器。
本阶段的唯一产物是 4 个单选诊断题，用来决定正式 planner 和后续 DocGen 的生成参数。
只问后续文档能直接落实的选择：讲解起点、章节优先级、例题/练习密度、章末测试配置、测后反馈粒度。
不要问抽象偏好、人格画像、难以写进文档的目标，也不要承诺无法验证的效果。
题目和选项必须短、直观，像快速选择题，不像配置说明。
question 通常 8-20 个中文字符；每题 options 必须正好 4 个互斥选项，每项通常 4-12 个中文字符，最长不超过 16 个中文字符。
四题需要覆盖不同落点：基础起点、讲解重心、练习/测试密度、测后反馈方式；不要四题都问同一类偏好。
每个 option 用学生容易理解的短标签，能映射到正文中的讲法、例题、练习、测验或解析方式，例如“先补基础”“例题带路”“多练变式”“错因提醒”；避免“重某某思维”“强化能力”这类难落地标签。
purpose 写清文档落点，例如“文档落点：影响函数章节的讲解起点、例题难度和章末小测题型”。

输出内容只包含：
{DIAGNOSE_START} 到 {DIAGNOSE_END} 之间放合法 JSON 数组。
""".strip()
    prompt = f"""
请生成前置诊断单选题。

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

输出 JSON 结构：
[
  {{"question":"短问题","purpose":"文档落点：它会改变哪些章节内容","options":["短选项一","短选项二","短选项三","短选项四"]}}
]

诊断题要求：
1. 每题都必须能在 DocGen 文档中看见结果，不能只是“学习风格偏好”。
2. 选项避免“提高能力、强化思维、大量训练、重竞赛思维”这类空话，也不要写成长句；把具体执行细节写进 purpose。
3. 如果用户给出考试、天数、章节清单或资料边界，优先围绕这些约束提问。
4. 固定输出 4 题，不要重复问同一维度。
5. 可用题目示例：“基础从哪起？”“讲解重哪里？”“练习怎么放？”“解析要多细？”。
6. 可用选项示例：“先补基础”“例题带路”“多练变式”“章末小测”“错因提醒”。

严格按以下格式输出：
{DIAGNOSE_START}
[{{"question":"问题文本","purpose":"文档落点：影响的章节、例题、练习、测验或解析配置","options":["短选项一","短选项二","短选项三","短选项四"]}}]
{DIAGNOSE_END}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_diagnosis",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "planning_note_chars": len(planning_note or ""),
            "material_note_chars": len(material_note or ""),
            "message_history_count": len(message_history),
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
    "DIAGNOSE_END",
    "DIAGNOSE_START",
    "PLAN_END",
    "PLAN_START",
    "SUGGESTION_END",
    "SUGGESTION_START",
    "build_planner_diagnosis_messages",
    "build_planner_repair_messages",
    "build_planner_stream_messages",
]
