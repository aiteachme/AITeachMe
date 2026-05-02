"""Prompts for composing final planner build plans."""

from __future__ import annotations

import json
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import (
    PlanIntent,
    PlannerBrief,
)
from app.workflows.digest.planner.lib.plans import planner_mode_label, render_planner_chapter_contract
from app.workflows.digest.planner.prompts.context import (
    render_latest_feedback,
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
    render_planner_context_mode,
)
from app.workflows.digest.planner.prompts.examples import render_composer_examples

PLAN_JSON_MARKER = "<PLAN_JSON>"
PLAN_JSON_END_MARKER = "</PLAN_JSON>"
DEFAULT_PLAN_INTENT = "围绕用户提示和资料主线，先整理资料边界，再生成可调整的初步大纲。"
RAW_REPAIR_RESPONSE_LIMIT = 9000


def _clip_raw_response(raw_response: str) -> str:
    text = str(raw_response or "").strip()
    if len(text) <= RAW_REPAIR_RESPONSE_LIMIT:
        return text or "模型未返回可解析内容。"
    return text[:RAW_REPAIR_RESPONSE_LIMIT].rstrip() + "\n...[已截断]"


def _render_plan_queries(plan_intent: PlanIntent) -> str:
    queries = [item.strip() for item in plan_intent.plan_queries if item.strip()]
    if not queries:
        return "- 暂无明确规划抓手"
    return "\n".join(f"- {item}" for item in queries)


def _render_latest_plan_json(latest_plan: dict[str, Any] | None) -> str:
    if not latest_plan:
        return "{}"
    return json.dumps(latest_plan, ensure_ascii=False, indent=2)


def build_plan_composer_messages(
    *,
    course_name: str,
    user_prompt: str | None = None,
    digest_mode: str,
    material_context: DigestMaterialContext,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
    message_history: list[str] | None = None,
    latest_feedback: str | None = None,
    latest_plan: dict[str, Any] | None = None,
    existing_doc_context: str | None = None,
    planner_context_mode: str = "fresh_build",
) -> list[dict[str, str]]:
    """构造规划器最终大纲合成提示词。

    输出协议分两层：先流式给用户可见的计划说明，再在隐藏 JSON 中返回
    plan_text / plan_steps / chapters。前端只展示 marker 之前的内容。
    """

    resolved_user_prompt = (user_prompt or "").strip()
    sketch = planner_brief.markdown.strip() or "暂无可见规划判断"
    plan_queries = _render_plan_queries(plan_intent)
    plan_intent_text = plan_intent.plan_intent.strip() or DEFAULT_PLAN_INTENT
    mode_label = planner_mode_label(digest_mode)
    chapter_contract = render_planner_chapter_contract(digest_mode)
    feedback_text = (latest_feedback or "").strip()
    is_revision = bool(latest_plan and feedback_text)
    task_title = "对上一版方案做对话式修订" if is_revision else "生成一份构建前研究计划"
    task_layers = (
        "\n".join(
            [
                "你要基于上一版构建计划做一次对话式修订，分成三层：",
                "1. 计划说明：用一段话说明这次会如何按用户修改意见调整方案，不要展开章节正文。",
                "2. 计划步骤：拆出 3-6 条可检查动作，说明如何应用修改、检查衔接并形成修订大纲。",
                "3. 初步大纲：输出修订后的完整章节骨架。",
            ]
        )
        if is_revision
        else "\n".join(
            [
                "你要生成一份构建前研究计划，分成三层：",
                "1. 计划说明：用一段话说明接下来会如何查找、对照、整理和判断，不要提前展开章节内容。",
                "2. 计划步骤：拆出 4-7 条可检查动作，可以包含“查询、对照、搜集、调研、归并、筛选、整理”等动作。",
                "3. 初步大纲：只给粗颗粒章节骨架，后续还会继续调整，不要写得像最终目录。",
            ]
        )
    )
    revision_contract = (
        f"""
上一版方案 JSON（修订源对象）：
{_render_latest_plan_json(latest_plan)}

修订方式：
- 把上一版方案 JSON 当成源对象，像编辑文档一样应用“本轮最新输入/修改意见”。
- 未被本轮修改意见影响的章节，title 和 key_points 保持原样。
- 如果用户明确要求整体重建、重新规划、重排主线或改成新的总章数，才重新划分全局章节。
- 输出的 chapters 必须是修订后的完整章节列表，不是差异列表。
""".strip()
        if is_revision
        else ""
    )
    chapter_count_instruction = (
        "- 修订时，章节数量由上一版方案应用本轮修改后自然得到；不要被默认参考章数牵引成重新规划。"
        if is_revision
        else "- chapters 数量和章节边界由用户目标、资料复杂度、请求模式和系统级章节规划合同共同决定。"
    )
    examples_block = "" if is_revision else f"\n示例规律：\n{render_composer_examples()}"
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    # 第一段是用户会看到的 plan_text；JSON 是机器合同。这里允许写
    # “拟查询/对照/搜集”的研究动作，但不能写成已经完成检索。
    system_prompt = f"""
你是 AITeachMe 的构建计划合成器。
你必须先输出用户可见的自然语言计划说明，再输出 {PLAN_JSON_MARKER} 包裹的机器可解析 JSON。
你不能声称已经完成检索或已经读到外部来源；规划阶段只负责制定研究和整理计划。
当前任务：{task_title}。
你生成的章节是后续知识文档生成器的冻结执行合同。
如果当前任务是修订，用户本轮修改意见和上一版方案优先于默认参考章数。

{chapter_contract}
""".strip()
    prompt = f"""
{task_layers}

重要边界：
- 规划阶段现在只制定研究/整理计划，不代表已经执行检索。
- 可以写“后续会查询/对照/搜集哪些方向”，不要写“已经查到/来源显示/某网站或某论文指出”。

主题：{course_name}
用户提示：{resolved_user_prompt}
模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

{context_mode_block}

本轮最新输入/修改意见：
{render_latest_feedback(latest_feedback)}

最近对话与修改意见：
{render_message_history(message_history)}

上一版方案：
{render_latest_plan(latest_plan)}

{revision_contract}

可见规划判断：
{sketch}

内部规划意图：
{plan_intent_text}

内部规划抓手：
{plan_queries}

可见输出要求：
- 先立即输出一段计划说明，不要标题、编号、项目符号。
- 计划说明控制在 140-320 字，重点写“我会先查什么/对照什么，再怎么整理和判断”。
- 计划说明不要列章节标题，不要提前写大纲内容；只表达研究路线和判断方法。

隐藏 JSON 要求：
- 计划说明结束后，从单独一行 {PLAN_JSON_MARKER} 开始。
- 输出合法 JSON 对象，最后以 {PLAN_JSON_END_MARKER} 结束。
- JSON 只有 plan_text、plan_steps、chapters 三个字段。
- plan_text 与可见计划说明语义一致。
- plan_steps 是 3-7 条动作步骤，用来解释本计划会查询什么、整理什么、判断什么、如何形成大纲。
- chapters 是很初步的粗颗粒骨架，不追求完整和细节。
{chapter_count_instruction}
- 如果资料覆盖多个知识簇、任务类型或学习阶段，应在模式允许范围内主动拆细。
- 如果这是对上一版方案的修订，chapters 必须体现编辑后的完整方案；未受影响的章节保持上一版写法。

JSON 形状：
{{
  "plan_text": "一小段计划概括",
  "plan_steps": ["查询或对照什么", "归并或筛选什么", "整理什么", "形成什么"],
  "chapters": [
    {{
      "title": "高度概括的章节方向",
      "key_points": ["本章后续要继续细化的方向"]
    }}
  ]
}}

格式约束：
- JSON 段只能输出 JSON，不要放 Markdown 代码块、注释或尾随逗号。
- chapters 只写高度概括的章节方向和 key_points，不要放来源、媒体计划、构建约束或后端字段。
- chapters 数量必须服务本轮用户目标和真实学习路径；不要为了凑默认数量额外加空心章节。
- 每章标题要体现学习任务，不要只写“核心模块”“复盘安排”这类过泛标题。
- 章节标题要自然像真实课程目录，避免口号化、过度对仗或统一句式。
- 若当前规划模式为已有文档重建/调整，JSON 必须体现对已有版本的改造，而不是新建文档的泛化规划。

内容边界：
- plan_steps 可以写“查询/对照/搜集/调研”的计划动作，但不能说已经完成检索。
- plan_text 和 plan_steps 是重点，不能被 chapters 反客为主。
- 没有上传资料时，基于用户提示生成通用初步计划，不要声称读过具体文件。
- 初步大纲保持概括，key_points 控制为 2-4 个方向，不要塞满细碎知识点。
{examples_block}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_plan_composer",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(resolved_user_prompt),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history or []),
            "latest_feedback_chars": len(latest_feedback or ""),
            "material_digest_chars": len(material_context.material_digest or ""),
            "brief_chars": len(sketch),
            "plan_intent_chars": len(plan_intent_text),
            "plan_query_count": len(plan_intent.plan_queries),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=messages,
    )


def build_plan_outline_repair_messages(
    *,
    course_name: str,
    user_prompt: str | None = None,
    digest_mode: str,
    material_context: DigestMaterialContext,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
    raw_response: str,
    parse_error: str,
    message_history: list[str] | None = None,
    latest_feedback: str | None = None,
    latest_plan: dict[str, Any] | None = None,
    existing_doc_context: str | None = None,
    planner_context_mode: str = "fresh_build",
) -> list[dict[str, str]]:
    """为格式异常的计划合成结果构造结构修复提示词。

    这里仍然走大模型路径：基于流式计划合成结果修复机器合同，
    而不是用本地关键词规则臆造大纲。
    """

    resolved_user_prompt = (user_prompt or "").strip()
    sketch = planner_brief.markdown.strip() or "暂无可见规划判断"
    plan_queries = _render_plan_queries(plan_intent)
    plan_intent_text = plan_intent.plan_intent.strip() or DEFAULT_PLAN_INTENT
    mode_label = planner_mode_label(digest_mode)
    chapter_contract = render_planner_chapter_contract(digest_mode)
    feedback_text = (latest_feedback or "").strip()
    is_revision = bool(latest_plan and feedback_text)
    revision_contract = (
        f"""
上一版方案 JSON（修订源对象）：
{_render_latest_plan_json(latest_plan)}

修订方式：
- 把上一版方案 JSON 当成源对象，像编辑文档一样应用“本轮最新输入/修改意见”。
- 未被本轮修改意见影响的章节，title 和 key_points 保持原样。
- 如果用户明确要求整体重建、重新规划、重排主线或改成新的总章数，才重新划分全局章节。
- 输出的 chapters 必须是修订后的完整章节列表，不是差异列表。
""".strip()
        if is_revision
        else ""
    )
    chapter_count_instruction = (
        "chapters 数量由上一版方案应用本轮修改后自然得到；不要被默认参考章数牵引成重新规划。"
        if is_revision
        else "chapters 数量由用户目标、资料复杂度、请求模式和系统级章节规划合同共同决定；不要为了凑默认数量额外加空心章节。"
    )
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    system_prompt = f"""
你是 AITeachMe 的计划大纲结构修复器。
你只输出合法 JSON 对象，不输出 Markdown、解释、注释、代码块或额外文本。
你不能使用本地规则或关键词臆造章节；必须基于用户提示、资料上下文、内部规划意图和原始模型输出，重新生成可解析的大纲合同。
你修复后的章节是后续知识文档生成器的冻结执行合同。
如果当前任务是修订，用户本轮修改意见和上一版方案优先于默认参考章数。

{chapter_contract}
""".strip()
    prompt = f"""
上一轮计划合成模型已经输出过内容，但机器 JSON 合同解析失败。
请重新生成一个合法 JSON 对象，供后端继续构建 confirmed plan。

解析错误：
{parse_error}

主题：{course_name}
用户提示：{resolved_user_prompt}
模式：{mode_label}

资料画像：
{render_material_overview(material_context)}

资料上下文：
{render_material_digest(material_context)}

{context_mode_block}

本轮最新输入/修改意见：
{render_latest_feedback(latest_feedback)}

最近对话与修改意见：
{render_message_history(message_history)}

上一版方案：
{render_latest_plan(latest_plan)}

{revision_contract}

可见规划判断：
{sketch}

内部规划意图：
{plan_intent_text}

内部规划抓手：
{plan_queries}

上一轮原始输出：
{_clip_raw_response(raw_response)}

只输出合法 JSON，字段必须严格为：
{{
  "plan_text": "一小段计划概括",
  "plan_steps": ["查询或对照什么", "归并或筛选什么", "整理什么", "形成什么"],
  "chapters": [
    {{
      "title": "高度概括的章节方向",
      "key_points": ["本章后续要继续细化的方向"]
    }}
  ]
}}

字段要求：
1. plan_text 控制在 140-320 字，必须说明后续会如何查找、对照、整理和判断。
2. plan_steps 输出 3-7 条动作步骤，不能声称已经完成检索。
3. {chapter_count_instruction}
4. 每章 key_points 输出 2-4 条，服务后续知识文档生成器继续过大模型写正文。
5. 没有上传资料时，只能基于用户提示生成通用初步计划，不要声称读过具体文件。
6. 若当前规划模式为已有文档重建/调整，必须围绕已有版本如何改造来修复大纲。
7. 如果这是对上一版方案的修订，必须把上一版 JSON 作为源对象；未受影响的章节保持上一版写法。
8. 不要输出来源名单、网站名、论文名、后端字段、Markdown 代码块或 {PLAN_JSON_MARKER} 标记。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_plan_outline_repair",
        inputs={
            "course_name": course_name,
            "user_prompt_chars": len(resolved_user_prompt),
            "digest_mode": digest_mode,
            "message_history_count": len(message_history or []),
            "latest_feedback_chars": len(latest_feedback or ""),
            "material_digest_chars": len(material_context.material_digest or ""),
            "brief_chars": len(sketch),
            "plan_intent_chars": len(plan_intent_text),
            "plan_query_count": len(plan_intent.plan_queries),
            "raw_response_chars": len(raw_response or ""),
            "parse_error_chars": len(parse_error or ""),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=messages,
    )


__all__ = [
    "PLAN_JSON_END_MARKER",
    "PLAN_JSON_MARKER",
    "build_plan_composer_messages",
    "build_plan_outline_repair_messages",
]
