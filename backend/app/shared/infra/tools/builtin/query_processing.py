"""Query helpers for docgen research planning and retrieval."""

from __future__ import annotations

EDUCATION_SITE_FILTERS: dict[str, list[str]] = {
    "zh": [
        "site:zhihu.com",
        "site:csdn.net",
        "site:mathworld.wolfram.com",
    ],
    "university": [
        "site:icourse163.org",
        "site:xuetangx.com",
        "site:ocw.mit.edu",
    ],
    "exam": [
        "site:kaoyan.com",
        "site:233.com",
        "真题 解析",
    ],
    "knowledge": [
        "site:wikipedia.org",
        "site:baike.baidu.com",
        "site:mathworld.wolfram.com",
    ],
}


def dedupe_queries(queries: list[str], *, limit: int | None = None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_query in queries:
        query = " ".join(str(raw_query or "").split()).strip()
        if not query or query in seen:
            continue
        seen.add(query)
        cleaned.append(query)
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned



def enrich_queries_for_education(
    queries: list[str],
    *,
    domain: str = "zh",
    max_site_filters_per_query: int = 1,
) -> list[str]:
    normalized_queries = dedupe_queries(queries)
    filters = EDUCATION_SITE_FILTERS.get(domain, [])[: max(0, max_site_filters_per_query)]
    enriched: list[str] = []
    seen: set[str] = set()
    for query in normalized_queries:
        for candidate in [query, *[f"{query} {site_filter}".strip() for site_filter in filters]]:
            if candidate in seen:
                continue
            seen.add(candidate)
            enriched.append(candidate)
    return enriched



def build_research_focus_text(
    *,
    title: str,
    objective: str = "",
    required_elements: list[str] | None = None,
    digest_mode: str = "",
) -> str:
    parts: list[str] = []
    normalized_title = str(title or "").strip()
    normalized_objective = str(objective or "").strip()
    normalized_required = [str(item).strip() for item in required_elements or [] if str(item).strip()]
    normalized_mode = str(digest_mode or "").strip()

    if normalized_title:
        parts.append(f"章节：{normalized_title}")
    if normalized_objective:
        parts.append(f"目标：{normalized_objective}")
    if normalized_required:
        parts.append("必须覆盖：" + "、".join(normalized_required))
    if normalized_mode:
        parts.append(f"模式：{normalized_mode}")
    return " | ".join(parts).strip()


__all__ = [
    "EDUCATION_SITE_FILTERS",
    "build_research_focus_text",
    "dedupe_queries",
    "enrich_queries_for_education",
]
