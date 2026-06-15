"""Digest pedagogy helpers for learning-document assembly and scaffolding."""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.shared.infra.observability.trace import traceable_with_context as traceable


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
_COURSE_SLUG_RE = re.compile(r"^(?:course|subj)_[a-z0-9_-]+$", re.IGNORECASE)
_MALFORMED_HEADING_TAIL_RE = re.compile(r"[与及和的、，,：:]$")


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
    mode_label = "紧凑节奏" if normalized_mode == "sprint" else "系统节奏"
    required_text = "、".join(item for item in required_elements if item.strip()) or "未提供"
    query_text = "；".join(item for item in search_queries if item.strip()) or "未提供"
    source_text = "\n".join(f"- {item}" for item in source_titles if item.strip()) or "- 未提供"
    system_prompt = """
你是 AITeachMe 的课程命名助手。
你的任务是根据教学合同和研究结果，为单个章节生成自然、具体、可扫读的中文标题。
标题基于上下文语义判断，聚焦本章知识对象、方法任务或应用场景。
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
- 短、具体、像真实目录，离开上下文也能看懂。
- 标题聚焦知识对象、方法任务、题型技能或应用场景。
- 保留必要限定词，避免长串枚举和固定句式。

输出要求：
1. 只输出一个中文标题。
2. 标题要短，通常 4-12 个中文字符。
3. 标题要像真实讲义章节名，让学生一眼知道这一章讲什么。
4. 如果来源标题带编号，只保留语义标题。
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
    plan: str,
    source_strategy: str = "",
    chapters: list[Mapping[str, object]],
) -> str:
    """构建知识文档开头的总览页。"""

    del plan
    normalized_mode = _normalize_mode(digest_mode)
    mode_label = "紧凑节奏" if normalized_mode == "sprint" else "系统节奏"
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


def _singleton_subheading_paths(markdown: str) -> list[str]:
    """Return H2 > H3 paths where the H2 has exactly one direct H3 child."""

    stripped_markdown = _CODE_FENCE_RE.sub("", markdown or "")
    paths: list[str] = []
    current_h2 = ""
    current_h3_children: list[str] = []

    def flush_current_h2() -> None:
        if current_h2 and len(current_h3_children) == 1:
            paths.append(f"{current_h2} > {current_h3_children[0]}")

    for hashes, raw_title in _HEADING_RE.findall(stripped_markdown):
        level = len(hashes)
        if level <= 2:
            flush_current_h2()
            current_h2 = clean_generated_chapter_title(raw_title) if level == 2 else ""
            current_h3_children = []
            continue
        if level == 3 and current_h2:
            cleaned_h3 = clean_generated_chapter_title(raw_title)
            if cleaned_h3:
                current_h3_children.append(cleaned_h3)

    flush_current_h2()
    return paths


def _generic_heading_titles(titles: list[str]) -> list[str]:
    generic: list[str] = []
    for title in titles:
        cleaned = clean_generated_chapter_title(title)
        if not cleaned:
            continue
        if cleaned in _UNUSABLE_CHAPTER_TITLES:
            generic.append(cleaned)
    return list(dict.fromkeys(generic))


def _malformed_heading_titles(titles: list[str]) -> list[str]:
    """Detect malformed heading shapes without maintaining semantic wordlists."""

    malformed: list[str] = []
    for title in titles:
        cleaned = clean_generated_chapter_title(title)
        if not cleaned:
            continue
        if cleaned in _UNUSABLE_CHAPTER_TITLES:
            continue
        if _MALFORMED_HEADING_TAIL_RE.search(cleaned):
            malformed.append(cleaned)
    return list(dict.fromkeys(malformed))


def analyze_chapter_heading_quality(markdown: str, *, digest_mode: str) -> dict[str, object]:
    normalized_mode = _normalize_mode(digest_mode)
    heading_titles = _extract_heading_titles(markdown, min_level=2, max_level=3)
    cleaned_titles = [clean_generated_chapter_title(title) for title in heading_titles if clean_generated_chapter_title(title)]
    duplicates = list(dict.fromkeys(title for title in cleaned_titles if cleaned_titles.count(title) > 1))
    generic_titles = _generic_heading_titles(cleaned_titles)
    malformed_titles = _malformed_heading_titles(cleaned_titles)
    singleton_subheading_paths = _singleton_subheading_paths(markdown)
    missing_modules: list[str] = []
    min_h2_count = 3 if normalized_mode == "sprint" else 4
    h2_count = _count_headings(markdown, level=2)
    force_model_heading_review = normalized_mode == "sprint"
    needs_agent_repair = bool(
        force_model_heading_review
        or h2_count < min_h2_count
        or duplicates
        or generic_titles
        or malformed_titles
        or singleton_subheading_paths
    )
    needs_scaffold_fallback = False
    return {
        "digest_mode": normalized_mode,
        "h2_count": h2_count,
        "heading_titles": cleaned_titles,
        "duplicate_titles": duplicates,
        "generic_titles": generic_titles,
        "malformed_titles": malformed_titles,
        "singleton_subheading_paths": singleton_subheading_paths,
        "missing_modules": missing_modules,
        "force_model_heading_review": force_model_heading_review,
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
    """Normalize only the chapter shell; semantic scaffold must come from LLM repair."""

    cleaned = (markdown or "").strip()
    if not cleaned.startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}".strip()
    return cleaned.rstrip() + "\n"


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
    del title, objective, required_elements, digest_mode, chapter_index, chapter_count, headings
    return []


def _normalize_mode(digest_mode: str) -> str:
    return (digest_mode or "systematic").strip().lower()


__all__ = [
    "build_chapter_title_resolution_messages",
    "analyze_chapter_heading_quality",
    "clean_generated_chapter_title",
    "coerce_resolved_chapter_title",
    "build_document_overview",
    "ensure_chapter_learning_scaffold",
    "is_usable_resolved_chapter_title",
    "resolve_effective_chapter_title",
]
