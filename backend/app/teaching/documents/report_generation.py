"""教学领域的学习文档装配与脚手架函数。"""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.shared.infra.observability import annotate_traceable
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
_TITLE_SPECIFICITY_KEYWORDS = (
    "高频",
    "题型",
    "公式",
    "速判",
    "易错",
    "边界",
    "路径",
    "定义",
    "结构",
    "方法",
    "例题",
    "应用",
    "迁移",
    "总结",
    "速查",
    "考点",
    "真题",
    "变式",
)
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_SUBJECT_SLUG_RE = re.compile(r"^subj_[a-z0-9_-]+$", re.IGNORECASE)
_GENERIC_FOCUS_TERMS = {
    "核心概念",
    "高频考点",
    "直观理解",
    "核心公式",
    "使用条件",
    "方法判断",
    "典型题型",
    "步骤拆解",
    "变式提醒",
    "易错点",
    "混淆概念",
    "失分原因",
    "综合变式",
    "得分策略",
    "学习目标",
    "前置关系",
    "核心问题",
    "关键概念",
    "符号说明",
    "关键结构",
    "核心定义",
    "关键公式",
    "成立条件",
    "推理过程",
    "方法步骤",
    "判断依据",
    "应用场景",
    "复习建议",
    "本章内容",
}
_SPRINT_HEADING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "guide": ("导读", "先看", "先拿", "破题", "切入", "抓什么"),
    "glossary": ("术语", "概念", "名词"),
    "objectives": ("目标", "学完", "做到"),
    "main": ("抓手", "重点", "核心", "得分"),
    "drills": ("题型", "拆解", "做题", "例题"),
    "memory": ("速记", "速查", "记忆", "清单"),
    "pitfalls": ("易错", "误区", "陷阱", "边界"),
    "recap": ("回顾", "复盘", "总结", "带走"),
}
_SYSTEMATIC_HEADING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "guide": ("导读", "先看", "进入", "切入", "主线"),
    "glossary": ("术语", "概念", "名词"),
    "objectives": ("目标", "学完", "做到"),
    "prereq": ("前置", "准备", "基础"),
    "motivation": ("为什么", "动机", "问题"),
    "definitions": ("定义", "定理", "结构", "框架"),
    "reasoning": ("推理", "应用", "证明", "怎么走"),
    "map": ("脉络", "位置", "地图", "全局"),
    "extension": ("延伸", "继续", "进阶"),
    "recap": ("回收", "总结", "要点", "带走"),
}


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
    if not re.search(r"[\u3400-\u9fff]", cleaned):
        return False
    if looks_like_legacy_template_title(cleaned):
        return False
    if re.fullmatch(r"第\s*\d+\s*章", cleaned):
        return False
    return True


def _title_specificity_score(title: str) -> int:
    cleaned = clean_generated_chapter_title(title)
    if not is_usable_resolved_chapter_title(cleaned):
        return -100

    score = 0
    length = len(cleaned)
    if 6 <= length <= 18:
        score += 4
    elif 4 <= length <= 24:
        score += 2

    if "：" in cleaned or ":" in cleaned:
        score += 3
    if any(keyword in cleaned for keyword in _TITLE_SPECIFICITY_KEYWORDS):
        score += 3
    if len(set(cleaned)) >= 6:
        score += 1
    return score


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
    if is_usable_resolved_chapter_title(provisional_title):
        return provisional_title

    cleaned_fallback = clean_generated_chapter_title(str(fallback_title or ""))
    if is_usable_resolved_chapter_title(cleaned_fallback):
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
    current_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
    if is_usable_resolved_chapter_title(cleaned):
        if _title_specificity_score(current_title) > _title_specificity_score(cleaned):
            return current_title
        return cleaned
    return current_title


@annotate_traceable(name="teaching.chapter_title_resolution_prompt", run_type="prompt")
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
    subject_display_name: str = "",
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
    display_subject = _resolve_subject_display_name(subject=subject, subject_display_name=subject_display_name)
    deduped_chapters = _dedupe_chapters_for_overview(chapters)
    goal_line = user_goal.strip() or f"围绕 {display_subject} 生成一份结构化学习文档。"
    summary_line = plan_summary.strip() or _default_plan_summary(
        subject=display_subject,
        digest_mode=normalized_mode,
        chapters=deduped_chapters,
    )

    lines = [
        "# 知识文档总览",
        "",
        f"> [!{note_kind}]",
        f"> 课程：{display_subject}",
        f"> 类型：{mode_label}",
        f"> 学习目标：{goal_line}",
        f"> 文档定位：{summary_line}",
    ]
    source_strategy_label = _source_strategy_label(source_strategy)
    if source_strategy_label:
        lines.append(f"> 资料来源：{source_strategy_label}")
    lines.extend(["", "## 这份文档怎么读", ""])
    lines.extend(f"- {item}" for item in _reading_guidance(normalized_mode))
    lines.extend(
        [
            "",
            "## 章节安排",
            "",
            "| 章节 | 标题 | 学习重点 | 章节定位 |",
            "| --- | --- | --- | --- |",
        ]
    )

    for chapter in deduped_chapters:
        chapter_index = int(chapter.get("chapter_index", 0) or 0)
        title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        focus = _chapter_focus(chapter)
        takeaway = _chapter_takeaway(chapter, digest_mode=normalized_mode)
        lines.append(f"| {chapter_index or '-'} | {title} | {focus} | {takeaway} |")

    return "\n".join(lines).strip() + "\n"


def _resolve_subject_display_name(*, subject: str, subject_display_name: str = "") -> str:
    explicit = str(subject_display_name or "").strip()
    if explicit and not _SUBJECT_SLUG_RE.fullmatch(explicit):
        return explicit
    normalized = str(subject or "").strip()
    if normalized and not _SUBJECT_SLUG_RE.fullmatch(normalized):
        return normalized
    return "当前课程"


def _dedupe_chapters_for_overview(chapters: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    best_by_index: dict[int, Mapping[str, object]] = {}
    for chapter in chapters:
        chapter_index = int(chapter.get("chapter_index", 0) or 0)
        existing = best_by_index.get(chapter_index)
        if existing is None:
            best_by_index[chapter_index] = chapter
            continue
        existing_len = len(str(existing.get("markdown") or existing.get("summary") or ""))
        current_len = len(str(chapter.get("markdown") or chapter.get("summary") or ""))
        if current_len >= existing_len:
            best_by_index[chapter_index] = chapter
    return [best_by_index[index] for index in sorted(best_by_index)]


def _chapter_takeaway(chapter: Mapping[str, object], *, digest_mode: str) -> str:
    tags = [str(item).strip() for item in chapter.get("tags", []) if str(item).strip()]
    if tags:
        if _normalize_mode(digest_mode) == "sprint":
            return f"先讲清 {tags[0]}，再落到题型与失分点"
        return f"先建立 {tags[0]}，再展开推理与应用"
    return "按本章主线完成概念理解、方法落地和总结回收"


def _extract_heading_titles(
    markdown: str,
    *,
    min_level: int = 2,
    max_level: int = 3,
) -> list[str]:
    titles: list[str] = []
    for hashes, title in _HEADING_RE.findall(markdown or ""):
        level = len(hashes)
        if level < min_level or level > max_level:
            continue
        cleaned = re.sub(r"\s+", " ", title).strip()
        if cleaned:
            titles.append(cleaned)
    return titles


def _count_headings(markdown: str, *, level: int) -> int:
    return sum(1 for hashes, _title in _HEADING_RE.findall(markdown or "") if len(hashes) == level)


def _has_heading_keywords(markdown: str, keywords: tuple[str, ...], *, min_level: int = 2, max_level: int = 3) -> bool:
    if not keywords:
        return False
    heading_titles = _extract_heading_titles(markdown, min_level=min_level, max_level=max_level)
    return any(any(keyword in title for keyword in keywords) for title in heading_titles)


def _normalize_focus_fragment(value: str, *, max_length: int = 12) -> str:
    cleaned = clean_generated_chapter_title(value)
    fragments = [
        part.strip()
        for part in re.split(r"[：:、，,（）()／/\-·\s]+", cleaned)
        if part.strip()
    ]
    for fragment in fragments:
        if 2 <= len(fragment) <= max_length and fragment not in _GENERIC_FOCUS_TERMS:
            return fragment
    if 2 <= len(cleaned) <= max_length and cleaned not in _GENERIC_FOCUS_TERMS:
        return cleaned
    return cleaned[:max_length].rstrip("：:，,。；; ")


def _pick_heading_focus(title: str, required_elements: list[str], *, fallback: str = "本章内容") -> str:
    for candidate in [*required_elements, title]:
        focus = _normalize_focus_fragment(candidate)
        if focus and focus not in _GENERIC_FOCUS_TERMS:
            return focus
    return fallback


def _heading_keyword_map(digest_mode: str) -> dict[str, tuple[str, ...]]:
    return _SPRINT_HEADING_KEYWORDS if _normalize_mode(digest_mode) == "sprint" else _SYSTEMATIC_HEADING_KEYWORDS


def _build_scaffold_headings(
    *,
    title: str,
    required_elements: list[str],
    digest_mode: str,
) -> dict[str, str]:
    normalized_mode = _normalize_mode(digest_mode)
    short_title = _normalize_focus_fragment(title, max_length=10) or "本章"
    focus = _pick_heading_focus(title, required_elements, fallback=short_title or "本章内容")
    if normalized_mode == "sprint":
        return {
            "guide": "## 这一章先看什么",
            "glossary": "## 先把核心概念讲清楚",
            "objectives": "## 学完这章你要会什么",
            "main": f"## {focus}的核心结论与判断抓手",
            "drills": "## 典型题型怎么审怎么做",
            "memory": "## 临考速记：最后要记住什么",
            "pitfalls": "## 易错点和混淆点集中辨析",
            "recap": "## 本章最后复盘",
        }
    return {
        "guide": f"## 进入《{short_title}》前先抓哪条主线",
        "glossary": "## 关键概念先讲清楚",
        "objectives": f"## 学完《{short_title}》后你应该会什么",
        "prereq": f"## 学《{short_title}》前要先补什么",
        "motivation": f"## 为什么这一章必须现在学",
        "definitions": f"## {focus}的定义、结构与核心关系",
        "reasoning": f"## {focus}怎样一步步走到应用",
        "map": f"## 《{short_title}》在整门课里的位置",
        "extension": f"## 学完《{short_title}》后还能往哪里接",
        "recap": f"## 《{short_title}》最后要带走什么",
    }


def analyze_chapter_heading_quality(markdown: str, *, digest_mode: str) -> dict[str, object]:
    normalized_mode = _normalize_mode(digest_mode)
    heading_keywords = _heading_keyword_map(normalized_mode)
    heading_titles = _extract_heading_titles(markdown, min_level=2, max_level=3)
    cleaned_titles = [clean_generated_chapter_title(title) for title in heading_titles if clean_generated_chapter_title(title)]
    duplicates = list(dict.fromkeys(title for title in cleaned_titles if cleaned_titles.count(title) > 1))
    generic_titles = [title for title in cleaned_titles if looks_like_legacy_template_title(title)]
    missing_modules = [
        key
        for key, keywords in heading_keywords.items()
        if not _has_heading_keywords(markdown, keywords)
    ]
    min_h2_count = 4 if normalized_mode == "sprint" else 5
    h2_count = _count_headings(markdown, level=2)
    needs_agent_repair = bool(
        h2_count < min_h2_count
        or duplicates
        or generic_titles
        or len(missing_modules) >= 2
    )
    needs_scaffold_fallback = bool(
        h2_count < max(2, min_h2_count - 1)
        or len(missing_modules) >= 3
        or "recap" in missing_modules
    )
    return {
        "digest_mode": normalized_mode,
        "h2_count": h2_count,
        "heading_titles": cleaned_titles,
        "duplicate_titles": duplicates,
        "generic_titles": generic_titles,
        "missing_modules": missing_modules,
        "needs_agent_repair": needs_agent_repair,
        "needs_scaffold_fallback": needs_scaffold_fallback,
    }


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
    normalized_mode = _normalize_mode(digest_mode)
    heading_plan = _build_scaffold_headings(
        title=title,
        required_elements=required_elements,
        digest_mode=normalized_mode,
    )
    heading_keywords = _heading_keyword_map(normalized_mode)
    min_h2_count = 4 if normalized_mode == "sprint" else 5
    needs_support_pack = _count_headings(cleaned, level=2) < min_h2_count

    missing_blocks: list[str] = []
    if needs_support_pack:
        if not _has_heading_keywords(cleaned, heading_keywords["guide"]):
            guide_block = build_chapter_guide(
                title=title,
                objective=objective,
                required_elements=required_elements,
                digest_mode=normalized_mode,
                source_count=source_count,
                heading=heading_plan["guide"],
            )
            missing_blocks.append(guide_block.strip())
        glossary_block = build_glossary_section(
            analysis_source,
            required_elements=required_elements,
            heading=heading_plan["glossary"],
        )
        if glossary_block and not _has_heading_keywords(cleaned, heading_keywords["glossary"]):
            missing_blocks.append(glossary_block.strip())
        objectives_block = build_learning_objectives_section(
            analysis_source,
            objective=objective,
            required_elements=required_elements,
            heading=heading_plan["objectives"],
        )
        if objectives_block and not _has_heading_keywords(cleaned, heading_keywords["objectives"]):
            missing_blocks.append(objectives_block.strip())

        for key, _heading, block in _build_mode_sections(
            title=title,
            objective=objective,
            required_elements=required_elements,
            digest_mode=normalized_mode,
            chapter_index=chapter_index,
            chapter_count=chapter_count,
            headings=heading_plan,
        ):
            if not _has_heading_keywords(cleaned, heading_keywords.get(key, ())):
                missing_blocks.append(block.strip())

    if missing_blocks:
        cleaned = _insert_after_first_heading(cleaned, "\n\n".join(missing_blocks))

    if not _has_heading_keywords(cleaned, heading_keywords["recap"]):
        recap_block = build_chapter_recap(
            title=title,
            required_elements=required_elements,
            digest_mode=normalized_mode,
            heading=heading_plan["recap"],
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
    heading: str | None = None,
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
        heading or ("## 这一章先看什么" if normalized_mode == "sprint" else "## 本章导读"),
        "",
        f"> [!{note_kind}]",
        f"> 本章目标：{goal_line}",
        f"> 阅读建议：{evidence_line}",
        "",
        "### 先抓住这些内容",
        "",
    ]
    lines.extend(f"- {item}" for item in focus_items)
    return "\n".join(lines).strip()


def build_chapter_recap(
    *,
    title: str,
    required_elements: list[str],
    digest_mode: str,
    heading: str | None = None,
) -> str:
    normalized_mode = _normalize_mode(digest_mode)
    resolved_heading = heading or ("## 快速回顾" if normalized_mode == "sprint" else "## 本章要点")
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
    lines = [resolved_heading, ""]
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
    headings: Mapping[str, str] | None = None,
) -> list[tuple[str, str, str]]:
    normalized_mode = _normalize_mode(digest_mode)
    focus_items = required_elements[:4] or _default_required_elements(normalized_mode)
    focus_text = "、".join(focus_items)
    resolved_headings = dict(headings or _build_scaffold_headings(title=title, required_elements=required_elements, digest_mode=normalized_mode))

    if normalized_mode == "sprint":
        quick_card = [
            f"- 这章最先记住：{focus_items[0]}",
            f"- 这章最常考：{focus_items[1] if len(focus_items) > 1 else '核心题型'}",
            "- 这章最值得临考前再扫一遍的，是步骤和易错点。",
        ]
        return [
            (
                "main",
                resolved_headings["main"],
                "\n".join(
                    [
                        resolved_headings["main"],
                        "",
                        f"- 先明确本章要解决什么问题：{objective or '把本章最关键的考点、条件和解题路径讲清楚。'}",
                        f"- 第一层先讲清：{focus_text}",
                        "- 第二层再讲：这些概念在题目里通常怎样出现，怎样判断能不能用。",
                        "- 第三层再收：哪些结论必须连同条件一起记，哪些地方最容易混淆。",
                    ]
                ).strip(),
            ),
            (
                "drills",
                resolved_headings["drills"],
                "\n".join(
                    [
                        resolved_headings["drills"],
                        "",
                        "1. 先看题眼，判断它在考哪个概念、性质或方法。",
                        "2. 再看条件，确认这道题为什么能走这条解题路径。",
                        "3. 最后把步骤、常见变形和失分点一起归纳。",
                    ]
                ).strip(),
            ),
            (
                "memory",
                resolved_headings["memory"],
                "\n".join([resolved_headings["memory"], "", *quick_card, "- 不要只背公式，要同时背‘什么时候用’和‘不能怎么误用’。"]).strip(),
            ),
            (
                "pitfalls",
                resolved_headings["pitfalls"],
                "\n".join(
                    [
                        resolved_headings["pitfalls"],
                        "",
                        "- 把最像但不一样的概念放在一起对比，不要分开零散记。",
                        "- 做题时先判断条件，再决定方法，不能看到熟词就机械套公式。",
                        "- 如果一个结论看起来很好用，先确认它有没有前提、范围或隐含条件。",
                    ]
                ).strip(),
            ),
        ]

    sections: list[tuple[str, str, str]] = [
        (
            "prereq",
            resolved_headings["prereq"],
            "\n".join(
                [
                    resolved_headings["prereq"],
                    "",
                    f"- 建议先回顾：{focus_items[0]}",
                    f"- 本章会反复调用：{focus_items[1] if len(focus_items) > 1 else '核心定义'}",
                    "- 如果前置概念还不稳，先把定义、符号和基本关系补平。",
                ]
            ).strip(),
        ),
        (
            "motivation",
            resolved_headings["motivation"],
            "\n".join(
                [
                    resolved_headings["motivation"],
                    "",
                    f"{objective or '本章要解决的是：为什么需要这部分知识，它在整门课里承担什么作用。'}",
                    "- 读这一章时，不只要记结论，还要知道它回答了哪个上位问题。",
                ]
            ).strip(),
        ),
        (
            "definitions",
            resolved_headings["definitions"],
            "\n".join(
                [
                    resolved_headings["definitions"],
                    "",
                    f"- 请围绕这些元素组织内容：{focus_text}",
                    "- 若出现定理或公式，必须同时交代定义背景、适用条件、结论含义和使用边界。",
                ]
            ).strip(),
        ),
        (
            "reasoning",
            resolved_headings["reasoning"],
            "\n".join(
                [
                    resolved_headings["reasoning"],
                    "",
                    "- 先说明推理链条，再给出能够落地的例子或应用。",
                    "- 例子最好同时覆盖‘怎么用’‘为什么这样用’和‘容易错在哪’。",
                ]
            ).strip(),
        ),
    ]

    if chapter_index == 1:
        sections.append(
            (
                "map",
                resolved_headings["map"],
                "\n".join(
                    [
                        resolved_headings["map"],
                        "",
                        f"<!-- [MERMAID: {title} 的整体知识脉络图] -->",
                    ]
                ).strip(),
            )
        )
    if chapter_count and chapter_index == chapter_count:
        sections.append(
            (
                "extension",
                resolved_headings["extension"],
                "\n".join(
                    [
                        resolved_headings["extension"],
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
            "先看每章开头，先确认这一章到底在考什么、常见问法是什么，再进入细节。",
            "每章都按“概念讲清楚 -> 题型拆开讲 -> 易错点收口”的顺序读，不要只扫结论。",
            "考前回看时优先扫“典型题型”“易错点”“本章复盘”三块，而不是从头重读。",
        ]
    return [
        "建议按章节顺序阅读，因为后面的推理和应用通常依赖前面建立的定义与结构。",
        "每章优先读懂“定义/结构 -> 推理 -> 例子”这条主线，不要把知识点切碎了记。",
        "每读完一章就回看一次本章总结，确认自己能讲清概念、关系和使用边界，再进入下一章。",
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
    "analyze_chapter_heading_quality",
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
