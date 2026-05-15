"""Prompts for composing planner build plans."""

from __future__ import annotations

import json
from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.planner.lib.models import PlanIntent, PlannerBrief
from app.workflows.digest.planner.lib.plans import planner_mode_label, render_planner_chapter_contract
from app.workflows.digest.planner.prompts.context import (
    render_latest_feedback,
    render_latest_plan,
    render_material_digest,
    render_material_overview,
    render_message_history,
    render_planner_context_mode,
)

DEFAULT_PLAN_INTENT = "围绕用户提示和资料主线，先整理资料边界，再生成可调整的初步大纲。"
REPLACE_EXISTING_OUTLINE_MODE = "replace_existing_outline"
COURSE_CATALOG_TITLE_CONTRACT = """
章节标题合同：
- title 是课程目录标题，不是学习策略句；它应该像讲义/教材里的课时主题，优先写具体知识对象、方法主题或题型主题。
- key_points 才写学习动作、练习方式、易错边界和题型处理；不要把这些动作压进 title。
- 对线性代数这类完整课程，优先按标准课时或教材边界拆分，例如行列式、矩阵、初等变换、向量、线性方程组、特征值、二次型这类可直接上课的主题；速成模式只影响取舍和 key_points 密度，不把标题改成抽象能力标签。
- 对窄范围专题，title 仍然是该专题内部的目录主题，例如适用条件、公式结构、计算方法、典型题型、易错边界；不要扩展成整门课。
- 标题语义必须来自大模型对用户目标、资料画像和上下文的综合判断；本地代码不会做关键词提取、规则截取或规则补标题。
""".strip()


def _render_plan_queries(plan_intent: PlanIntent) -> str:
    queries = [item.strip() for item in plan_intent.plan_queries if item.strip()]
    if not queries:
        return "- 暂无明确规划抓手"
    return "\n".join(f"- {item}" for item in queries)


def _render_structured_intent(plan_intent: PlanIntent) -> str:
    preferences = [item.strip() for item in plan_intent.content_preferences if item.strip()]
    options = [item.strip() for item in plan_intent.adjustment_options if item.strip()]
    change_mode = plan_intent.plan_change_mode.strip()
    target_scope = plan_intent.target_scope.strip()
    scope_decision = plan_intent.scope_decision.strip()
    chapter_count_guidance = plan_intent.chapter_count_guidance.strip()
    requested_chapter_count = plan_intent.requested_chapter_count
    split_guidance = plan_intent.chapter_split_guidance.strip()
    lines: list[str] = []
    if change_mode:
        lines.extend(["计划变更模式：", f"- {change_mode}"])
    if target_scope:
        lines.extend(["本轮目标范围：", f"- {target_scope}"])
    if scope_decision:
        lines.extend(["范围判断：", f"- {scope_decision}"])
    if requested_chapter_count is not None:
        lines.extend(["用户指定章节数：", f"- {requested_chapter_count}"])
    if chapter_count_guidance:
        lines.extend(["章节数量/颗粒度判断：", f"- {chapter_count_guidance}"])
    if preferences:
        lines.extend(["用户内容偏好判断：", *[f"- {item}" for item in preferences]])
    if split_guidance:
        lines.extend(["章节边界判断：", f"- {split_guidance}"])
    if options:
        lines.extend(["意图识别给出的用户调整引导：", *[f"- {item}" for item in options]])
    return "\n".join(lines).strip() or "- 暂无额外结构化判断"


def _is_replacement_revision(plan_intent: PlanIntent) -> bool:
    return plan_intent.plan_change_mode.strip() == REPLACE_EXISTING_OUTLINE_MODE


def _render_latest_plan_json(latest_plan: dict[str, Any] | None) -> str:
    if not latest_plan:
        return "{}"
    return json.dumps(latest_plan, ensure_ascii=False, indent=2)


def _render_task_chapter_contract(*, digest_mode: str, is_revision: bool, is_replacement_revision: bool) -> str:
    if not is_revision:
        return render_planner_chapter_contract(digest_mode)
    if is_replacement_revision:
        return "\n".join(
            [
                "范围重定向学习大纲：",
                "- 本轮不是在上一版方案上做局部补丁，而是把上一版完整替换成新的 target_scope 方案。",
                "- 上一版方案 JSON 只能作为上下文和被替换对象，不得继承旧章节、旧标题或旧 required_elements。",
                "- chapters 必须围绕本轮 target_scope 重新生成完整列表；旧方案中不属于 target_scope 的章节必须消失。",
                "- 如果 requested_chapter_count 非空，chapters 数量必须严格等于该数字。",
                "- 每章标题必须像课程目录，直接体现 target_scope 内部的一个知识主题、方法主题、题型主题或易错边界。",
            ]
        )
    return "\n".join(
        [
            "修订学习大纲：",
            "- 上一版方案 JSON 是本轮 chapters 的源对象，先按它的章节顺序、标题和 required_elements/key_points 建立工作副本。",
            "- 上一版 JSON 的 chapter_plan[].required_elements 对应本轮输出 chapters[].key_points。",
            "- 本轮最新输入/修改意见是作用在工作副本上的最小补丁；仅当 plan_change_mode=patch_existing 时使用本合同。",
            "- 未被本轮修改意见影响的章节必须原样保留 title 和 required_elements/key_points，顺序也保持不变。",
            "- 如果本轮是在调整重点、偏向或主要讲某些主题，被强调主题的相关章节、低优先级章节和综合复盘都属于受影响对象；必须通过章节顺序、章节取舍或 key_points 改写体现变化，不能只改 plan_text。",
            "- 如果本轮语义是在移除某个章节或内容，只移除被指向的对象；不要把被移除对象的内容吸收到其他章节，除非用户明确要求保留或融入。",
            "- 如果本轮使用相对位置、序号或代称指向章节，必须以上一版 JSON 的章节列表为定位依据。",
            "- 不要因为 sprint/systematic 的默认参考章数而自动压缩、扩展、合并或重排章节。",
        ]
    )


def _render_revision_contract(latest_plan: dict[str, Any] | None, *, is_replacement_revision: bool) -> str:
    if is_replacement_revision:
        return f"""
上一版方案 JSON（仅作为被替换对象和上下文）：
{_render_latest_plan_json(latest_plan)}

范围重定向方式：
- 本轮 plan_change_mode=replace_existing_outline，表示用户要把当前方案改成一个新范围的完整大纲。
- 不要保留上一版未提到的章节；不要把旧章节当成必须保留的工作副本。
- 先按 target_scope 和 requested_chapter_count 重新划分章节，再检查是否仍有旧方案内容混入。
- 输出的 chapters 是替换后的完整章节列表，不是差异列表。
""".strip()
    return f"""
上一版方案 JSON（修订源对象）：
{_render_latest_plan_json(latest_plan)}

修订方式：
- 把上一版方案 JSON 当成唯一源对象，像编辑文档一样应用“本轮最新输入/修改意见”。
- 先定位本轮修改实际影响哪些章节、字段或排序，再输出应用补丁后的完整 chapters。
- 上一版 JSON 的 chapter_plan[].required_elements 对应本轮输出 chapters[].key_points。
- 未被影响的章节，title 和 required_elements/key_points 必须和上一版保持一致。
- 如果用户要求“主要讲/更偏/重点放”某些主题，不能只在 plan_text 宣称重心变化；必须让 chapters 的顺序、章节取舍或相关 key_points 可见地反映新重点。
- 如果用户只是删除、弱化或不要某个对象，不要擅自把它合并到其他章节；删除就是从修订后结果中消失。
- 只有用户明确要求整体重建、重新规划、重排主线或改变整份方案总量时，才重新划分全局章节。
- 输出的 chapters 必须是修订后的完整章节列表，不是差异列表。
""".strip()


def build_plan_visible_messages(
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
    """Build the user-visible streaming plan prompt.

    The machine outline is generated by ``build_plan_structured_messages`` via
    the structured LLM path. This stream is only for user-facing guidance.
    """

    resolved_user_prompt = (user_prompt or "").strip()
    sketch = planner_brief.markdown.strip() or "暂无可见规划判断"
    plan_queries = _render_plan_queries(plan_intent)
    structured_intent = _render_structured_intent(plan_intent)
    plan_intent_text = plan_intent.plan_intent.strip() or DEFAULT_PLAN_INTENT
    mode_label = planner_mode_label(digest_mode)
    feedback_text = (latest_feedback or "").strip()
    is_revision = bool(latest_plan and feedback_text)
    is_replacement_revision = is_revision and _is_replacement_revision(plan_intent)
    sketch_instruction = (
        "注意：上面的“可见规划判断”来自更早的并行思考流。如果它和“结构化用户意图判断”冲突，"
        "必须以结构化用户意图判断为准；不要复述其中关于保留旧章节、局部收缩或最小补丁的冲突表述。"
        if is_replacement_revision
        else "上面的“可见规划判断”可作为说明素材，但仍必须服从本轮最新输入和结构化用户意图判断。"
    )
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    visible_output_rules = (
        "\n".join(
            [
                "- 只输出一段自然语言，不要标题、编号、项目符号或 JSON。",
                "- 控制在 140-260 字，重点说明如何识别本轮目标范围并生成替换后的完整大纲。",
                "- 明确说明上一版旧章节会被新范围替换，不要说会保留未改章节。",
                "- 可以自然提示用户后续能继续调整哪些方向，但不要要求必须回答后才能继续。",
            ]
        )
        if is_replacement_revision
        else "\n".join(
            [
                "- 只输出一段自然语言，不要标题、编号、项目符号或 JSON。",
                "- 控制在 140-260 字，重点说明如何定位上一版方案、应用本轮修改、保留未改部分。",
                "- 可以自然提示用户后续能继续调整哪些方向，但不要要求必须回答后才能继续。",
            ]
        )
        if is_revision
        else "\n".join(
            [
                "- 只输出一段自然语言，不要标题、编号、项目符号或 JSON。",
                "- 控制在 140-320 字，重点说明你如何理解用户想学什么、优先覆盖什么、章节边界可怎样调整。",
                "- 可以自然提示用户后续能继续调整深浅、章节数、例题密度或考试/体系取向。",
            ]
        )
    )
    system_prompt = """
你是 AITeachMe 的用户可见计划说明生成器。
你只负责输出给用户看的规划说明，不输出 JSON、代码块、后端字段或机器合同。
规划说明必须来自你对用户目标、资料画像、最近对话和内部规划意图的综合判断，不做本地规则摘取片段。
最新用户输入/本轮修改意见优先于课程名和模式；如果内部规划意图锁定了具体目标范围，说明必须围绕该范围，不要扩展成整门课。
""".strip()
    prompt = f"""
请生成本轮构建计划的用户可见说明。

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

可见规划判断：
{sketch}

可见规划判断使用规则：
{sketch_instruction}

内部规划意图：
{plan_intent_text}

内部规划抓手：
{plan_queries}

结构化用户意图判断：
{structured_intent}

输出要求：
{visible_output_rules}
- 如果“结构化用户意图判断”中有具体本轮目标范围，第一句必须明确说出会围绕这个范围规划，而不是围绕课程名泛化。
- 如果这个目标范围是具体知识点/方法/题型，说明里要自然提示会把它拆成若干学习角度；如果是否扩展到前置知识不确定，只作为可调整问题提出，不要默认扩展。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_visible_plan_composer",
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
            "content_preference_count": len(plan_intent.content_preferences),
            "adjustment_option_count": len(plan_intent.adjustment_options),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
            "is_replacement_revision": is_replacement_revision,
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=messages,
    )


def build_plan_structured_messages(
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
    """Build the structured machine outline prompt.

    This path is the authoritative plan contract and is consumed through the
    infra ``response_model`` structured-output helper.
    """

    resolved_user_prompt = (user_prompt or "").strip()
    sketch = planner_brief.markdown.strip() or "暂无可见规划判断"
    plan_queries = _render_plan_queries(plan_intent)
    structured_intent = _render_structured_intent(plan_intent)
    plan_intent_text = plan_intent.plan_intent.strip() or DEFAULT_PLAN_INTENT
    mode_label = planner_mode_label(digest_mode)
    feedback_text = (latest_feedback or "").strip()
    is_revision = bool(latest_plan and feedback_text)
    is_replacement_revision = is_revision and _is_replacement_revision(plan_intent)
    chapter_contract = _render_task_chapter_contract(
        digest_mode=digest_mode,
        is_revision=is_revision,
        is_replacement_revision=is_replacement_revision,
    )
    revision_contract = (
        _render_revision_contract(latest_plan, is_replacement_revision=is_replacement_revision)
        if is_revision
        else ""
    )
    requested_chapter_count = plan_intent.requested_chapter_count
    chapter_count_instruction = (
        f"chapters 数量必须严格等于用户指定的 {requested_chapter_count} 章；不要多一章，也不要少一章。"
        if is_replacement_revision and requested_chapter_count is not None
        else "chapters 数量必须服务 target_scope 的自然拆分；不要继承上一版章数，也不要保留旧章节。"
        if is_replacement_revision
        else
        "chapters 数量必须等于上一版章节列表应用本轮最小补丁后的自然结果；不要被默认参考章数牵引成重新规划。"
        if is_revision
        else "chapters 数量由用户目标、资料复杂度、请求模式和系统级章节规划合同共同决定；不要为了凑默认数量额外加空心章节。"
    )
    plan_text_requirement = (
        "plan_text 控制在 140-260 字，说明本轮会把上一版替换为 target_scope 的完整大纲，并按用户指定章数或自然颗粒度拆分；不要写成保留旧章节的局部修订。"
        if is_replacement_revision
        else
        "plan_text 控制在 140-260 字，说明如何基于上一版 JSON 定位修改对象、应用本轮补丁并校验未改章节；不要写成从零重建路线。"
        if is_revision
        else "plan_text 控制在 140-320 字，说明你如何理解用户目标、优先内容、章节边界和可调整方向。"
    )
    plan_steps_requirement = (
        "plan_steps 输出 3-7 条范围重定向检查动作，必须包含识别新 target_scope、丢弃无关旧章节、按指定章数拆分、检查章节是否都围绕新范围。"
        if is_replacement_revision
        else
        "plan_steps 输出 3-7 条修订检查动作，不能声称已经读取未完成资料、确定证据来源或完成正文生成，也不能提出未被用户要求的全局重排。"
        if is_revision
        else "plan_steps 输出 3-7 条规划判断和调整抓手，说明目标判断、内容取舍、章节边界、可调整方向和形成大纲的检查动作。"
    )
    context_mode_block = render_planner_context_mode(
        planner_context_mode=planner_context_mode,
        existing_doc_context=existing_doc_context,
    )
    system_prompt = f"""
你是 AITeachMe 的机器可解析计划大纲生成器。
你只输出满足 response_model 的结构化结果，不输出 Markdown、解释、代码块、后端字段或额外文本。
所有用户意图、章节边界、标题取舍和引导问题都必须来自大模型对上下文的综合判断，不使用本地规则摘取片段。
如果当前任务是修订，用户本轮修改意见和上一版方案优先于默认参考章数。
最新用户输入/本轮修改意见的优先级最高；课程名、资料标题和 digest_mode 只能提供背景，不能覆盖用户刚刚说出的具体学习范围。
给用户看的可调整问题已经由上游 PlanIntent.adjustment_options 生成，本结构化大纲只负责 plan_text、plan_steps 和 chapters。

{chapter_contract}
""".strip()
    prompt = f"""
请生成本轮可确认的构建计划合同。

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

结构化用户意图判断：
{structured_intent}

优质突击课目录参考原则：
- 参考蜂考这类应试讲义的目录颗粒度：常见结构是课时主题 -> 考点/重要程度/常见题型 -> 典型题步骤 -> 练习巩固；学习这种“先定考点任务，再给方法和题型”的组织方式。
- 章节边界优先按「课程主题/考点簇/题型簇/解法方法/易错诊断/综合应用」划分，标题直接告诉学生这一章讲什么主题。
- 只是学习其规划方法和标题可读性，不能照抄资料原文、题目或目录。
- 若用户要求围绕同一知识点分多章，要按不同教学视角拆开，例如直观动机、定义边界、关键方法、例题应用、易错诊断、综合迁移。

{COURSE_CATALOG_TITLE_CONTRACT}

范围优先级：
- 如果“本轮目标范围”是一个具体知识点、方法、定理、公式、题型或章节主题，所有 chapters 都必须围绕这个范围展开；不要生成整门课程或相邻大章节。
- 例如用户要“洛必达法则的章节”，自然大纲应拆成洛必达法则的适用条件、不定式识别、求极限步骤、连续使用与等价替换边界、易错诊断和典型题训练等角度，而不是生成“极限、导数、积分”的通用高数路线。
- 例如用户要“定积分的 5 个章节”，chapters 必须是 5 章且全部围绕定积分，可拆成定义与几何意义、性质与可积条件、基本定理和换元/分部、典型计算题、面积/应用与易错诊断等角度；不能保留极限、导数、级数、多元微分等旧章节。
- 前置知识只能作为某章 key_points 的必要背景出现；除非用户明确要求扩展，不能把前置知识升级成独立主线章节。
- 如果你认为用户可能想扩展到前置/后续内容，应服从上游 PlanIntent.adjustment_options 中的引导；本结构化结果不要另造新的调整问题字段。

字段要求：
1. {plan_text_requirement}
2. {plan_steps_requirement}
3. {chapter_count_instruction}
4. 每章 title 必须是让人一眼看懂的课程目录标题；每章 key_points 输出 2-4 条，服务后续知识文档生成器继续过大模型写正文。
5. chapters 只写课程骨架和 key_points，不要放来源、媒体计划、后端字段、已读取未完成资料、已确定证据来源或已生成正文的表述。
6. 没有上传资料时，只能基于用户提示生成通用初步计划，不要声称读过具体文件。
7. 若当前规划模式为已有文档重建/调整，必须围绕已有版本如何改造来生成大纲。
8. 如果这是 patch_existing 修订，必须把上一版 JSON 作为源对象；上一版 chapter_plan[].required_elements 对应输出 chapters[].key_points，未受影响的章节保持上一版写法，不要吸收被移除对象的内容；如果本轮是在调整重点，不能只改 plan_text，chapters 也必须体现权重、顺序、取舍或 key_points 的变化。
9. 如果这是 replace_existing_outline 修订，上一版 JSON 只作为被替换对象；输出必须是替换后的新完整大纲，不保留无关旧章节。
10. JSON 字符串里不要使用未转义的英文双引号；引用术语时用中文引号「」或直接改写。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "planner_structured_plan_composer",
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
            "content_preference_count": len(plan_intent.content_preferences),
            "adjustment_option_count": len(plan_intent.adjustment_options),
            "has_latest_plan": latest_plan is not None,
            "is_revision": is_revision,
            "is_replacement_revision": is_replacement_revision,
            "requested_chapter_count": requested_chapter_count,
            "planner_context_mode": planner_context_mode,
            "existing_doc_context_chars": len(existing_doc_context or ""),
        },
        output=messages,
    )


def build_plan_structured_count_retry_messages(
    *,
    course_name: str,
    user_prompt: str | None = None,
    digest_mode: str,
    material_context: DigestMaterialContext,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
    previous_outline: dict[str, Any],
    required_chapter_count: int,
    message_history: list[str] | None = None,
    latest_feedback: str | None = None,
    latest_plan: dict[str, Any] | None = None,
    existing_doc_context: str | None = None,
    planner_context_mode: str = "fresh_build",
) -> list[dict[str, str]]:
    messages = build_plan_structured_messages(
        course_name=course_name,
        user_prompt=user_prompt,
        digest_mode=digest_mode,
        material_context=material_context,
        planner_brief=planner_brief,
        plan_intent=plan_intent,
        message_history=message_history,
        latest_feedback=latest_feedback,
        latest_plan=latest_plan,
        existing_doc_context=existing_doc_context,
        planner_context_mode=planner_context_mode,
    )
    retry_prompt = f"""
上一轮结构化大纲违反了用户明确指定的章节数量，请重新生成完整结构化结果。

必须严格满足：
- chapters 数量等于 {required_chapter_count}。
- 每一章都围绕 target_scope，不保留无关旧章节。
- 每章 title 仍必须遵守课程目录标题合同，不能写成学习策略句或抽象能力标签。
- 不输出解释、Markdown 或额外文本，只输出 response_model 需要的结构化结果。

{COURSE_CATALOG_TITLE_CONTRACT}

上一轮错误输出：
{json.dumps(previous_outline, ensure_ascii=False, indent=2)}
""".strip()
    return [*messages, {"role": "user", "content": retry_prompt}]


__all__ = [
    "build_plan_structured_messages",
    "build_plan_structured_count_retry_messages",
    "build_plan_visible_messages",
]
