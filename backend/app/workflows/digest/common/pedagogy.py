"""Digest pedagogy helpers for learning-document assembly and scaffolding."""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.shared.infra.observability.trace import traceable_with_context as traceable
from app.shared.infra.tools.builtin.content_analysis import (
    build_term_coverage,
    extract_key_terms,
    extract_term_excerpts,
    find_missing_terms,
)


def build_glossary_section(
    markdown: str,
    *,
    required_elements: list[str],
    heading: str = "## 术语速览",
    max_terms: int = 6,
) -> str:
    """Build a compact glossary block from generated chapter content."""

    terms = extract_key_terms(
        markdown,
        seed_terms=required_elements,
        limit=max_terms,
    )
    if not terms:
        return ""

    excerpts = extract_term_excerpts(markdown, terms, excerpt_char_limit=72)
    lines = [
        heading,
        "",
        "| 术语 | 快速理解 |",
        "| --- | --- |",
    ]
    for term in terms:
        explanation = excerpts.get(term) or "建议在正文中补充该术语的定义、用途或一个直观例子。"
        lines.append(f"| {term} | {explanation} |")
    return "\n".join(lines).strip()


def build_learning_objectives_section(
    markdown: str,
    *,
    objective: str,
    required_elements: list[str],
    heading: str = "## 学习目标对照",
) -> str:
    """Summarize whether the chapter already covers the planned required elements."""

    cleaned_required = [str(item).strip() for item in required_elements if str(item).strip()]
    if not objective.strip() and not cleaned_required:
        return ""

    coverage_rows = build_term_coverage(markdown, cleaned_required)
    missing_terms = find_missing_terms(markdown, cleaned_required)
    lines = [heading, ""]
    if objective.strip():
        lines.append(f"- 本章目标：{objective.strip()}")
    if coverage_rows:
        covered_count = sum(1 for item in coverage_rows if bool(item["covered"]))
        lines.append(f"- 当前覆盖：{covered_count}/{len(coverage_rows)} 个重点要素")
        for item in coverage_rows:
            status_label = "已覆盖" if bool(item["covered"]) else "待补强"
            lines.append(f"- {status_label}：{item['term']}")
    else:
        lines.append("- 当前没有显式配置必备要点，建议围绕目标检查定义、方法和例子是否完整。")
    if missing_terms:
        lines.append(f"- 建议补充：{'、'.join(missing_terms[:4])}")
    return "\n".join(lines).strip()


_TITLE_NUMBER_TOKEN_RE = r"(?:\d+(?:\.\d+)*|[一二三四五六七八九十百千万]+|[ivxlcdm]+)"
_TITLE_CHAPTER_PREFIX_RE = re.compile(
    rf"^\s*第\s*{_TITLE_NUMBER_TOKEN_RE}\s*[章节讲节篇部分]\s*[.)）．、:：\s]*",
    re.IGNORECASE,
)
_TITLE_OUTLINE_PREFIX_RE = re.compile(
    rf"^\s*(?:[（(]\s*{_TITLE_NUMBER_TOKEN_RE}\s*[)）]\s*[.)）．、:：\s]*|"
    rf"{_TITLE_NUMBER_TOKEN_RE}(?:\s*[.)）．、:：]\s*|\s+))",
    re.IGNORECASE,
)
_UNUSABLE_CHAPTER_TITLES = {
    "未命名",
    "未命名章节",
    "本章",
    "本章内容",
    "本章目标",
    "当前章节",
    "章节目标",
    "学习目标",
    "Untitled",
    "Untitled Chapter",
}
_TITLE_ONLY_NUMBER_RE = re.compile(
    r"^(?:(?:第\s*)?(?:\d+(?:\.\d+)*|[一二三四五六七八九十百千万]+|[ivxlcdm]+)\s*(?:[章节讲节篇部分])?|chapter\s*\d+)$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_KU_ANCHOR_RE = re.compile(r"(?:\{#ku_[\w-]+\}|<!--\s*ATM_KU:\s*ku_[\w-]+\s*-->)")
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_COURSE_SLUG_RE = re.compile(r"^(?:course|subj)_[a-z0-9_-]+$", re.IGNORECASE)
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
    "guide": ("重点结构", "考点结构", "知识结构", "核心问题", "主线"),
    "glossary": ("术语", "概念", "名词"),
    "objectives": ("结论", "方法", "掌握", "目标"),
    "main": ("高价值任务", "高频考法", "考法", "抓手", "重点", "核心"),
    "drills": ("典型任务", "典型例题", "例题", "题型", "解析"),
    "memory": ("关键结论", "公式", "判定", "速查", "结论"),
    "pitfalls": ("易错", "误区", "陷阱", "边界"),
    "recap": ("核心总结", "小结", "总结"),
}
_SYSTEMATIC_HEADING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "guide": ("知识结构", "核心问题", "主线", "框架"),
    "glossary": ("术语", "概念", "名词"),
    "objectives": ("结论", "方法", "目标", "掌握"),
    "prereq": ("前置基础", "前置", "准备", "基础"),
    "motivation": ("解决的问题", "动机", "问题"),
    "definitions": ("定义", "定理", "结构", "框架"),
    "reasoning": ("推理与应用", "推理", "应用", "证明"),
    "map": ("课程位置", "位置", "地图", "全局"),
    "extension": ("延伸应用", "延伸", "进阶"),
    "recap": ("核心总结", "小结", "总结"),
}


def clean_generated_chapter_title(raw_title: str) -> str:
    cleaned = str(raw_title or "").strip()
    cleaned = cleaned.strip().strip("“”\"'`")
    for _ in range(3):
        next_cleaned = _TITLE_CHAPTER_PREFIX_RE.sub("", cleaned, count=1)
        next_cleaned = _TITLE_OUTLINE_PREFIX_RE.sub("", next_cleaned, count=1).strip()
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip("：:，,。；; ")


def is_usable_resolved_chapter_title(title: str) -> bool:
    cleaned = clean_generated_chapter_title(title)
    if cleaned in _UNUSABLE_CHAPTER_TITLES:
        return False
    if len(cleaned) < 3 or len(cleaned) > 36:
        return False
    if not re.search(r"[\u3400-\u9fffA-Za-z]", cleaned):
        return False
    if _TITLE_ONLY_NUMBER_RE.fullmatch(cleaned):
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
    if is_usable_resolved_chapter_title(provisional_title):
        return provisional_title

    cleaned_fallback = clean_generated_chapter_title(str(fallback_title or ""))
    if is_usable_resolved_chapter_title(cleaned_fallback):
        return cleaned_fallback

    if chapter_index is None:
        chapter_index = int(chapter_data.get("chapter_index", 0) or 0) or None
    return f"第 {chapter_index} 章" if chapter_index else ""


def coerce_resolved_chapter_title(
    raw_title: str,
    *,
    chapter: Mapping[str, object] | None = None,
    chapter_index: int | None = None,
) -> str:
    cleaned = clean_generated_chapter_title(raw_title)
    current_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
    if is_usable_resolved_chapter_title(cleaned):
        return cleaned
    return current_title


@traceable(name="teaching.chapter_title_resolution_prompt", run_type="prompt")
def build_chapter_title_resolution_messages(
    *,
    course_name: str,
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
    mode_label = "快速复习" if normalized_mode == "sprint" else "系统学习"
    required_text = "、".join(item for item in required_elements if item.strip()) or "未提供"
    query_text = "；".join(item for item in search_queries if item.strip()) or "未提供"
    source_text = "\n".join(f"- {item}" for item in source_titles if item.strip()) or "- 未提供"
    system_prompt = """
你是 AITeachMe 的课程命名助手。
你的任务是根据教学合同和研究结果，为单个章节生成自然、具体、可扫读的中文标题。
标题必须由你基于上下文判断生成，不要从固定词表、关键词抽取或字符串拼接中凑出来。
你只输出一个标题，不输出解释、编号或 Markdown。
""".strip()
    user_prompt = f"""
请为下面这一章生成一个新的中文章节标题。

主题：{course_name}
课程模式：{mode_label}
学习目标：{objective or "把本章最核心的知识主线讲清楚。"}
必须覆盖：{required_text}
检索重点：{query_text}
写作要求：{writing_instructions or "保持教学导向，体现知识脉络。"}
证据概况：本地命中 {local_hits} 条，外部命中 {web_hits} 条。

来源线索：
{source_text}

研究笔记：
{dense_context or "暂无研究笔记，请根据学习大纲稳健命名。"}

风格参考：
- 好标题示例：洛必达法则、等价无穷小替换、分部积分、闭区间最值、矩阵分解。
- 这些只是长度和清晰度示例，不是候选词表；请按本章真实语义重新命名。
- 避免“核心概念”“方法总结”“章节目标”这类离开上下文看不懂的标题。

输出要求：
1. 只输出一个中文标题。
2. 标题要短，通常 4-12 个中文字符；不要写冒号副标题或长串枚举。
3. 标题要像真实讲义章节名，让学生一眼知道这一章讲什么。
4. 不要输出编号、解释或 Markdown；如果来源标题带编号，只保留语义标题。
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_document_overview(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    source_strategy: str = "",
    chapters: list[Mapping[str, object]],
) -> str:
    """构建知识文档开头的总览页。"""

    normalized_mode = _normalize_mode(digest_mode)
    mode_label = "快速复习" if normalized_mode == "sprint" else "系统学习"
    display_course = _resolve_course_name(course_name)
    deduped_chapters = _dedupe_chapters_for_overview(chapters)
    goal_line = user_prompt.strip() or f"围绕 {display_course} 生成一份结构化学习文档。"
    chapter_count = len(deduped_chapters)
    scope_line = _build_overview_scope(deduped_chapters)

    lines = [
        "# 知识文档总览",
        "",
        (
            f"这份讲义围绕《{display_course}》展开，按 {mode_label} 方式组织内容，"
            f"共 {chapter_count} 章。"
            if chapter_count > 0
            else f"这份讲义围绕《{display_course}》展开，按 {mode_label} 方式组织内容。"
        ),
        "",
        f"学习目标：{goal_line}",
    ]
    if scope_line:
        lines.extend(["", f"重点覆盖：{scope_line}"])

    return "\n".join(lines).strip() + "\n"


def _build_overview_scope(chapters: list[Mapping[str, object]], *, max_items: int = 5) -> str:
    titles: list[str] = []
    for chapter in chapters:
        chapter_index = int(chapter.get("chapter_index", 0) or 0)
        title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index).strip()
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= max_items:
            break
    if not titles:
        return ""
    if len(chapters) > max_items:
        return "、".join(titles) + " 等主题"
    return "、".join(titles)


def _resolve_course_name(course_name: str) -> str:
    normalized = str(course_name or "").strip()
    if normalized and not _COURSE_SLUG_RE.fullmatch(normalized):
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
            return f"先讲清 {tags[0]}，再落到常见任务/题型与易错点"
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


def _generic_heading_titles(titles: list[str]) -> list[str]:
    generic: list[str] = []
    for title in titles:
        cleaned = clean_generated_chapter_title(title)
        if not cleaned:
            continue
        if cleaned in _GENERIC_FOCUS_TERMS or cleaned in _UNUSABLE_CHAPTER_TITLES:
            generic.append(cleaned)
    return list(dict.fromkeys(generic))


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
            "guide": f"## {focus}的重点结构",
            "glossary": f"## {focus}的核心概念",
            "objectives": f"## {focus}要掌握的结论与方法",
            "main": f"## {focus}的高价值任务与考法",
            "drills": f"## {focus}的典型任务与例题解析",
            "memory": f"## {focus}的关键结论与判定速查",
            "pitfalls": f"## {focus}的易错点辨析",
            "recap": f"## {focus}的核心总结",
        }
    return {
        "guide": f"## {focus}的知识结构",
        "glossary": f"## {focus}的关键概念",
        "objectives": f"## {focus}的核心结论与方法",
        "prereq": f"## {focus}的前置基础",
        "motivation": f"## {focus}要解决的问题",
        "definitions": f"## {focus}的定义与结构",
        "reasoning": f"## {focus}的推理与应用",
        "map": f"## {focus}在课程中的位置",
        "extension": f"## {focus}的延伸应用",
        "recap": f"## {focus}的核心总结",
    }


def analyze_chapter_heading_quality(markdown: str, *, digest_mode: str) -> dict[str, object]:
    normalized_mode = _normalize_mode(digest_mode)
    heading_titles = _extract_heading_titles(markdown, min_level=2, max_level=3)
    cleaned_titles = [clean_generated_chapter_title(title) for title in heading_titles if clean_generated_chapter_title(title)]
    duplicates = list(dict.fromkeys(title for title in cleaned_titles if cleaned_titles.count(title) > 1))
    generic_titles = _generic_heading_titles(cleaned_titles)
    missing_modules: list[str] = []
    min_h2_count = 3 if normalized_mode == "sprint" else 4
    h2_count = _count_headings(markdown, level=2)
    needs_agent_repair = bool(
        h2_count < min_h2_count
        or duplicates
        or generic_titles
    )
    needs_scaffold_fallback = bool(
        h2_count < 2
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
    needs_support_pack = _count_headings(cleaned, level=2) < 2

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
        "先看高频入口和速查表，再用例题解析、变式和易错边界检查能不能真的会用。"
        if normalized_mode == "sprint"
        else "先理解本章在整体知识中的位置，再进入定义、推理和应用。"
    )

    lines = [
        heading or ("## 核心重点结构" if normalized_mode == "sprint" else "## 知识结构"),
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
    resolved_heading = heading or ("## 核心总结" if normalized_mode == "sprint" else "## 本章小结")
    items = required_elements[:3] or _default_required_elements(normalized_mode)
    prompts = (
        [
            f"不看现成结论，试着用一句话讲清楚《{title}》的核心意思。",
            f"把“{items[0]}”和一个典型任务/题型或常见解法对应起来。",
            "说出一个最容易在真实练习或应用中出错的点，并解释为什么。",
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
        first_focus = focus_items[0]
        second_focus = focus_items[1] if len(focus_items) > 1 else "核心任务/题型"
        quick_table = [
            "| 复习入口 | 先看什么 | 不能忽略什么 |",
            "| --- | --- | --- |",
            f"| {first_focus} | 定义和适用条件 | 适用范围和反例 |",
            f"| {second_focus} | 题目或任务给出的条件 | 单位、方向、边界条件 |",
            "| 例题/任务 | 题目给出的对象和目标 | 不要看到熟词就机械套方法 |",
        ]
        return [
            (
                "main",
                resolved_headings["main"],
                "\n".join(
                    [
                        resolved_headings["main"],
                        "",
                        f"- 本章要解决的问题：{objective or '把本章最关键的主题、条件和处理路径讲清楚。'}",
                        f"- 高频入口：{focus_text}",
                        "- 读法：先看题目或任务目标，再选方法，最后检查适用条件和易错边界。",
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
                        "1. **条件**：先圈出题目或任务给出的对象、条件和目标。",
                        "2. **方法**：再选择本章对应的定义、结论、公式或操作步骤。",
                        "3. **检查**：最后回到原条件，检查范围、方向、单位或边界是否被破坏。",
                    ]
                ).strip(),
            ),
            (
                "memory",
                resolved_headings["memory"],
                "\n".join(
                    [
                        resolved_headings["memory"],
                        "",
                        *quick_table,
                        "",
                        "- 不要只背结论，要同时背“什么时候用”和“不能怎么误用”。",
                    ]
                ).strip(),
            ),
            (
                "pitfalls",
                resolved_headings["pitfalls"],
                "\n".join(
                    [
                        resolved_headings["pitfalls"],
                        "",
                        "- 把最像但不一样的概念放在一起对比，不要分开零散记。",
                        "- 处理任务或练习时先判断条件，再决定方法，不能看到熟词就机械套结论。",
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
                        f"- 先把《{title}》看成本门内容的入口，确认它要连接哪些概念和方法。",
                        "- 再顺着后续章节回看这一章，判断哪些定义、符号或思路会被反复调用。",
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
                        "- 复习全文时，优先串联核心定义、关键推理和典型应用。",
                        "- 如果继续深入，建议按“基础定义 -> 关键方法 -> 综合问题”继续扩展。",
                    ]
                ).strip(),
            )
        )
    return sections


def _default_required_elements(digest_mode: str) -> list[str]:
    if digest_mode == "sprint":
        return ["核心概念", "任务/题型抓手", "常见陷阱"]
    return ["定义", "推理链条", "例题"]


def _reading_guidance(digest_mode: str) -> list[str]:
    if digest_mode == "sprint":
        return [
            "先看每章开头，先确认这一章要解决什么、常见问法/任务是什么，再进入细节。",
            "每章都按“概念讲清楚 -> 任务/题型拆开讲 -> 易错点收口”的顺序读，不要只扫结论。",
            "快速复习时优先扫“典型任务/题型”“易错点”“核心总结”三块，而不是从头重读。",
        ]
    return [
        "建议按章节顺序阅读，因为后面的推理和应用通常依赖前面建立的定义与结构。",
        "每章优先读懂“定义/结构 -> 推理 -> 例子”这条主线，不要把知识点切碎了记。",
        "每读完一章就整理一次本章总结，确认自己能讲清概念、关系和使用边界，再进入下一章。",
    ]


def _chapter_focus(chapter: Mapping[str, object]) -> str:
    tags = [str(item).strip() for item in chapter.get("tags", []) if str(item).strip()]
    if tags:
        return "、".join(_plain_overview_text(item, max_length=28) for item in tags[:3] if _plain_overview_text(item, max_length=28))
    summary = str(chapter.get("summary") or "").strip()
    if summary:
        return _plain_overview_text(summary, max_length=120)
    return "核心概念、推理链路与典型例子"


def _plain_overview_text(value: str, *, max_length: int = 120) -> str:
    text = str(value or "")
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _KU_ANCHOR_RE.sub(" ", text)
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", " ", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`>\[\]\|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;|-")
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip(" ：:，,。；;|-") + "..."


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


def _default_plan_summary(*, course_name: str, digest_mode: str, chapters: list[Mapping[str, object]]) -> str:
    mode_label = "快速复习" if digest_mode == "sprint" else "系统学习"
    return f"围绕 {course_name} 设计的一条 {mode_label} 学习路径，共 {len(chapters)} 章。"


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
    "build_glossary_section",
    "build_learning_objectives_section",
    "clean_generated_chapter_title",
    "coerce_resolved_chapter_title",
    "build_document_overview",
    "ensure_chapter_learning_scaffold",
    "is_usable_resolved_chapter_title",
    "resolve_effective_chapter_title",
]
