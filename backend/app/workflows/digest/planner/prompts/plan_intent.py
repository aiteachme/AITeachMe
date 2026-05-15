"""Prompts for planner intent and query-grab generation."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.prompts.context import (
    render_latest_feedback,
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
    render_planner_context_mode,
)
from app.workflows.digest.planner.lib.plans import planner_mode_label

PLAN_QUERY_MIN = 3
PLAN_QUERY_MAX = 8


def build_plan_intent_messages(
    *,
    course_name: str,
    user_prompt: str,
    digest_mode: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
    latest_feedback: str | None = None,
    latest_plan: dict[str, Any] | None = None,
    existing_doc_context: str | None = None,
    planner_context_mode: str = "fresh_build",
) -> list[dict[str, str]]:
    # 这里只产出内部意图识别结果。它不直接展示给用户，只帮助计划合成器
    # 确定“用户想怎么学”和“该按什么问题去整理资料”。
    mode_label = planner_mode_label(digest_mode)
    is_revision = bool(latest_plan and str(latest_feedback or "").strip())
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    revision_guidance = (
        """
修订优先级：
- 这是对上一版方案的对话式修订，不是从零生成新方案。
- 先判断本轮是 patch_existing 还是 replace_existing_outline。
- patch_existing：用户是在上一版中局部增删改某章、改顺序、改风格、弱化/强化某部分。
- replace_existing_outline：用户给出新的具体专题、明确章数、或说“改成/生成 XXX 的 N 个章节”；这表示整版方案范围重定向，上一版只作为被替换对象和上下文，不应保留旧章节。
- 如果用户说“定积分的 5 个章节”“洛必达法则分几章”“把当前方案改成 XXX”，必须优先判为 replace_existing_outline，并输出 requested_chapter_count。
- plan_queries 必须服务 plan_change_mode：局部 patch 写编辑检查抓手；范围重定向写新专题拆分抓手。
""".strip()
        if is_revision
        else ""
    )
    task_instruction = (
        "请识别本轮对上一版方案的编辑意图，再把结果整理成内部修订意图合同。"
        if is_revision
        else "请先识别用户学习意图，再把结果整理成内部规划意图合同。"
    )
    contract_usage = (
        "修订意图合同不是最终展示内容，也不承诺已读取未完成资料或已确定证据来源；它只用于后续按上一版方案生成“计划说明 + 修订后完整大纲”。"
        if is_revision
        else "规划意图合同不是最终展示内容，也不承诺已读取未完成资料或已确定证据来源；它只用于后续生成“计划说明 + 初步大纲”。"
    )
    query_shape_label = (
        f"{PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条用于修订检查的编辑抓手"
        if is_revision
        else f"{PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条用于后续综合大纲的整理抓手"
    )
    field_requirements = (
        f"""
字段要求：
1. plan_intent 不超过 140 字，必须同时说明：
   - 编辑意图：本轮是局部编辑、整体重建、调整重点、改写风格，还是其他自然语言修改；
   - 影响对象：本轮主要影响上一版中的哪些章节、字段、顺序或整体边界；
   - 变更模式：本轮应 patch_existing 还是 replace_existing_outline。
2. plan_change_mode 只能输出 patch_existing 或 replace_existing_outline。
3. 如果用户给出新的具体专题或明确章数，必须输出 replace_existing_outline；不要把它当成上一版的局部补充。
4. requested_chapter_count 如果用户明确说了 N 章/N 个章节，输出整数 N；否则输出 null。
5. plan_queries 输出 {PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条，是给计划合成器的修订或重定向抓手。
6. patch_existing 时，plan_queries 写定位上一版对象、应用补丁、检查未改章节、确认完整修订大纲等编辑动作。
7. replace_existing_outline 时，plan_queries 写新 target_scope 的章节拆分、题型边界、方法步骤和易错诊断；不要继续围绕上一版旧章节。
8. 如果用户是在说更偏某主题、主要讲某主题、重点放某主题，这仍是 patch_existing，但它影响相关章节的权重、顺序、key_points 和低优先级章节取舍；plan_queries 必须要求后续大纲体现这种变化，不能只改 plan_text。
9. 如果用户意图不明确，就基于最近对话和上一版方案保守判断；但用户明确给出新专题/章数时，不得保守保留旧方案。
10. 不要输出来源名单、网站名、论文名、长解释、内部课程标识或重复内容。
""".strip()
        if is_revision
        else f"""
字段要求：
1. plan_intent 不超过 140 字，必须同时说明：
   - 用户意图：短期复习、系统课学习、题型突破、速查复盘、入门理解等；
   - 产出用途：用来备考、复习、补弱、建立体系或快速查漏；
   - 组织主线：资料应该按知识簇、题型、概念依赖、易错点或应用场景来整理。
2. plan_queries 输出 {PLAN_QUERY_MIN}-{PLAN_QUERY_MAX} 条，是给计划合成器的内部拆题抓手。
3. plan_queries 要服务意图识别结果，可以写知识簇、题型、方法、易错边界、应用场景或大纲拆分问题。
4. plan_queries 不要写成网站搜索词、来源列表或最终章节标题。
5. 如果用户意图不明确，就从资料形态和请求模式推断，但要保守表达。
6. 如果没有上传资料，就基于用户提示做通用意图识别，不要说“已上传资料显示/资料中包含”。
7. 若当前规划模式为已有文档重建/调整，plan_intent 和 plan_queries 必须围绕已有版本如何改造。
8. 如果本轮最新输入是在修改已有方案，必须判断这是对上一版的局部编辑还是整体重建；局部编辑只围绕被影响对象思考，不要扩展成未要求的全局合并或重排。
9. 不要输出来源名单、网站名、论文名、长解释、内部课程标识或重复内容。
""".strip()
    )
    examples_block = ""
    system_prompt = """
你是 AITeachMe 的学习规划意图分析器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
规划意图合同只服务后续计划合成，不是对用户的最终展示，也不承诺已读取未完成资料或已确定证据来源。
最新用户输入/本轮修改意见的优先级最高；课程名、资料标题和模式只能作为背景，不能覆盖用户刚刚说出的具体学习目标。
""".strip()
    prompt = f"""
{task_instruction}
{contract_usage}

课程/主题：{course_name}
用户提示：{user_prompt}
请求模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

{context_mode_block}

本轮最新输入/修改意见：
{render_latest_feedback(latest_feedback)}

上一版方案：
{render_latest_plan(latest_plan)}

最近对话：
{render_message_history(message_history)}

{revision_guidance}

只输出合法 JSON：
{{
  "plan_intent": "一小段内部规划意图",
  "plan_change_mode": "create_new | patch_existing | replace_existing_outline",
  "target_scope": "本轮真正要规划的学习范围；如果是窄范围专题，写清具体专题名",
  "scope_decision": "为什么本轮应按这个范围规划，以及是否需要避免扩展成整门课",
  "chapter_count_guidance": "章节数量和拆分颗粒度建议",
  "requested_chapter_count": null,
  "plan_queries": ["{query_shape_label}"],
  "content_preferences": ["用户最可能希望优先覆盖或暂缓展开的内容"],
  "chapter_split_guidance": "如何划分章节边界，尤其是用户要求同一知识点分多章时的拆分原则",
  "adjustment_options": ["后续最值得让用户确认或调整的问题；必须说明如果用户确认，会怎么改方案"]
}}

{field_requirements}

额外结构化判断要求：
1. 新建场景 plan_change_mode 输出 create_new；修订场景只能输出 patch_existing 或 replace_existing_outline。
2. 如果用户最新输入指向一个具体知识点、方法、定理、公式、题型或章节主题，例如“洛必达法则”“定积分”“矩阵初等变换”“贝叶斯公式”，target_scope 必须锁定这个具体对象；不要因为课程名是“高数”或模式是“速成课”就扩展成整门课。
3. 如果用户说“生成 XXX 的章节 / 拆成几章 / 分多个章节介绍 XXX / XXX 的 5 个章节”，scope_decision 必须说明“本轮只围绕 XXX 规划章节”；requested_chapter_count 必须写成用户指定的数字。
4. 只有用户明确说要“完整高数 / 全部知识 / 系统学完 / 从头到尾”时，target_scope 才可以是整门课或大范围主线。
5. content_preferences 必须来自你对用户提示、资料画像、上一版方案和最近对话的综合理解，不要写成片段摘取。
6. chapter_split_guidance 必须说明章节边界该如何服务学习路径；如果是完整课程，应优先提示后续合成器按课程目录/课时主题拆分，而不是按抽象学习动作拆分；如果用户希望围绕一个知识点展开多章，应按不同教学视角拆分，而不是合并成一章。
7. adjustment_options 输出 2-5 条，写成用户后续可以直接确认的问题或方向；每条必须包含“如果是/如果不是/如果你希望”这类条件，并说明会怎么调整方案，例如深浅、章节数、例题密度、先后顺序、是否偏考试或系统理解。
8. adjustment_options 会直接进入前端“可以继续这样改”区域，不要再依赖后续结构化大纲 LLM 另行生成。
9. 这些字段只服务后续大纲合成，不直接承诺已经读取未完成资料或确定证据来源。

{examples_block}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_plan_intent",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(user_prompt or ""),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history),
            "latest_feedback_chars": len(latest_feedback or ""),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
            "material_digest_chars": len(material_context.material_digest or ""),
            "plan_query_min": PLAN_QUERY_MIN,
            "plan_query_max": PLAN_QUERY_MAX,
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=messages,
    )


__all__ = ["build_plan_intent_messages"]
