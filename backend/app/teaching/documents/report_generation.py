"""教学领域的学习文档装配与脚手架函数。"""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.teaching.documents.content_blocks import (
    build_glossary_section,
    build_learning_objectives_section,
)

_TITLE_PREFIX_RE = re.compile(r"^\s*(?:第\s*\d+\s*章[\s：:、.-]*)?(?:\d+[\).、：:\-\s]+)?(.+?)\s*$")
_LEGACY_TEMPLATE_SUFFIX_RE = re.compile(
    r"[:：]\s*(核心概念|公式方法|题型突破|易错辨析|综合迁移|考前速查|主题导入|概念定义|结构公式|方法推理|例题应用|边界辨析|总结延伸)\s*$"
)
_LEGACY_TEMPLATE_TITLES = {
    "全景导论",
    "总结与延展",
    "主题导入",
    "概念定义",
    "结构公式",
    "方法推理",
    "例题应用",
    "边界辨析",
    "综合迁移",
    "总结延伸",
    "核心概念",
    "公式方法",
    "题型突破",
    "易错辨析",
    "考前速查",
}
_STATIC_TITLES = {"练习与自检", "知识文档总览"}


def clean_generated_chapter_title(raw_title: str) -> str:
    cleaned = _TITLE_PREFIX_RE.sub(r"\1", str(raw_title or "").strip())
    cleaned = cleaned.strip().strip("“”\"'`")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip("：:，,。；; ")


def looks_like_legacy_template_title(title: str) -> bool:
    cleaned = clean_generated_chapter_title(title)
    if not cleaned:
        return False
    if cleaned in _LEGACY_TEMPLATE_TITLES:
        return True
    return bool(_LEGACY_TEMPLATE_SUFFIX_RE.search(cleaned))


def is_usable_resolved_chapter_title(title: str) -> bool:
    cleaned = clean_generated_chapter_title(title)
    if cleaned in _STATIC_TITLES:
        return True
    if len(cleaned) < 3 or len(cleaned) > 28:
        return False
    if looks_like_legacy_template_title(cleaned):
        return False
    if re.fullmatch(r"第\s*\d+\s*章", cleaned):
        return False
    return True


def resolve_effective_chapter_title(
    chapter: Mapping[str, object] | None = None,
    *,
    chapter_index: int | None = None,
    fallback_title: str | None = None,
) -> str:
    chapter_data = chapter or {}
    resolved_title = clean_generated_chapter_title(str(chapter_data.get("resolved_title") or ""))
    if is_usable_resolved_chapter_title(resolved_title):
        return resolved_title

    provisional_title = clean_generated_chapter_title(str(chapter_data.get("title") or ""))
    if provisional_title and not looks_like_legacy_template_title(provisional_title):
        return provisional_title

    cleaned_fallback = clean_generated_chapter_title(str(fallback_title or ""))
    if cleaned_fallback and not looks_like_legacy_template_title(cleaned_fallback):
        return cleaned_fallback

    if chapter_index is None:
        chapter_index = int(chapter_data.get("chapter_index", 0) or 0) or None
    return f"第 {chapter_index} 章" if chapter_index else "未命名章节"


def coerce_resolved_chapter_title(
    raw_title: str,
    *,
    chapter: Mapping[str, object] | None = None,
    chapter_index: int | None = None,
) -> str:
    cleaned = clean_generated_chapter_title(raw_title)
    if is_usable_resolved_chapter_title(cleaned):
        return cleaned
    return resolve_effective_chapter_title(chapter, chapter_index=chapter_index)


def build_chapter_title_resolution_messages(
    *,
    subject: str,
    digest_mode: str,
    objective: str,
    required_elements: list[str],
    search_queries: list[str],
    writing_instructions: str,
    dense_context: str,
    source_titles: list[str],
    local_hits: int,
    web_hits: int,
) -> list[dict[str, str]]:
    normalized_mode = _normalize_mode(digest_mode)
    mode_label = "冲刺课" if normalized_mode == "sprint" else "系统课"
    required_text = "、".join(item for item in required_elements if item.strip()) or "核心概念、推理路径、典型例子"
    query_text = "；".join(item for item in search_queries if item.strip()) or "无明确检索词"
    source_text = "\n".join(f"- {item}" for item in source_titles if item.strip()) or "- 当前没有明确来源标题"
    user_prompt = f"""
请为下面这一章生成一个新的中文章节标题。

主题：{subject}
课程模式：{mode_label}
学习目标：{objective or "把本章最核心的知识主线讲清楚。"}
必须覆盖：{required_text}
检索重点：{query_text}
写作要求：{writing_instructions or "保持教学导向，体现知识脉络。"}
证据概况：本地命中 {local_hits} 条，外部命中 {web_hits} 条。

来源线索：
{source_text}

研究笔记：
{dense_context[:5000] or "暂无研究笔记，请根据章节合同稳健命名。"}

输出要求：
1. 只输出一个中文标题。
2. 不要出现“全景导论”“总结与延展”“主题导入”“概念定义”等模板化命名。
3. 标题要像真实讲义章节名，体现知识主线或问题意识。
4. 不要输出编号，不要输出解释，不要输出 Markdown。
""".strip()
    return [
        {
            "role": "system",
            "content": "你是 AITeachMe 的课程命名助手，负责根据教学合同和研究结果生成自然、具体、非模板化的中文章节标题。",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_document_overview(
    *,
    subject: str,
    digest_mode: str,
    tone: str,
    user_goal: str,
    plan_summary: str,
    source_strategy: str = "",
    chapters: list[Mapping[str, object]],
) -> str:
    """构建知识文档开头的总览页。"""

    normalized_mode = _normalize_mode(digest_mode)
    mode_label = "冲刺课" if normalized_mode == "sprint" else "系统课"
    note_kind = "TIP" if normalized_mode == "sprint" else "IMPORTANT"
    goal_line = user_goal.strip() or f"围绕 {subject} 生成一份结构化学习文档。"
    summary_line = plan_summary.strip() or _default_plan_summary(
        subject=subject,
        digest_mode=normalized_mode,
        chapters=chapters,
    )

    lines = [
        "# 知识文档总览",
        "",
        f"> [!{note_kind}]",
        f"> 学科：{subject}",
        f"> 模式：{mode_label}",
        f"> 风格：{tone or 'encouraging'}",
        f"> 目标：{goal_line}",
        f"> 方案摘要：{summary_line}",
    ]
    source_strategy_label = _source_strategy_label(source_strategy)
    if source_strategy_label:
        lines.append(f"> 资料策略：{source_strategy_label}")
    lines.extend(["", "## 如何使用这份文档", ""])
    lines.extend(f"- {item}" for item in _reading_guidance(normalized_mode))
    lines.extend(
        [
            "",
            "## 章节路线图",
            "",
            "| 章节 | 学习重点 | 证据概览 |",
            "| --- | --- | --- |",
        ]
    )

    for chapter in chapters:
        chapter_index = int(chapter.get("chapter_index", 0) or 0)
        title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        focus = _chapter_focus(chapter)
        evidence = _chapter_evidence(chapter)
        lines.append(f"| {chapter_index or '-'} | {title} | {focus} | {evidence} |")

    return "\n".join(lines).strip() + "\n"


def ensure_chapter_learning_scaffold(
    markdown: str,
    *,
    title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
    source_count: int = 0,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
) -> str:
    """为单章内容补齐稳定的教学脚手架。"""

    cleaned = (markdown or "").strip()
    if not cleaned.startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}".strip()
    analysis_source = cleaned

    guide_block = build_chapter_guide(
        title=title,
        objective=objective,
        required_elements=required_elements,
        digest_mode=digest_mode,
        source_count=source_count,
    )
    missing_blocks: list[str] = []
    if not _contains_heading(cleaned, "## 本章导读"):
        missing_blocks.append(guide_block.strip())
    glossary_block = build_glossary_section(
        analysis_source,
        required_elements=required_elements,
    )
    if glossary_block and not _contains_heading(cleaned, "## 术语速览"):
        missing_blocks.append(glossary_block.strip())
    objectives_block = build_learning_objectives_section(
        analysis_source,
        objective=objective,
        required_elements=required_elements,
    )
    if objectives_block and not _contains_heading(cleaned, "## 学习目标对照"):
        missing_blocks.append(objectives_block.strip())

    for heading, block in _build_mode_sections(
        title=title,
        objective=objective,
        required_elements=required_elements,
        digest_mode=digest_mode,
        chapter_index=chapter_index,
        chapter_count=chapter_count,
    ):
        if not _contains_heading(cleaned, heading):
            missing_blocks.append(block.strip())

    if missing_blocks:
        cleaned = _insert_after_first_heading(cleaned, "\n\n".join(missing_blocks))

    recap_heading = "## 快速回顾" if _normalize_mode(digest_mode) == "sprint" else "## 本章要点"
    if not _contains_heading(cleaned, recap_heading):
        recap_block = build_chapter_recap(
            title=title,
            required_elements=required_elements,
            digest_mode=digest_mode,
        )
        cleaned = cleaned.rstrip() + "\n\n" + recap_block.strip() + "\n"
    return cleaned.rstrip() + "\n"


def build_chapter_guide(
    *,
    title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
    source_count: int = 0,
) -> str:
    normalized_mode = _normalize_mode(digest_mode)
    note_kind = "TIP" if normalized_mode == "sprint" else "IMPORTANT"
    goal_line = objective.strip() or f"理解《{title}》这一章最核心的知识主线。"
    focus_items = required_elements[:4] or _default_required_elements(normalized_mode)
    evidence_line = (
        f"本章整合了 {source_count} 条筛选后的参考来源。"
        if source_count > 0
        else "本章基于构建方案与当前可用学习素材整理而成。"
    )

    lines = [
        "## 本章导读",
        "",
        f"> [!{note_kind}]",
        f"> 学习目标：{goal_line}",
        f"> 素材说明：{evidence_line}",
        "",
        "### 建议先抓住这些点",
        "",
    ]
    lines.extend(f"- {item}" for item in focus_items)
    return "\n".join(lines).strip()


def build_chapter_recap(*, title: str, required_elements: list[str], digest_mode: str) -> str:
    normalized_mode = _normalize_mode(digest_mode)
    heading = "## 快速回顾" if normalized_mode == "sprint" else "## 本章要点"
    items = required_elements[:3] or _default_required_elements(normalized_mode)
    prompts = (
        [
            f"不用看公式，试着用一句话讲清楚《{title}》的核心意思。",
            f"把“{items[0]}”和一道典型题型或常见解法对应起来。",
            "说出一个最容易在考试里出错的点，并解释为什么。",
        ]
        if normalized_mode == "sprint"
        else [
            f"概括《{title}》背后的核心结构或主命题。",
            f"总结“{items[0]}”与本章其他部分之间的联系。",
            "指出一个你最需要回头再看一遍的定义、定理或推理步骤。",
        ]
    )
    lines = [heading, ""]
    lines.extend(f"- {item}" for item in prompts)
    return "\n".join(lines).strip()


def _build_mode_sections(
    *,
    title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
    chapter_index: int | None = None,
    chapter_count: int | None = None,
) -> list[tuple[str, str]]:
    normalized_mode = _normalize_mode(digest_mode)
    focus_items = required_elements[:4] or _default_required_elements(normalized_mode)
    focus_text = "、".join(focus_items)

    if normalized_mode == "sprint":
        quick_card = [
            f"- 这章最先记住：{focus_items[0]}",
            f"- 这章最常考：{focus_items[1] if len(focus_items) > 1 else '核心题型'}",
            "- 这章最值得临考前再扫一遍的，是步骤和易错点。",
        ]
        return [
            (
                "## 核心抓手",
                "\n".join(
                    [
                        "## 核心抓手",
                        "",
                        f"- 本章目标：{objective or '把本章最关键的得分点讲清楚。'}",
                        f"- 优先掌握：{focus_text}",
                        "- 先理解概念，再把它和题型、步骤、误区连起来。",
                    ]
                ).strip(),
            ),
            (
                "## 题型拆解",
                "\n".join(
                    [
                        "## 题型拆解",
                        "",
                        "1. 先识别题目在考什么概念或公式。",
                        "2. 再判断题目需要哪条解题路径。",
                        "3. 最后总结这种题型最容易踩的坑。",
                    ]
                ).strip(),
            ),
            (
                "## 本章速记卡",
                "\n".join(["## 本章速记卡", "", *quick_card]).strip(),
            ),
            (
                "## 易错提醒",
                "\n".join(
                    [
                        "## 易错提醒",
                        "",
                        "- 不要只记结论，要记“什么时候用”和“为什么这样用”。",
                        "- 如果出现相近概念，必须顺手做一遍对比。",
                        "- 做题时先判断条件，再套方法，不要直接机械代公式。",
                    ]
                ).strip(),
            ),
        ]

    sections: list[tuple[str, str]] = [
        (
            "## 前置知识",
            "\n".join(
                [
                    "## 前置知识",
                    "",
                    f"- 建议先回顾：{focus_items[0]}",
                    f"- 本章会反复用到：{focus_items[1] if len(focus_items) > 1 else '核心定义'}",
                    "- 如果前置概念还不稳，先从定义和符号入手。",
                ]
            ).strip(),
        ),
        (
            "## 动机引入",
            "\n".join(
                [
                    "## 动机引入",
                    "",
                    f"{objective or '本章要解决的是：为什么需要这部分知识，它在整体结构里承担什么作用。'}",
                ]
            ).strip(),
        ),
        (
            "## 核心定义与定理",
            "\n".join(
                [
                    "## 核心定义与定理",
                    "",
                    f"- 请围绕这些元素组织内容：{focus_text}",
                    "- 若出现定理或公式，必须解释适用条件、结论含义和使用边界。",
                ]
            ).strip(),
        ),
        (
            "## 推理与应用",
            "\n".join(
                [
                    "## 推理与应用",
                    "",
                    "- 先说明推理链条，再给出应用例子。",
                    "- 例子最好覆盖“怎么用”“为什么这样用”“容易错在哪”。",
                ]
            ).strip(),
        ),
    ]

    if chapter_index == 1:
        sections.append(
            (
                "## 全局脉络图",
                "\n".join(
                    [
                        "## 全局脉络图",
                        "",
                        f"<!-- [MERMAID: {title} 的整体知识脉络图] -->",
                    ]
                ).strip(),
            )
        )
    if chapter_count and chapter_index == chapter_count:
        sections.append(
            (
                "## 延伸学习",
                "\n".join(
                    [
                        "## 延伸学习",
                        "",
                        "- 回看全文时，优先串联核心定义、关键推理和典型应用。",
                        "- 如果继续深入，建议按“基础定义 -> 关键方法 -> 综合问题”继续扩展。",
                    ]
                ).strip(),
            )
        )
    return sections


def _default_required_elements(digest_mode: str) -> list[str]:
    if digest_mode == "sprint":
        return ["核心概念", "题型抓手", "常见陷阱"]
    return ["定义", "推理链条", "例题"]


def _reading_guidance(digest_mode: str) -> list[str]:
    if digest_mode == "sprint":
        return [
            "先看“本章导读”，快速确认哪些概念、公式和题型最值得优先记住。",
            "重点利用题型拆解和易错提醒，训练考场场景下的快速判断路径。",
            "每章结尾的“快速回顾”适合在考前或刷题前再扫一遍。",
        ]
    return [
        "建议按章节顺序阅读，因为后面的内容通常依赖前面建立的定义和结构。",
        "结合章节路线图和每章导读来理解整体脉络，不要只孤立记忆零散知识点。",
        "每读完一章就回看一次“本章要点”，先固化主结论，再进入下一章。",
    ]


def _chapter_focus(chapter: Mapping[str, object]) -> str:
    tags = [str(item).strip() for item in chapter.get("tags", []) if str(item).strip()]
    if tags:
        return "、".join(tags[:3])
    summary = str(chapter.get("summary") or "").strip()
    if summary:
        return summary[:120]
    return "核心概念、推理链路与典型例子"


def _chapter_evidence(chapter: Mapping[str, object]) -> str:
    source_count = len(list(chapter.get("source_details", []) or []))
    local_hits = int(chapter.get("local_hits", 0) or 0)
    web_hits = int(chapter.get("web_hits", 0) or 0)
    if source_count <= 0 and local_hits <= 0 and web_hits <= 0:
        return "基于规划结果整理"

    evidence_bits: list[str] = []
    if source_count > 0:
        evidence_bits.append(f"{source_count} 条来源")
    if local_hits > 0:
        evidence_bits.append(f"{local_hits} 条本地命中")
    if web_hits > 0:
        evidence_bits.append(f"{web_hits} 条外部命中")
    return "；".join(evidence_bits)


def _default_plan_summary(*, subject: str, digest_mode: str, chapters: list[Mapping[str, object]]) -> str:
    mode_label = "冲刺型" if digest_mode == "sprint" else "系统型"
    return f"围绕 {subject} 设计的一条 {mode_label} 学习路径，共 {len(chapters)} 章。"


def _source_strategy_label(source_strategy: str) -> str:
    normalized = str(source_strategy or "").strip().lower()
    if normalized == "local_first":
        return "优先基于上传资料整理，再按需补充外部研究。"
    if normalized == "web_first":
        return "当前缺少本地资料，优先执行联网研究与来源筛选。"
    return ""


def _normalize_mode(digest_mode: str) -> str:
    return (digest_mode or "systematic").strip().lower()


def _contains_heading(markdown: str, heading: str) -> bool:
    target = heading.strip().lower()
    for line in markdown.splitlines():
        if line.strip().lower() == target:
            return True
    return False


def _insert_after_first_heading(markdown: str, block: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            insertion_index = index + 1
            while insertion_index < len(lines) and lines[insertion_index].strip() == "":
                insertion_index += 1
            return "\n".join(
                lines[:insertion_index] + ["", block.strip(), ""] + lines[insertion_index:]
            ).strip()
    return (block.strip() + "\n\n" + markdown.strip()).strip()


__all__ = [
    "build_chapter_title_resolution_messages",
    "build_chapter_guide",
    "build_chapter_recap",
    "clean_generated_chapter_title",
    "coerce_resolved_chapter_title",
    "build_document_overview",
    "ensure_chapter_learning_scaffold",
    "is_usable_resolved_chapter_title",
    "looks_like_legacy_template_title",
    "resolve_effective_chapter_title",
]
