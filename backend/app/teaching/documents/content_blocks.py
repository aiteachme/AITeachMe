"""Teaching-oriented document support blocks built on reusable infra helpers."""

from __future__ import annotations

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


__all__ = [
    "build_glossary_section",
    "build_learning_objectives_section",
]
