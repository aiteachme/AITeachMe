"""Prompt builders for DocGen generation-time support."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.presentation_policy import build_presentation_contract_prompt
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def _bullet_lines(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _chapter_shape_hint(*, digest_mode: str) -> str:
    profile = get_docgen_mode_profile(digest_mode)
    return f"""
可参考的{profile.prompt_label}讲义写作关注点，不是固定目录：
{_bullet_lines(profile.chapter_format)}

可参考的课程化节奏，不要求逐条出现：
{_bullet_lines(profile.course_flow_hints)}

例题/练习可以优先采用这些方向：
{_bullet_lines(profile.practice_focuses)}
""".strip()


def _opening_structure_instruction(*, digest_mode: str) -> str:
    profile = get_docgen_mode_profile(digest_mode)
    if profile.is_sprint:
        return "一级标题后给考点速览表，列考点、重要程度、题型或任务场景、抓手；正文按 `## 01 短考点名` 推进"
    return "一级标题后给 3-5 行导航表；正文按 `## 01 具体知识点名` 推进"


def _section_shape_instruction(*, digest_mode: str) -> str:
    profile = get_docgen_mode_profile(digest_mode)
    if profile.is_sprint:
        return "小节内部按规则抓手、公式/步骤、题目或任务、解/答案、易错点组织"
    return "小节内部用加粗字段组织解释、条件/步骤、例题/任务、解析、答案/结论、易错点"


def _presentation_contract(*, digest_mode: str = "") -> str:
    return build_presentation_contract_prompt(digest_mode=digest_mode)


def _build_mode_contract(
    *,
    digest_mode: str,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
) -> str:
    profile = get_docgen_mode_profile(digest_mode)
    chapter_specific = ""
    if chapter_index == 1:
        chapter_specific = profile.prompt_opening_guidance
    elif chapter_count and chapter_index == chapter_count:
        chapter_specific = profile.prompt_closing_guidance
    extra_contract = f"\n{profile.prompt_extra_contract}" if profile.prompt_extra_contract else ""
    return f"""
文档模式：{profile.prompt_label}。
写作优先级：{profile.prompt_priority}。
关注点：{"；".join(profile.chapter_format)}。
章节结构：{_opening_structure_instruction(digest_mode=profile.mode)}。
小节标题聚焦本章知识对象、方法、任务或场景；{_section_shape_instruction(digest_mode=profile.mode)}。
三级标题只用于同一知识点下的并列子主题。{extra_contract}
{chapter_specific}
""".strip()


def build_docgen_writer_messages(
    *,
    title: str,
    objective: str,
    digest_mode: str,
    required_elements: list[str],
    writing_instructions: str,
    source_count: int,
    dense_context: str,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
    execution_contract: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    """构造章节 writer 提示词。

    Writer prompt 消费上游已经准备好的 dense_context 和章节执行合同，不在
    prompt builder 里静默截断材料。资产、练习和来源统一由后续节点处理。
    """

    mode_profile = get_docgen_mode_profile(digest_mode)
    normalized_mode = mode_profile.mode
    mode_label = mode_profile.prompt_label
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    execution_contract = dict(execution_contract or {})
    practice_quota = dict(execution_contract.get("practice_quota") or {})
    content_role_targets = dict(execution_contract.get("content_role_targets") or {})
    example_coverage_plan = list(execution_contract.get("example_coverage_plan") or [])
    chapter_end_practice_plan = list(execution_contract.get("chapter_end_practice_plan") or [])
    content_mix_policy = dict(execution_contract.get("content_mix_policy") or {})
    coverage_policy = [
        str(item).strip()
        for item in list(execution_contract.get("coverage_policy") or [])
        if str(item).strip()
    ]
    example_density_policy = dict(execution_contract.get("example_density_policy") or {})
    claim_targets = [
        str(item).strip()
        for item in list(execution_contract.get("claim_targets") or [])
        if str(item).strip()
    ]
    conflict_warnings = [
        str(item).strip()
        for item in list(execution_contract.get("conflict_warnings") or [])
        if str(item).strip()
    ]
    learner_profile = str(execution_contract.get("learner_profile") or "").strip()
    forbidden_scope = [
        str(item).strip()
        for item in list(execution_contract.get("forbidden_scope") or [])
        if str(item).strip()
    ]
    profile_density = dict(mode_profile.example_density_policy)
    min_worked_examples = _positive_int(
        practice_quota.get("worked_examples") or profile_density.get("worked_examples_per_chapter"),
        default=4,
    )
    short_practice_quota = _positive_int(
        practice_quota.get("practice_tasks") or profile_density.get("practice_tasks_per_chapter"),
        default=4,
    )
    activity_quota = _positive_int(
        practice_quota.get("learning_activities") or profile_density.get("total_learning_activities_per_chapter"),
        default=min_worked_examples + short_practice_quota,
    )
    training_min_examples = _positive_int(profile_density.get("training_chapter_min_examples"), default=6)
    concept_min_examples = _positive_int(profile_density.get("concept_chapter_min_examples"), default=2)
    chapter_end_min_tasks = _positive_int(
        practice_quota.get("chapter_end_min_tasks") or profile_density.get("chapter_end_practice_min_tasks"),
        default=2,
    )
    chapter_end_max_tasks = max(
        chapter_end_min_tasks,
        _positive_int(
            practice_quota.get("chapter_end_max_tasks") or profile_density.get("chapter_end_practice_max_tasks"),
            default=max(4, chapter_end_min_tasks),
        ),
    )
    sprint_problem_contract = ""
    if mode_profile.is_sprint:
        sprint_problem_contract = f"""
练习组织原则：
- 按章节角色选择组织方式：概念章用短例子和反例，方法章用步骤和检查点，训练章按真实题型或任务差异分组。
- 学习活动目标：训练型约 {training_min_examples} 个，普通方法章至少 {min_worked_examples} 个，概念章至少 {concept_min_examples} 个；完整活动含题目/任务、解析、答案/结论、易错点。
- 正文知识点内安排必要例题、短检查和变式；章末单元测试由后续专门节点生成。
""".strip()
    contract_summary = (
        f"- 目标字数：{execution_contract.get('target_word_count') or '未指定'}\n"
        f"- 最低字数：{execution_contract.get('min_word_count') or '未指定'}\n"
        f"- 最低覆盖分：{execution_contract.get('min_coverage_score') or '未指定'}\n"
        f"- 最低证据支撑：{execution_contract.get('min_evidence_support') or '未指定'}\n"
        f"- 解释深度：{execution_contract.get('explanation_depth') or '未指定'}\n"
        f"- 图示写作：正文写清变量、对象位置、图形关系和图注；静态图节点负责绘制 SVG\n"
        f"- 练习目标：学习活动约 {activity_quota} 个；完整例题/案例 {min_worked_examples} 个；短练习/自测/变式约 {short_practice_quota} 个\n"
        f"- 例题密度：{example_density_policy.get('policy_text') or '例题、案例和任务服务当前知识点。'}\n"
        f"- 内容角色目标：{content_role_targets}\n"
        f"- 例题覆盖计划：{example_coverage_plan}\n"
        f"- 章末单元测试计划：{chapter_end_practice_plan}（供后续专门节点使用，正文写作阶段只生成知识正文）\n"
        f"- 覆盖检查策略：{'；'.join(coverage_policy) if coverage_policy else '按学习大纲覆盖核心知识和例题。'}\n"
        f"- 本章主张目标：{'；'.join(claim_targets) if claim_targets else '按学习大纲覆盖'}\n"
        f"- 学习者画像参考：{learner_profile or '暂无画像；按用户目标和资料本身写作'}\n"
        f"- 本章边界外主题：{'；'.join(forbidden_scope) if forbidden_scope else '无显式边界外主题'}\n"
        f"- 需谨慎处理的冲突/低证据点：{'；'.join(conflict_warnings) if conflict_warnings else '无'}"
    )
    system_prompt = """
你是 AITeachMe 的中文教学文档作者。
输出学生可直接阅读的中文 Markdown 讲义：清楚、可信、可复习。
内容来自研究材料和本章执行合同；材料不足时稳健整理，不编造来源事实。
章节讲清概念、条件、方法、例题/任务、检查点和易错边界。
""".strip()
    user_prompt = f"""
请只输出本章的中文 Markdown 正文，不要输出解释，不要输出代码块外的多余说明。

章节标题：{title}
学习目标：{objective or "把本章最核心的知识主线讲清楚。"}
文档模式：{mode_label}
必须覆盖：{required_text}
可用来源数量：{source_count}
额外写作要求：{writing_instructions or "保持教学导向，强调理解路径与复习价值。"}

模式参考：
{_build_mode_contract(digest_mode=normalized_mode, chapter_index=chapter_index, chapter_count=chapter_count)}

执行合同：
{contract_summary}

写作口径：
1. 只输出本章中文 Markdown 正文，以 `# {title}` 开头。
2. {_opening_structure_instruction(digest_mode=normalized_mode)}；章末测试由后续专门节点追加。
3. 每个知识点小节讲清对象、条件/边界、处理路径、例题/任务、答案/结论和易错点/检查点。
4. 例题、案例、变式训练和自测贴合本章材料；每个可判断任务给解析、答案或判定依据。
5. 执行合同中的“本章边界外主题”只作必要前后联系，不扩写成独立小节。
6. 学习者画像只调整解释节奏、练习密度和易错提醒。
7. 需要图形辅助时，正文写清题设、变量、图形关系和图注；静态图示节点会绘制 SVG。代码块只用于代码、命令或伪代码。

版式合同：
{_presentation_contract(digest_mode=normalized_mode)}

{sprint_problem_contract}

参考写作路径：
{_chapter_shape_hint(digest_mode=normalized_mode)}

输出要求：
1. 只输出中文 Markdown。
2. 一级标题必须是 `# {title}`。
3. 本阶段只写知识点内的例题、变式和检查点。
4. 只写学生可见正文；不输出内部协议、调试信息、来源附录、草稿痕迹、HTML 注释或未渲染占位内容。

研究材料：
{dense_context}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_writer",
        inputs={
            "title": title,
            "digest_mode": digest_mode,
            "required_count": len(required_elements),
            "source_count": source_count,
            "dense_context_chars": len(dense_context),
            "chapter_index": chapter_index,
            "chapter_count": chapter_count,
        },
        output=messages,
    )


def build_docgen_heading_repair_messages(
    *,
    title: str,
    objective: str,
    digest_mode: str,
    required_elements: list[str],
    writing_instructions: str,
    source_count: int,
    markdown: str,
    dense_context: str,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
) -> list[dict[str, str]]:
    mode_profile = get_docgen_mode_profile(digest_mode)
    normalized_mode = mode_profile.mode
    mode_label = mode_profile.prompt_label
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    system_prompt = """
你是 AITeachMe 的教学编辑助手。
你的任务不是重写整章主题，而是在保留原有内容价值和文风的前提下，修复章节的二级、三级标题与结构组织。
标题要自然、具体、像真实中文讲义；参考结构只能帮助判断缺口，不能变成固定模板。
修订目标是让它更像可读的课程讲义，而不是研究草稿、内部整理记录或套格式的提纲。
标题应是内容名词短语，而不是学习动作口号、问答提示或内部修补口吻。
标题只表达语义，不承担编号或样式说明。
""".strip()
    # 标题修复只需要局部参考；完整正文和完整研究上下文仍保留在 state/manifest。
    user_prompt = f"""
请把下面这一章 Markdown 修订成“标题和结构更清楚，但仍保持原有教学内容”的版本。
章节标题：{title}
学习目标：{objective or "把本章最核心的知识主线讲清楚"}
文档模式：{mode_label}
必须覆盖：{required_text}
可用来源数量：{source_count}
额外写作要求：{writing_instructions or "保持教学导向，优先让结构更清楚"}
章节位置：第 {chapter_index or 1} 章 / 共 {chapter_count or '?'} 章

模式参考：
{_build_mode_contract(digest_mode=normalized_mode, chapter_index=chapter_index, chapter_count=chapter_count)}

输出要求：
1. 只输出修订后的完整中文 Markdown。
2. 一级标题必须保持为 `# {title}`。
3. 可以重命名、合并或降级标题；孤立三级标题要并入更具体的 `##`，或改成正文加粗小节。
4. 标题要来自本章知识对象、方法、任务/题型或应用场景；不要套固定表头。
5. 如果原文存在泛化目录标题、学习动作标题、内部检查标题、序号占位题型或证据整理标题，必须按小节正文改成具体内容名，或合并进相邻小节；不要保留这些标签当目录标题。
6. 保留已有正文、例子、公式和重点提示块的学习价值，只删除重复、跑题、草稿痕迹、原始来源清单和内部调试信息。
7. 只在结构确实不完整时补少量过渡句、总结句或提示句；不能凭空编造来源事实，不能改变公式和代码字面量的原意。

写作口径：
表达要像真实中文教学讲义：清楚、克制、可信、面向学习，不写聊天回复、鸡汤或内部草稿。
版式口径：
{_presentation_contract(digest_mode=normalized_mode)}
如果正文已有例题、案例或任务区，要保留“题目/案例、解析、易错点”这类学习价值，不要改成只有列表。

参考写作路径，不要照抄为目录：
{_chapter_shape_hint(digest_mode=normalized_mode)}

可参考但不要照抄的研究线索：
{dense_context or "暂无额外研究线索，请主要整理现有正文结构。"}

当前 Markdown：
{markdown}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_heading_repair",
        inputs={
            "title": title,
            "digest_mode": digest_mode,
            "required_count": len(required_elements),
            "markdown_chars": len(markdown),
            "dense_context_chars": len(dense_context),
            "chapter_index": chapter_index,
            "chapter_count": chapter_count,
        },
        output=messages,
    )


def build_docgen_research_purify_messages(
    *,
    dense_context: str,
    chapter_title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
) -> list[dict[str, str]]:
    must_cover = "、".join(required_elements) if required_elements else "与本章最相关的核心知识"
    profile = get_docgen_mode_profile(digest_mode)
    normalized_mode = profile.mode
    mode_label = profile.prompt_label
    system_prompt = """
你是 AITeachMe 的研究整理助手。
你的任务是把杂乱素材提纯成适合章节写作使用的中文研究笔记。
你不能补充素材里没有的事实，也不能把研究笔记写成最终讲义正文。
""".strip()
    user_prompt = f"""
请把下面的研究素材提纯成“供章节写作直接使用”的中文研究笔记。

章节标题：{chapter_title or "本章内容"}
章节目标：{objective or "为本章提供可教学、可解释、可举例的可靠材料。"}
文档模式：{mode_label}
必须覆盖：{must_cover}

输出要求：
1. 只保留和本章直接相关的信息。
2. 优先保留定义、公式、推理线索、典型例子、来源线索。
3. 删除空话、重复段落和无关背景。
4. 输出应是中文 Markdown 研究笔记，不是最终成稿。
5. 不能补充素材中没有出现的事实。
6. 本模式优先保留：{profile.prompt_research_focus}。

原始素材：
{dense_context}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_research_purify",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "required_count": len(required_elements),
            "dense_context_chars": len(dense_context),
        },
        output=messages,
    )


def build_docgen_mermaid_prompt(*, topic: str, context: str) -> str:
    prompt = f"""
请根据下面内容生成一段干净、可渲染的 Mermaid 语法。

要求：
1. 只返回 Mermaid 代码，不要解释，不要加 Markdown 代码块。
2. 默认使用 `mindmap`；如果内容是前置依赖、流程、因果、方法步骤或概念关系，优先使用 `flowchart LR`。
3. 如果使用 mindmap，根节点必须是主题本身；最多 3 层结构，保证清晰，不要过密。
4. 节点文字优先用中文短语，单个节点尽量控制在 4 到 12 个字。
5. 不要在节点里放公式、比较符号（>、<、=）、HTML、Markdown 链接、代码符号、英文引号或复杂括号嵌套；如果必须表达公式关系，请改写成中文短语。
6. 如果使用 flowchart，可以用 2-3 个简单 `classDef` 给核心概念、方法步骤、易错提醒区分颜色；不要使用 click、HTML、复杂 style 或外链。
7. 如果上下文噪声很多，优先保留最核心的 3 到 6 个概念节点，宁可简洁也不要产出脏 Mermaid。
8. 绝对不要复制上下文中的 Markdown 标题、正文段落、`---` 分隔线或反引号。

主题：{topic}
上下文：{context}
""".strip()
    return trace_prompt_build(
        "docgen_mermaid",
        inputs={"topic": topic, "context_chars": len(context)},
        output=prompt,
    )


def build_docgen_sub_query_messages(
    *,
    query: str,
    context_summary: list[dict[str, str]],
    max_queries: int,
    domain: str,
) -> list[dict[str, str]]:
    context_lines = "\n".join(
        f"- {item['text']}"
        for item in context_summary
        if str(item.get("text") or "").strip()
    ) or "- 当前没有额外上下文"
    system_prompt = """
你是 AITeachMe 的研究规划助手。
你的任务是把单个教学主题拆成可检索、可抓取、可用于知识整理的中文子查询。
查询要服务后续写作和证据补强，不要生成空泛口号。
""".strip()
    user_prompt = f"""
请围绕下面这个教学章节主题，拆解出更适合后续检索和抓取的研究子查询。

主题：{query}
领域：{domain}
最多输出：{max_queries} 条

已有线索：
{context_lines}

输出要求：
1. 只输出适合中文搜索引擎或知识库检索的查询语句。
2. 查询要彼此互补，不要只是同义改写。
3. 优先覆盖：核心定义、推导/公式、应用案例/例题、易错点/常见误区。
4. 如果主题更偏系统节奏，可适当补“前置知识”“适用条件”“概念关系”。
5. 如果主题更偏紧凑节奏，可适当补“真实任务/真实案例”“常见任务/高频题型”“防坑提醒”；只有材料明确包含考试或真题时才使用“真题”措辞。
6. 所有查询必须使用中文。
7. 如果你判断信息不足，也请尽量基于主题稳健拆解，不要返回空列表。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_sub_queries",
        inputs={
            "query": query,
            "domain": domain,
            "max_queries": max_queries,
            "context_count": len(context_summary),
        },
        output=messages,
    )


def build_docgen_gap_query_messages(
    *,
    dense_context: str,
    required_elements: list[str],
    max_queries: int = 2,
    domain: str = "education",
) -> list[dict[str, str]]:
    must_cover = "、".join(required_elements) if required_elements else "与本章最相关的核心知识"
    system_prompt = """
你是 AITeachMe 的研究分析引擎。
你的任务是检查现有研究素材的知识盲区，并生成少量补充检索查询。
如果素材已经足够，不要为了凑数量硬造查询。
""".strip()
    user_prompt = f"""
请分析现有的研究素材，找出缺失的关键信息，并生成用于进一步检索的查询语句。

必须覆盖的知识：{must_cover}
领域：{domain}
最多生成新查询数：{max_queries}

现有素材摘要：
{dense_context}

输出要求：
1. 分析现有素材中**没有充分解释**或**完全缺失**的关键概念、推导过程或示例。
2. 针对这些盲区（gaps），生成适合在搜索引擎上检索的中文查询语句。
3. 查询语句要足够具体，比如“XXX公式 详细推导过程”或“XXX 在实际工程中的应用案例”。
4. 只返回查询语句列表（按行分割或JSON均可，系统会自动提取其中有意义的文本），不要解释。
5. 如果现有素材已经足够完美，无需补充，你可以返回空结果。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_gap_queries",
        inputs={
            "dense_context_chars": len(dense_context),
            "required_count": len(required_elements),
            "max_queries": max_queries,
            "domain": domain,
        },
        output=messages,
    )


__all__ = [
    "build_docgen_heading_repair_messages",
    "build_docgen_mermaid_prompt",
    "build_docgen_research_purify_messages",
    "build_docgen_sub_query_messages",
    "build_docgen_gap_query_messages",
    "build_docgen_writer_messages",
]
