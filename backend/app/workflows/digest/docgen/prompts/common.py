"""DocGen prompt builders owned by the digest workflow layer."""

from __future__ import annotations

DENSE_CONTEXT_WRITER_BUDGET = 14000
DENSE_CONTEXT_REPAIR_BUDGET = 4000
DENSE_CONTEXT_PURIFY_BUDGET = 12000
DENSE_CONTEXT_GAP_QUERY_BUDGET = 8000
MARKDOWN_REPAIR_BUDGET = 14000
MERMAID_CONTEXT_BUDGET = 3000
PROMPT_CLAIM_TARGET_BUDGET = 8
PROMPT_CONFLICT_WARNING_BUDGET = 6


def _normalize_mode(digest_mode: str) -> str:
    return (digest_mode or "systematic").strip().lower()


def _chapter_shape_hint(*, digest_mode: str) -> str:
    normalized_mode = _normalize_mode(digest_mode)
    if normalized_mode == "sprint":
        return """
推荐写成考前冲刺讲义的骨架：
1) 本章在考什么/为什么重要；
2) 先把核心概念、结论、判断条件讲清楚；
3) 再讲典型题型、审题抓手、解题步骤；
4) 再收易错点、混淆点、边界条件；
5) 最后用精炼回顾或速记做收尾。
""".strip()
    return """
推荐写成课程讲义的骨架：
1) 本章问题背景与学习目标；
2) 核心定义/结构/符号；
3) 关键推理或方法如何成立；
4) 典型例子或应用如何落地；
5) 最后做本章总结与后续衔接。
""".strip()


def _build_mode_contract(
    *,
    digest_mode: str,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
) -> str:
    normalized_mode = _normalize_mode(digest_mode)
    if normalized_mode == "sprint":
        chapter_specific = ""
        if chapter_index == 1:
            chapter_specific = "如果这是课程开篇，本章必须先用直观场景、常见题型或学习动机破题，再建立概念直觉。"
        elif chapter_count and chapter_index == chapter_count:
            chapter_specific = "如果这是课程收束章，本章必须回收高频题型、易错点和最后复盘抓手。"
        return f"""
文档模式契约：这是冲刺型知识文档。
必须写得抓重点、抓题型、抓易错点。
必须覆盖这些教学模块：开篇导入、得分抓手、题型拆解、临考速记、易错辨析、最终回顾。
二级标题文案可以自行命名，优先写成自然、具体、像真实讲义的小标题，不要机械复用模板词。
结尾不能空泛，必须便于考前快速复盘。
{chapter_specific}
""".strip()
    extra = ""
    if chapter_index == 1:
        extra = "如果这是课程开篇，本章必须给出整体知识脉络；不要自行输出任何资产占位符。"
    elif chapter_count and chapter_index == chapter_count:
        extra = "如果这是课程收束章，本章必须回收全文主线，并给出进一步深入学习的建议。"
    return f"""
文档模式契约：这是系统型知识文档。
必须重视定义、定理、推导、应用与章节之间的结构关系。
必须覆盖这些教学模块：章节导入、前置知识、学习动机、关键定义/定理、推理到应用、章节回收。
二级标题文案可以自行命名，优先体现本章主题与知识主线，不要机械复用模板词。
如果涉及公式或定理，不能只写结论，必须解释适用前提、推理过程和常见边界。
{extra}
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
    normalized_mode = _normalize_mode(digest_mode)
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    execution_contract = dict(execution_contract or {})
    media_quota = dict(execution_contract.get("media_quota") or {})
    practice_quota = dict(execution_contract.get("practice_quota") or {})
    claim_targets = [
        str(item).strip()
        for item in list(execution_contract.get("claim_targets") or [])
        if str(item).strip()
    ][:PROMPT_CLAIM_TARGET_BUDGET]
    conflict_warnings = [
        str(item).strip()
        for item in list(execution_contract.get("conflict_warnings") or [])
        if str(item).strip()
    ][:PROMPT_CONFLICT_WARNING_BUDGET]
    contract_summary = (
        f"- 目标字数：{execution_contract.get('target_word_count') or '未指定'}\n"
        f"- 最低字数：{execution_contract.get('min_word_count') or '未指定'}\n"
        f"- 最低覆盖分：{execution_contract.get('min_coverage_score') or '未指定'}\n"
        f"- 最低证据支撑：{execution_contract.get('min_evidence_support') or '未指定'}\n"
        f"- 解释深度：{execution_contract.get('explanation_depth') or '未指定'}\n"
        f"- 媒体配额：Mermaid {media_quota.get('mermaid', 0)} / 图片 {media_quota.get('images', 0)}\n"
        f"- 练习配额：简答 {practice_quota.get('short_answer', 0)} / 自检 {practice_quota.get('self_check', 0)} / 推理 {practice_quota.get('reasoning', 0)} / 应用 {practice_quota.get('application', 0)}\n"
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
""".strip()
    # 研究材料可能很长，这里只裁剪 prompt 输入，不裁剪 workflow 中保存的原始上下文。
    user_prompt = f"""
请只输出本章的中文 Markdown 正文，不要输出解释，不要输出代码块外的多余说明。

章节标题：{title}
学习目标：{objective or "把本章最核心的知识主线讲清楚。"}
文档模式：{normalized_mode}
必须覆盖：{required_text}
可用来源数量：{source_count}
额外写作要求：{writing_instructions or "保持教学导向，强调理解路径与复习价值。"}

模式契约：
{_build_mode_contract(digest_mode=normalized_mode, chapter_index=chapter_index, chapter_count=chapter_count)}

执行合同：
{contract_summary}

写作口径：
表达要像真实中文教学讲义：清楚、克制、可信、面向学习，不写聊天回复、鸡汤或内部草稿。

推荐章节骨架：
{_chapter_shape_hint(digest_mode=normalized_mode)}

输出硬约束：
1. 只输出中文 Markdown。
2. 一级标题必须是 `# {title}`。
3. 二级标题必须服从模式契约，覆盖关键模块，但标题文案可以自行命名，不要整章复制固定模板标题。
4. 不要自行输出任何资产占位符、内部协议块、HTML 注释或 Mermaid 源码块；系统会在写作完成后按执行合同追加内部资产请求。
5. 只输出标准 Markdown；不要输出 HTML、CSS、`<style>`、`<div>`、`<details>` 或内联样式。
6. 如果需要公式，必须使用 `$...$` 或 `$$...$$`。
7. 不允许编造引用、文献、实验结果或材料中不存在的事实。
8. 不要把研究材料原样贴出来，要改写成适合学生学习的讲义。
9. 先讲清概念和判断依据，再讲题型、例子或应用，不能一上来堆口号或堆小技巧。
10. 减少抒情句、鼓励句、戏剧化比喻，避免“你已经掌握了”“稳住”“这一步很有灵魂”这类空话。
11. 禁止输出这些内部或草稿痕迹：`重点补全`、`结构补全`、`研究材料重组`、`可直接回看这些研究线索`、`研究笔记`、` ```markdown `、原始来源列表、内部 subject id。
12. 不要在章节正文里插入“参考资料与延伸阅读”；参考资料会统一在文档底部处理。

研究材料：
{dense_context[:DENSE_CONTEXT_WRITER_BUDGET]}
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


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
    normalized_mode = _normalize_mode(digest_mode)
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    system_prompt = """
你是 AITeachMe 的教学编辑助手。
你的任务不是重写整章主题，而是在保留原有内容价值和文风的前提下，修复章节的二级、三级标题与结构组织。
标题必须自然、具体、像真实中文讲义，不要使用模板化标题。
修订目标是让它更像可读的课程讲义，而不是研究草稿或内部整理记录。
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

模式契约：
{_build_mode_contract(digest_mode=normalized_mode, chapter_index=chapter_index, chapter_count=chapter_count)}

输出硬约束：
1. 只输出修订后的完整中文 Markdown。
2. 一级标题必须保持为 `# {title}`。
3. 二级和三级标题由你重新命名，可以合并重复标题、改掉泛标题、补上缺失教学模块。
4. 不要使用“本章导读”“快速回顾”“主题导入”“总结提升”“第 N 章”这类模板标题。
5. 尽量保留已有正文、例子和公式，除非确实重复或跑题，不要大删内容。
6. 如果结构不完整，可以补少量过渡句、总结句或提示句，但不要凭空编造来源事实。
7. 如果涉及公式，继续使用 `$...$` 或 `$$...$$`。
8. 不要新增任何资产占位符、内部协议块、HTML 注释或 Mermaid 源码块；只保留已有标准 Markdown 正文。
9. 只输出标准 Markdown；不要输出 HTML、CSS、`<style>`、`<div>`、`<details>` 或内联样式。
10. 删除或改写任何草稿痕迹：`重点补全`、`结构补全`、`研究材料重组`、`可直接回看这些研究线索`、`研究笔记`、原始来源堆砌、` ```markdown `。
11. 如果正文太像聊天式安慰、流程说明或研究摘录，要改成更像课堂讲义的表达。

写作口径：
表达要像真实中文教学讲义：清楚、克制、可信、面向学习，不写聊天回复、鸡汤或内部草稿。

推荐章节骨架：
{_chapter_shape_hint(digest_mode=normalized_mode)}

可参考但不要照抄的研究线索：
{dense_context[:DENSE_CONTEXT_REPAIR_BUDGET] or "暂无额外研究线索，请主要整理现有正文结构。"}

当前 Markdown：
{markdown[:MARKDOWN_REPAIR_BUDGET]}
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_docgen_research_purify_messages(
    *,
    dense_context: str,
    chapter_title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
) -> list[dict[str, str]]:
    must_cover = "、".join(required_elements) if required_elements else "与本章最相关的核心知识"
    normalized_mode = _normalize_mode(digest_mode)
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
6. 如果是 `sprint`，优先保留高频考点、题型线索和易错点。
7. 如果是 `systematic`，优先保留定义、推导、适用条件和结构关系。

原始素材：
{dense_context[:DENSE_CONTEXT_PURIFY_BUDGET]}
""".strip()
    return [
        {
            "role": "system",
            "content": "你是 AITeachMe 的研究整理助手，负责把杂乱素材提纯成适合教学写作的中文研究笔记。",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_docgen_mermaid_prompt(*, topic: str, context: str) -> str:
    return f"""
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
上下文：{context[:MERMAID_CONTEXT_BUDGET]}
""".strip()


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
    return [
        {
            "role": "system",
            "content": "你是 AITeachMe 的研究规划助手，负责把单个教学主题拆成可检索、可抓取、可用于知识整理的中文子查询。",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_docgen_gap_query_messages(
    *,
    dense_context: str,
    required_elements: list[str],
    max_queries: int = 2,
    domain: str = "education",
) -> list[dict[str, str]]:
    must_cover = "、".join(required_elements) if required_elements else "与本章最相关的核心知识"
    user_prompt = f"""
请分析现有的研究素材，找出缺失的关键信息，并生成用于进一步检索的查询语句。

必须覆盖的知识：{must_cover}
领域：{domain}
最多生成新查询数：{max_queries}

现有素材摘要：
{dense_context[:DENSE_CONTEXT_GAP_QUERY_BUDGET]}

输出要求：
1. 分析现有素材中**没有充分解释**或**完全缺失**的关键概念、推导过程或示例。
2. 针对这些盲区（gaps），生成适合在搜索引擎上检索的中文查询语句。
3. 查询语句要足够具体，比如“XXX公式 详细推导过程”或“XXX 在实际工程中的应用案例”。
4. 只返回查询语句列表（按行分割或JSON均可，系统会自动提取其中有意义的文本），不要解释。
5. 如果现有素材已经足够完美，无需补充，你可以返回空结果。
""".strip()
    return [
        {
            "role": "system",
            "content": "你是 AITeachMe 的研究分析引擎，负责寻找现有资料的盲区，并生成补充检索的查询语句以完善知识闭环。",
        },
        {"role": "user", "content": user_prompt},
    ]


__all__ = [
    "build_docgen_heading_repair_messages",
    "build_docgen_mermaid_prompt",
    "build_docgen_research_purify_messages",
    "build_docgen_sub_query_messages",
    "build_docgen_gap_query_messages",
    "build_docgen_writer_messages",
]
