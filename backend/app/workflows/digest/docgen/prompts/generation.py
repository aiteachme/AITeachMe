"""Prompt builders for DocGen generation-time support."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
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


def _presentation_contract() -> str:
    return """
使用标准 Markdown 表达教学结构：自然段讲清逻辑，表格/清单只在对比、分类、步骤或参数密集时使用。
关键术语、条件、结论和易错边界可以加粗，但不要把整章写成高亮清单。
重点提示块只在确实能帮助理解核心结论、方法提醒或易错边界时使用；没有必要时不要硬凑。
不要使用 HTML、内联样式或装饰性符号。
""".strip()


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
请根据本章真实内容取舍和命名二级标题，优先体现本章主题、学习路径、例题价值与知识主线。
二级标题要像真实教材或课程讲义目录，应该是内容名词短语，例如“条件概率与独立性”“期望与方差的计算”“进程调度与同步互斥”，不要写成提醒读者行动的口号或内部流程。
所有 Markdown 标题都不要带展示编号，例如“1.”、“(1).”、“（一）”、“一、”、“第 1 章”等；前端会统一负责编号。
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

    normalized_mode = get_docgen_mode_profile(digest_mode).mode
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    execution_contract = dict(execution_contract or {})
    media_quota = dict(execution_contract.get("media_quota") or {})
    practice_quota = dict(execution_contract.get("practice_quota") or {})
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
    contract_summary = (
        f"- 目标字数：{execution_contract.get('target_word_count') or '未指定'}\n"
        f"- 最低字数：{execution_contract.get('min_word_count') or '未指定'}\n"
        f"- 最低覆盖分：{execution_contract.get('min_coverage_score') or '未指定'}\n"
        f"- 最低证据支撑：{execution_contract.get('min_evidence_support') or '未指定'}\n"
        f"- 解释深度：{execution_contract.get('explanation_depth') or '未指定'}\n"
        f"- 媒体配额：Mermaid {media_quota.get('mermaid', 0)}；不要请求文生图配图\n"
        f"- 练习配额：例题解析 {practice_quota.get('worked_examples', 0)} / 简答 {practice_quota.get('short_answer', 0)} / 快速检测 {practice_quota.get('self_check', 0)} / 推理 {practice_quota.get('reasoning', 0)} / 应用 {practice_quota.get('application', 0)}\n"
        f"- 本章主张目标：{'；'.join(claim_targets) if claim_targets else '按章节合同覆盖'}\n"
        f"- 需谨慎处理的冲突/低证据点：{'；'.join(conflict_warnings) if conflict_warnings else '无'}"
    )
    system_prompt = """
你是 AITeachMe 的中文教学文档作者。
你的任务是把研究材料写成可直接给学生阅读的高质量 Markdown 讲义。
成品必须像真实课程讲义或考前讲义，不像聊天回复，不像研究笔记，也不像内部草稿。
禁止输出英文标题、禁止输出英文段落、禁止把材料机械拼接。
遇到公式要解释公式在说什么、什么时候能用、最容易错在哪里。
如果材料不足，要坦诚用现有材料做稳健整理，不能编造事实或来源。
所有例题、变式题、类比和应用场景都必须贴合本学科、本章标题、学习目标和研究材料；禁止引入无关学科场景来凑例子。
""".strip()
    user_prompt = f"""
请只输出本章的中文 Markdown 正文，不要输出解释，不要输出代码块外的多余说明。

章节标题：{title}
学习目标：{objective or "把本章最核心的知识主线讲清楚。"}
文档模式：{normalized_mode}
必须覆盖：{required_text}
可用来源数量：{source_count}
额外写作要求：{writing_instructions or "保持教学导向，强调理解路径与复习价值。"}

模式参考：
{_build_mode_contract(digest_mode=normalized_mode, chapter_index=chapter_index, chapter_count=chapter_count)}

执行合同：
{contract_summary}

写作口径：
表达要像真实中文教学讲义：清楚、克制、可信、面向学习，不写聊天回复、鸡汤或内部草稿。
标题口径：二级标题必须来自本章知识对象、公式、方法、题型或应用场景；不要使用学习动作口号、问答提示或内部修补口吻。
编号口径：Markdown 标题不要自带编号；不要写 `# 1. {title}`、`## (1). 定义`、`## 一、核心概念` 这类标题。
版式口径：
{_presentation_contract()}
练习口径：如果本章适合用题目讲清方法，可以自然融入贴合本章的短例题或变式题；题目必须服务概念、条件或方法，不要为了凑数写泛泛复习提示。

参考写作路径，不要照抄为目录：
{_chapter_shape_hint(digest_mode=normalized_mode)}

输出要求：
1. 只输出中文 Markdown。
2. 一级标题必须是 `# {title}`。
3. 标题直接写语义短语，不要自带展示编号；前端和后处理会统一处理编号与标题规范。
4. 只写学生可见的正文，不输出资产占位符、内部协议、HTML 注释、Mermaid 源码块或调试信息。
5. 公式使用 Markdown 数学语法；代码、命令、路径、文件名、环境变量、配置项等字面量使用反引号代码片段，并保留原始符号。
6. 不编造引用、文献、实验结果或材料中不存在的事实。
7. 不要把研究材料原样贴出来，要改写成适合学生学习的讲义。
8. 先讲清概念、条件和判断依据，再讲题型、例子或应用，避免一上来堆技巧。
9. 例题、练习、类比和应用必须来自本章学科语境，不要跨学科凑例子。
10. 少写抒情句、鼓励句和聊天式口吻，保持清楚、克制、可信。

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
    normalized_mode = get_docgen_mode_profile(digest_mode).mode
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    system_prompt = """
你是 AITeachMe 的教学编辑助手。
你的任务不是重写整章主题，而是在保留原有内容价值和文风的前提下，修复章节的二级、三级标题与结构组织。
标题要自然、具体、像真实中文讲义；参考结构只能帮助判断缺口，不能变成固定模板。
修订目标是让它更像可读的课程讲义，而不是研究草稿、内部整理记录或套格式的提纲。
标题应是内容名词短语，而不是学习动作口号、问答提示或内部修补口吻。
所有 Markdown 标题都不要带展示编号，例如“1.”、“(1).”、“（一）”、“一、”、“第 1 章”等；前端会统一负责编号。
""".strip()
    # 标题修复只需要局部参考；完整正文和完整研究上下文仍保留在 state/manifest。
    user_prompt = f"""
请把下面这一章 Markdown 修订成“标题和结构更清楚，但仍保持原有教学内容”的版本。
章节标题：{title}
学习目标：{objective or "把本章最核心的知识主线讲清楚"}
文档模式：{normalized_mode}
必须覆盖：{required_text}
可用来源数量：{source_count}
额外写作要求：{writing_instructions or "保持教学导向，优先让结构更清楚"}
章节位置：第 {chapter_index or 1} 章 / 共 {chapter_count or '?'} 章

模式参考：
{_build_mode_contract(digest_mode=normalized_mode, chapter_index=chapter_index, chapter_count=chapter_count)}

输出要求：
1. 只输出修订后的完整中文 Markdown。
2. 一级标题必须保持为 `# {title}`。
3. 二级和三级标题可以重新命名、合并重复项或改掉泛标题；标题要来自本章知识对象、方法、题型或应用场景。
4. 尽量保留已有正文、例子和公式，除非确实重复或跑题，不要大删内容。
5. 只在结构确实不完整时补少量过渡句、总结句或提示句，不能凭空编造来源事实。
6. 代码、命令、路径、文件名、环境变量、配置项等字面量继续使用反引号代码片段，并保留原始符号。
7. 删除或改写草稿痕迹、研究材料堆砌、原始来源清单和内部调试信息。
8. 如果正文太像聊天式安慰、流程说明或研究摘录，要改成课堂讲义表达。
9. 保留已有重点提示块的学习价值；如果提示块过长，只压缩表达，不要整块删除。

写作口径：
表达要像真实中文教学讲义：清楚、克制、可信、面向学习，不写聊天回复、鸡汤或内部草稿。
版式口径：
{_presentation_contract()}
如果正文已有例题区，要保留“题目、解析、易错点”这类学习价值，不要改成只有题目列表。

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
    system_prompt = """
你是 AITeachMe 的研究整理助手。
你的任务是把杂乱素材提纯成适合章节写作使用的中文研究笔记。
你不能补充素材里没有的事实，也不能把研究笔记写成最终讲义正文。
""".strip()
    user_prompt = f"""
请把下面的研究素材提纯成“供章节写作直接使用”的中文研究笔记。

章节标题：{chapter_title or "未命名章节"}
章节目标：{objective or "为本章提供可教学、可解释、可举例的可靠材料。"}
文档模式：{normalized_mode}
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
2. 默认使用 `mindmap`；如果主题明确要求流程图、决策树或时间线，可以使用 `flowchart TD` 或 `timeline`。
3. 如果使用 mindmap，根节点必须是主题本身；最多 3 层结构，保证清晰，不要过密。
4. 节点文字优先用中文短语，单个节点尽量控制在 4 到 12 个字。
5. 不要在节点里放公式、HTML、Markdown 链接、代码符号、复杂括号嵌套；不要在同一个图里混用多种 Mermaid 图类型。
6. 如果上下文噪声很多，优先保留最核心的 3 到 6 个概念节点，宁可简洁也不要产出脏 Mermaid。
7. 绝对不要复制上下文中的 Markdown 标题、正文段落、`---` 分隔线或反引号。

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
    fallback_queries: list[str],
) -> list[dict[str, str]]:
    context_lines = "\n".join(
        f"- {item['text']}"
        for item in context_summary
        if str(item.get("text") or "").strip()
    ) or "- 当前没有额外上下文"
    fallback_lines = "\n".join(f"- {item}" for item in fallback_queries if str(item).strip()) or "- 无"
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
3. 优先覆盖：核心定义、推导/公式、应用例题、易错点/常见误区。
4. 如果主题更偏系统课，可适当补“前置知识”“适用条件”“概念关系”。
5. 如果主题更偏冲刺课，可适当补“真题”“高频题型”“防坑提醒”。
6. 所有查询必须使用中文。
7. 如果你判断信息不足，也请尽量基于主题稳健拆解，不要返回空列表。

可参考但不要机械照抄的兜底方向：
{fallback_lines}
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
            "fallback_query_count": len(fallback_queries),
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
