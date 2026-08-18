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
DIAGNOSE_START = "<DIAGNOSE_JSON>"
DIAGNOSE_END = "</DIAGNOSE_JSON>"
COURSE_NAME_START = "<COURSE_NAME>"
COURSE_NAME_END = "</COURSE_NAME>"
CHAPTERS_START = "<CHAPTERS_JSON>"
CHAPTERS_END = "</CHAPTERS_JSON>"
BUILD_CONSTRAINTS_START = "<BUILD_CONSTRAINTS_JSON>"
BUILD_CONSTRAINTS_END = "</BUILD_CONSTRAINTS_JSON>"


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
- title 通常 4-12 个中文字符，最多不超过 14 个中文字符；细节、训练、检测、应用场景放进 required_elements。
- 过宽的目录词只补一个核心对象或方法词，示例：“实数与代数式化简”“函数图像与解析式”“几何图形与证明”；不要补成长串。
- 用户明确给出 A/B/C 知识块并要求按它们划分时，title 序列与 A/B/C 对齐；如果列表项本身过宽，可保留原词并补一个短限定。
- objective 是本章独有、可观察的学习结果，不能把 required_elements 机械拼接成一句话。
- required_elements 只描述需要用户确认的覆盖范围，写成具体概念、方法、题型或易错对象；不要在这里决定开篇方式、讲解顺序、资料落点、例题数量、练习策略或小测配置。
- required_elements 不能把“图示”“方法步骤”“单元测试”“讲后纠错与回顾”“为后续章节打底”“整理”“判定题”“图表分析”这类教学动作或泛容器当成独立知识点；若用户明确要求某类内容，写成具体课程对象，例如“函数图像读图”“自变量与因变量混淆”“几何判定条件识别”。
- 用户同时给出学习天数时，天数按 A/B/C 的学习量分配到各知识块。
- 最后一个列表项与其他列表项保持同等授课粒度，围绕其自身的核心概念、例题、小测和纠错展开。
- 全程巩固、检测和纠错按服务对象拆入各章节；plan 结尾落到最后一个知识块自身的学习内容。
- 上一版 planner 中的前置诊断选择只作为生成参数：影响讲解起点、章节内篇幅侧重、例题/练习密度和文档内解析写法；不要把诊断选项变成一级章节、固定二级标题、章节数量或全章重复模板，除非用户明确这样要求。

输出内容由五个标签组成。
{COURSE_NAME_START} 到 {COURSE_NAME_END} 之间是整门课程的短标题；必须概括用户的完整建课目标，不能从并列覆盖项中只取第一项。
{PLAN_START} 到 {PLAN_END} 之间是用户可见的 plan 字段，会被实时 SSE 展示；这段要自然、有判断力，像最终方案顶部的黑体说明。
{SUGGESTION_START} 到 {SUGGESTION_END} 之间是 suggestion 字段，写成可调整参数：章节边界、每章时长、讲解深度、例题数量、练习密度、文档内小测题量和练后解析粒度。
{BUILD_CONSTRAINTS_START} 到 {BUILD_CONSTRAINTS_END} 之间放合法 JSON 对象，把前置诊断对篇幅细致程度的选择落成每章字数合同。
{CHAPTERS_START} 到 {CHAPTERS_END} 之间放合法 JSON 数组；每个元素只包含 title、objective、required_elements；用户指定知识块列表时，数组顺序与列表顺序一致。
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

前置诊断选择与模型生成的文档落点：
{diagnose_action_policy}

上一版方案摘要：
{render_latest_plan(latest_plan)}

{revision_rules}

章节规划合同：
{render_planner_chapter_contract(digest_mode)}

输出内容要求：
0. course_name：最多 16 个字符，概括整门课程的学科、完整范围和用途；用户已明确课程名称时保留核心名称；多个并列模块必须用共同上位主题概括，不能取其中一项代替整门课。
1. plan：140-280 字，讲清学习范围、模块拆分和先后顺序；用户给出 A/B/C 列表时，按 A/B/C 的名称逐项展开，全段优先使用具体模块名和具体学习任务；最后一个列表项与前面列表项保持同等粒度。
2. suggestion：2-4 句，直接给出可继续调整的具体参数，围绕范围、周期、讲解深度、例题密度、练习密度、文档内小测题量、练后解析粒度或章节数。
3. chapters：输出完整章节列表；title 写成学生能直接识别的课程目录名，通常 4-12 字，最多 14 字；只保留“核心主题 + 一个必要限定”，不要使用冒号、破折号或长副标题。
4. 每个一级章节负责一块可展开讲解的内容；objective 说明学完本章能理解、判断或完成什么；required_elements 只列需要用户确认的具体概念、方法、题型和易错对象。
4a. required_elements 禁止独立写“图示”“方法步骤”“单元测试”“重点检查概念理解”“讲后纠错与回顾”“为后续章节打底”“整理”“判定题”“图表分析”等教学动作或泛容器；找不到具体课程对象时不要写该项。
5. title 保留必要限定词；资料来源、文件名、页码、天数和进度放进 plan，不要塞进章节标题或 required_elements。标题示例：实数与代数式化简、方程与不等式求解、函数图像与解析式、几何图形与证明、数据分析与概率应用。
6. 用户以“按 A、B、C 划分章节/模块/单元”给出列表时，这个列表就是完整一级章节清单；chapters 与 A/B/C 逐项对应：第 i 个 chapter 负责第 i 个列表项，数组长度等于列表项数量；如果列表项已是清晰知识块名称，title 等于该列表项；如果只有宽泛类别，title 可在保留原词的基础上补一个短限定。
7. 用户明确列出的学习活动只需在 plan 中说明其服务范围；不要在 Planner 阶段为每章展开写作、例题、练习、小测或资料使用策略，这些由 DocGen 根据确认范围和诊断答案统一制定。
8. 用户同时给出学习天数和 A/B/C 列表时，天数是 A/B/C 的进度预算；最后一个列表项按它自身的具体对象、方法和练习安排展开。
9. 没有资料时按用户目标和通用课程常识规划。
10. 如果用户明确要求 N 章，chapters 数量必须等于 N；如果要求 A-B 章，chapters 数量必须落在这个范围内；没有明确章数时参考章节规划合同，紧凑节奏也要拆出足够的可授课模块，但资料很少或目标很窄时可以合理少于参考下限。
11. build constraints 必须根据用户原始要求和已回答的前置诊断选择输出：
    - 精炼提纲：chapter_length_profile=`outline`，每章 min/target/max 约 1400/1800/2200 字；
    - 标准讲解：`standard`，约 2400/3000/3600 字；这是没有明确选择时的默认值；
    - 细致推导：`detailed`，约 3400/4200/5000 字；
    - 从零铺垫：`foundation`，约 4200/5200/6200 字。
    选项文案可能不同，要按语义映射；用户明确给出篇幅时优先遵守。三个数字必须满足 min <= target <= max，不要只在 plan 文案里描述篇幅。

严格按以下格式输出：
{COURSE_NAME_START}课程短标题{COURSE_NAME_END}
{PLAN_START}
plan 字段正文
{PLAN_END}
{SUGGESTION_START}
suggestion 字段正文
{SUGGESTION_END}
{BUILD_CONSTRAINTS_START}
{{"chapter_length_profile":"standard","chapter_min_words":2400,"chapter_target_words":3000,"chapter_max_words":3600}}
{BUILD_CONSTRAINTS_END}
{CHAPTERS_START}
[{{"title":"知识块名称","objective":"本章独有的可观察学习结果","required_elements":["具体概念、方法、题型或易错对象"]}}]
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
    """Build personalized questions that map directly to Planner and DocGen parameters."""

    mode_label = planner_mode_label(digest_mode)
    system_prompt = f"""
你是 AITeachMe 的前置诊断题设计器。
本阶段不是画像问卷，也不是学习偏好调查；产物是课程名和 4 个单选题，用来冻结正式 Planner 和后续 DocGen 的可执行写作参数。

课程名要求：
- 根据完整建课目标和资料范围，概括整门课程的学科、主题与用途，最多 16 个字符。
- 用户已经明确课程名称时保留其核心名称；用户列出多个并列模块时，课程名必须覆盖整个集合，不能取其中一项代替整门课。
- 不使用“学习课程”“课程方案”等空泛名称，不写完整句子，不添加引号或标签。
- 用户完整建课目标和资料范围的优先级高于当前暂存名称；暂存名称只是一条弱提示。

生成问题前先在内部完成以下判断，不要输出判断过程：
1. 提炼整门课程的目标、完整范围、主要模块、用途、时间与资料约束，形成课程级地图。
2. 区分用户已经明确的条件与仍未确定的条件；已经明确的内容不要换个说法再次询问。
3. 从仍未确定的条件中，按“答案会对整门课程结构和正文生成产生多大影响”排序。
4. 选择 4 个互不重复、信息增益最高的课程级决策生成问题。

四题没有固定题面或固定顺序，但只要用户尚未明确，就优先包含下面两个对后续正文影响最大的课程级决策：
- 整门课程希望采用怎样的篇幅与讲解细致程度，例如精炼提纲、标准讲解、细致推导或从零铺垫；答案必须能改变各章目标字数、解释层次、推导展开和背景补充。
- 整门课程希望采用怎样的例题、练习与章末小测密度，以及解析写到什么粒度；答案必须能改变各章例题数量、变式密度、小测配置、答案步骤和错因提示。
其余问题从下面的课程级规划层面中选择信息增益最高且用户尚未明确的内容：
- 学习者对完整范围的总体起点与目标深度。
- 主要模块之间的覆盖比例、先后关系或应用重心。
- 全课的组织方式、示例类型或资料使用策略。
- 全课的应用任务、检查方式或反馈重点。
如果用户已经明确其中某项，就替换为另一个真正会改变课程方案的未决条件。

问题主语应是整门课程、完整学习范围或同一层级的主要模块组。一个回答至少应能改变多个章节，或改变全课的深度、组织、示例、练习与反馈策略。个性化应体现在对课程范围的准确概括、模块分组和选项语义上；只有当用户的课程本身就很窄时，才把该主题内部的主要能力维度视为课程级模块。

当某题询问模块覆盖或内容重心时，四个选项必须在同一层级上共同覆盖用户列出的全部主要模块。主要模块超过三个时，应按关联性合并成容易理解的模块组，并保留一个整体均衡方案；不能只列输入靠前的几项而让后续模块消失。

题面和选项要求：
- question 通常 8-24 个中文字符，直问一个可执行取舍。
- 每题 options 必须正好 4 个互斥选项。
- 每个 option 必须使用“短标签｜具体影响”的格式：短标签便于选择，具体影响说明该选项会怎样改变后续课程文档。
- 短标签通常 4-10 个中文字符；具体影响通常 8-24 个中文字符；整个 option 最长不超过 48 个中文字符。
- 影响说明必须写可执行结果，例如每章目标字数、讲解层次、推导展开、背景补充、例题数量、变式密度、小测题量、答案步骤、错因提示或模块重心，不能只写“更详细”“更适合”等空话。
- 章末测试是当前文档发布合同的固定组成部分；练习密度最低的选项也要保留 1-2 道短测，只能调整题量与解析粒度，不能写“不设小测”“取消测试”。
- 不把诊断写成知识测验，不问抽象人格或无法写进文档的偏好。
- 不承诺提分、掌握或通过考试等无法验证的效果。

purpose 必须以“文档落点：”开头，明确这道题会改变哪些实际文档部件，例如讲解起点、章节篇幅、例题难度、练习密度、章末小测、答案解析或错因提示。不要写章节编号或章节数量。

输出前自检：
- course_name 是可直接展示的短标题，不是用户指令的截断片段。
- 四个问题分别补齐四个不同的课程级未决条件，没有重复用户已经明确的信息；若篇幅细致程度和题目/解析密度尚未明确，必须覆盖这两项。
- 每个问题的答案都会实质改变多个章节或全课生成策略，整体范围没有被输入中的某一项悄悄缩窄。
- JSON 数组正好 4 项，每项都有 question、purpose、options。
- 每个 options 正好 4 个不重复的“短标签｜具体影响”，四种影响形成清晰梯度或互斥取舍。
- 四题只控制 Planner 与 DocGen 能落实的课程结构和文档生成策略，不延伸到 Examine/Profile。

输出内容只包含：
{COURSE_NAME_START} 到 {COURSE_NAME_END} 之间的课程短标题；
{DIAGNOSE_START} 到 {DIAGNOSE_END} 之间的合法 JSON 数组。
""".strip()
    prompt = f"""
请为当前课程生成个性化前置诊断单选题。

用户完整建课目标（课程命名与诊断范围的唯一优先依据）：
{user_prompt or "未提供"}

当前暂存名称（可能不完整；仅在上面的用户目标未提供时参考）：
{course_name}

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
  {{"question":"针对当前课程的短问题","purpose":"文档落点：会改变的正文部件","options":["短标签一｜对应的具体生成影响","短标签二｜对应的具体生成影响","短标签三｜对应的具体生成影响","短标签四｜对应的具体生成影响"]}}
]

严格按以下格式输出：
{COURSE_NAME_START}课程短标题{COURSE_NAME_END}
{DIAGNOSE_START}
[{{"question":"问题文本","purpose":"文档落点：具体生成策略","options":["短标签一｜具体影响","短标签二｜具体影响","短标签三｜具体影响","短标签四｜具体影响"]}}]
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
{COURSE_NAME_START}非空课程短标题{COURSE_NAME_END}
{PLAN_START}...{PLAN_END}
{SUGGESTION_START}...{SUGGESTION_END}
{BUILD_CONSTRAINTS_START}合法 JSON 对象{BUILD_CONSTRAINTS_END}
{CHAPTERS_START}合法 JSON 数组{CHAPTERS_END}
每个章节必须完整包含非空的 title、objective、required_elements；不要新增写作策略字段，也不要用固定通用话术补字段。

上一轮错误输出：
{invalid_output[:6000]}
""".strip()
    messages = [*original_messages, {"role": "user", "content": repair_prompt}]
    return trace_prompt_build(
        "planner_plan_repair",
        inputs={
            "original_message_count": len(original_messages),
            "invalid_output_chars": len(invalid_output or ""),
            "error_chars": len(error or ""),
        },
        output=messages,
    )


def build_planner_diagnosis_repair_messages(
    *,
    original_messages: list[dict[str, str]],
    invalid_output: str,
    error: str,
) -> list[dict[str, str]]:
    repair_prompt = f"""
上一次输出需要按前置诊断协议修复。
错误：{error}

请基于同一课程上下文重新输出完整结果。不得删除、截短或本地改写已有语义；请由你重新生成满足合同的内容。
必须严格包含：
{COURSE_NAME_START}非空课程短标题{COURSE_NAME_END}
{DIAGNOSE_START}正好四项的合法 JSON 数组{DIAGNOSE_END}
每项必须完整包含非空 question、以“文档落点：”开头的 purpose，以及正好四个互不重复的“短标签｜具体影响” options；每个 option 最长 48 个字符。

上一轮错误输出：
{invalid_output[:6000]}
""".strip()
    messages = [*original_messages, {"role": "user", "content": repair_prompt}]
    return trace_prompt_build(
        "planner_diagnosis_repair",
        inputs={
            "original_message_count": len(original_messages),
            "invalid_output_chars": len(invalid_output or ""),
            "error_chars": len(error or ""),
        },
        output=messages,
    )


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
        "build_constraints": dict(latest_plan.get("build_constraints") or {}),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = [
    "CHAPTERS_END",
    "CHAPTERS_START",
    "BUILD_CONSTRAINTS_END",
    "BUILD_CONSTRAINTS_START",
    "COURSE_NAME_END",
    "COURSE_NAME_START",
    "DIAGNOSE_END",
    "DIAGNOSE_START",
    "PLAN_END",
    "PLAN_START",
    "SUGGESTION_END",
    "SUGGESTION_START",
    "build_planner_diagnosis_messages",
    "build_planner_diagnosis_repair_messages",
    "build_planner_repair_messages",
    "build_planner_stream_messages",
]
