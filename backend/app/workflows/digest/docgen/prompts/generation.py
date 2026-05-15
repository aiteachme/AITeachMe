"""Prompt builders for DocGen generation-time support."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.presentation_policy import build_presentation_contract_prompt
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def _bullet_lines(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


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
文档模式契约：这是{profile.prompt_label}知识文档。
写作优先级是{profile.prompt_priority}。
这些只是参考侧重点，不是固定目录：{"、".join(profile.chapter_format)}。
课程化节奏也只是参考：{"、".join(profile.course_flow_hints)}。
请根据本章真实内容取舍和命名二级标题，优先体现本章主题、知识对象、方法路径、例题价值与知识主线。
二级标题必须由模型根据本章上下文重新判断生成，像真实教材或课程讲义目录；不要从固定词表、关键词抽取或字符串拼接中凑标题。
不要把内部检查词、学习动作、练习配额或模块标签写成学生可见目录，也不要统一套成固定句式。
如果无法确定一个具体标题，宁可保留正文段落或合并进相邻小节，不要生成假标题。
标题层级要自然：`##` 是主要内容块，`###` 只用于同一 `##` 下至少两个并列子主题；孤立三级标题应并入 `##` 或改成正文加粗小节。
标题只表达语义，不承担编号或样式说明。
不要为了凑齐参考模块而硬塞小节。{extra_contract}
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
    media_quota = dict(execution_contract.get("media_quota") or {})
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
    forbidden_scope = [
        str(item).strip()
        for item in list(execution_contract.get("forbidden_scope") or [])
        if str(item).strip()
    ]
    min_worked_examples = int(mode_profile.example_density_policy.get("worked_examples_per_chapter", 4) or 4)
    training_min_examples = int(mode_profile.example_density_policy.get("training_chapter_min_examples", 6) or 6)
    concept_min_examples = int(mode_profile.example_density_policy.get("concept_chapter_min_examples", 2) or 2)
    sprint_problem_contract = ""
    if mode_profile.is_sprint:
        sprint_problem_contract = f"""
练习组织原则：
- 先由模型根据本章材料判断本章角色，再决定组织形式。只有天然适合集中练习或任务训练的章节，才把题目或任务按本章真实差异分组，再分别讲“什么时候用、怎么做、怎么算完、哪里会错”。
- 概念、定义、过渡或铺垫章节不要硬改成测验章；用 {concept_min_examples} 个左右的短例子、反例、条件辨析或小任务把条件和边界讲清即可。
- 训练型章节至少写 {training_min_examples} 个完整学习活动，普通方法章至少写 {min_worked_examples} 个左右；每个完整活动必须包含 **题目/任务**、**解析步骤**、**答案或结论**、**易错点**。
- 真实题型或任务分类不能停留在口号或空表；每一类至少要能看到一个贴合本章的短题、条件变化或错因例子。
- 如果使用“自测”“辨析”“思考”这类形式，必须给出参考答案、判定依据或解题要点；不要只抛问题让学生自己想。
- 整份文档里的集中练习、测验或综合训练通常放在自然适合的 1-2 个章节或章末，不要让每一章都长成同一套固定收尾模块。
- 收束标题必须由模型根据本章具体题型、方法或知识对象自然命名；不要把学习动作、检查动作或配额标签复制成目录标题。
- 如果要写题型分类，先判断每类题真正考的对象、条件变化或操作步骤，再用这个差异命名；不要用序号占位名，不要把关键词拼成标题。
""".strip()
    sprint_problem_contract_summary = (
        sprint_problem_contract.replace("练习组织原则：\n", "").replace("\n", "；")
        if sprint_problem_contract
        else ""
    )
    contract_summary = (
        f"- 目标字数：{execution_contract.get('target_word_count') or '未指定'}\n"
        f"- 最低字数：{execution_contract.get('min_word_count') or '未指定'}\n"
        f"- 最低覆盖分：{execution_contract.get('min_coverage_score') or '未指定'}\n"
        f"- 最低证据支撑：{execution_contract.get('min_evidence_support') or '未指定'}\n"
        f"- 解释深度：{execution_contract.get('explanation_depth') or '未指定'}\n"
        f"- 媒体配额：Mermaid {media_quota.get('mermaid', 0)}；不要请求文生图配图\n"
        f"- 练习数量要求：例题解析 {practice_quota.get('worked_examples', 0)} 个；简答 {practice_quota.get('short_answer', 0)} 个；带答案的理解检查活动 {practice_quota.get('self_check', 0)} 个；推理 {practice_quota.get('reasoning', 0)} 个；应用 {practice_quota.get('application', 0)} 个\n"
        f"- 例题密度策略：{example_density_policy.get('policy_text') or '例题、案例和任务必须服务当前知识点。'}\n"
        f"{('- 练习组织原则：' + sprint_problem_contract_summary) if sprint_problem_contract_summary else ''}\n"
        f"- 内容角色目标：{content_role_targets}\n"
        f"- 例题覆盖计划：{example_coverage_plan}\n"
        f"- 章末练习收束计划：{chapter_end_practice_plan}\n"
        f"- 覆盖检查策略：{'；'.join(coverage_policy) if coverage_policy else '按学习大纲覆盖核心知识和例题。'}\n"
        f"- 本章主张目标：{'；'.join(claim_targets) if claim_targets else '按学习大纲覆盖'}\n"
        f"- 本章边界外主题：{'；'.join(forbidden_scope) if forbidden_scope else '无显式边界外主题'}\n"
        f"- 需谨慎处理的冲突/低证据点：{'；'.join(conflict_warnings) if conflict_warnings else '无'}"
    )
    system_prompt = """
你是 AITeachMe 的中文教学文档作者。
你的任务是把研究材料写成可直接给学生阅读的高质量 Markdown 讲义。
成品必须像真实课程讲义或复习讲义，不像聊天回复，不像研究笔记，也不像内部草稿。
禁止输出英文标题、禁止输出英文段落、禁止把材料机械拼接。
遇到公式要解释公式在说什么、什么时候能用、最容易错在哪里。
遇到步骤、例题、易错点和高频规则清单时，要拆成清楚的信息块，不能让不同学习功能混在同一段里。
章节要简练但必须完整：学生不看原教材也应能知道“是什么、为什么、什么时候能用、怎么用、怎么检查是否用对”。重要概念要有定义、边界和例子；重要方法要有条件、步骤、检查点和至少一个可解析任务。
如果材料不足，要坦诚用现有材料做稳健整理，不能编造事实或来源。
所有例题、变式题、类比和应用场景都必须贴合本课程、本章标题、学习目标和研究材料；禁止引入无关课程场景来凑例子。
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
表达要像真实中文教学讲义：清楚、克制、可信、面向学习，不写聊天回复、鸡汤或内部草稿。
标题口径：二级标题来自本章知识对象、公式、方法、真实任务或应用场景；标题要像成熟讲义目录，具体、可扫描、有信息增量，不要用固定表头或通用短语拼接。
章节边界：执行合同中的“本章边界外主题”属于其它章节；除非本章材料明确用它作一句前后联系，否则不要扩写成独立小节、例题或练习。
版式口径：
{_presentation_contract(digest_mode=normalized_mode)}
内容完整性：每个主要 `##` 都要形成一个可独立学习的小单元，让学生不看原教材也应能知道“是什么、为什么、什么时候能用、怎么用、怎么检查是否用对”。不要只写几句定义就跳到下一个标题。优先用“概念解释 + 条件边界 + 表格/步骤 + 例题/案例 + 检查点/易错点”的组合压缩信息，让内容比教材更直观、更好复习。
直观解释：遇到抽象概念、公式、定义、规则或流程时，先用一两句话讲清它解决什么问题，再给条件、例子或反例；不要只堆名词、定义和结论。
练习口径：如果本章适合用题目、案例或任务讲清方法，可以自然融入贴合本章的短例题、案例或变式任务；它们必须服务概念、条件或方法，不要为了凑数写泛泛复习提示。
例题优先级：例题、案例、操作示例、变式训练和自测是正文重点，不是附录。快速复习节奏要提高例题/任务密度，但密度要跟章节角色匹配：训练型章节多给完整题和变式，概念型章节用短例子、反例和条件辨析支撑理解；系统学习要保证每个核心知识点都有例题、案例或练习支撑。
题目样式：完整例题优先使用 `> [!EXAMPLE]`，章末练习收束优先使用 `> [!PRACTICE]`。块内用 **题目/任务**、**解析/判定依据**、**答案/结论**、**易错点** 标注清楚；不同学科可改成案例、操作、证明、翻译、设计或诊断任务，但必须给可判断的答案或标准。
当前模式质量线：如果是快速复习节奏，先由模型根据本章材料判断是否适合集中训练。训练型章节必须让学生一眼看到“这章会遇到哪些题或任务、条件怎么变、下一步怎么做、哪里最容易错”，并有由本章材料自然生成的真实分类或常见问法整理；普通概念/方法章节不强制分类表，但要有贴合本章的短例子、反例、边界提醒或小任务。不要把内部检查词直接写成学生可见表头。训练型章节至少 {training_min_examples} 个完整学习活动，普通方法章至少 {min_worked_examples} 个左右，概念章至少 {concept_min_examples} 个左右；执行合同要求更多时按更多写。
{sprint_problem_contract}
章末收束：每章末尾都应有一个短练习收束块，除非本章材料完全不适合出题或任务。这个块应由本章内容自然生成 2-4 个小题、案例检查、操作任务、判断题或迁移题，并给出答案/判定依据/解析要点；标题和题目类别必须来自本章真实内容，不要套固定模板。
版式表达：快速复习章节不要写成大段平铺笔记，也不要把公式、说明、步骤、提醒和例题揉在同一段里。连续解释两段后，下一段优先改成对照表、步骤列表、例题块、易错提醒或短小结，除非内容本身不适合。高频结论、题目条件、解题步骤、易错提醒和例题可使用 GitHub 风格 callout，例如 `> [!IMPORTANT]`、`> [!TIP]`、`> [!WARNING]`、`> [!EXAMPLE]`、`> [!PRACTICE]`；关键条件、限制和结论要适度加粗，但不要整段加粗。
学习内容角色：正文需要自然覆盖核心知识、方法示范、解释辅助、原理推理、练习评估、知识组织和应用拓展中的本章必要部分；这些是写作检查维度，不要求作为固定标题原样出现。

参考写作路径，不要照抄为目录：
{_chapter_shape_hint(digest_mode=normalized_mode)}

输出要求：
1. 只输出中文 Markdown。
2. 一级标题必须是 `# {title}`。
3. 标题直接写语义短语，层级要有并列关系；不要复用章节标题，不要制造孤立三级标题，也不要把样式说明写进正文。
4. 不要输出泛化目录标题、学习动作标题、内部检查标题、序号占位题型或证据整理标题；练习章可以写材料中真实存在的练习名，普通章节必须用具体语义标题。
5. 内容必须来自本章课程语境和研究材料：不编造来源事实，不原样贴研究材料，不跨课程凑例子，不把其它章节主题补成独立小节。
6. 先讲清概念、条件和判断依据，再讲真实任务、例子或应用；训练型章节要多给可解析的例题、案例、变式或错误诊断，系统课核心知识点也要有例子支撑。
7. 每个主要 `##` 至少讲清本小节对象、关键条件或边界、处理路径或解释依据、一个例子/任务/反例，以及一个检查点或易错提醒；如果某项不适合本学科，也要换成等价的案例、操作、证明、设计或诊断标准。
8. 例题和自测必须有解析步骤、答案或结论、易错点；不要只写“请自行练习”“思考一下”。
9. 章末保留一个短练习收束块，优先用 `> [!PRACTICE]`，包含 2-4 个贴合本章的小题/任务和答案或判定依据；传统题目不适合时改成案例检查、操作步骤检查、边界辨析或迁移任务。
10. 信息块要清楚分层：公式后解释适用条件，步骤后给检查点，例题后给错因；不要把公式、说明、步骤、提醒和例题揉成一段。
11. 只写学生可见正文；不输出内部协议、调试信息、来源附录、草稿痕迹、HTML 注释或未渲染占位内容。

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
4. 如果主题更偏系统课，可适当补“前置知识”“适用条件”“概念关系”。
5. 如果主题更偏快速复习，可适当补“真实任务/真实案例”“常见任务/高频题型”“防坑提醒”；只有材料明确包含考试或真题时才使用“真题”措辞。
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
