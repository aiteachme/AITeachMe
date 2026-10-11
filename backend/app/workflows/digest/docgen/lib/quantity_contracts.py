"""Deterministic Markdown checks for explicit, LLM-interpreted quantities."""

from __future__ import annotations

from markdown_it import MarkdownIt

from app.workflows.digest.docgen.lib.models import ChapterQuantityConstraints
from app.workflows.digest.docgen.lib.unit_tests import unit_test_structure_issues


class ChapterQuantityContractError(RuntimeError):
    """Raised when final publication formatting violates explicit quantities."""


def explicit_chapter_structure_issues(
    markdown: str,
    quantities: ChapterQuantityConstraints,
    *,
    include_unit_test: bool = False,
) -> list[str]:
    """Count Markdown structure, leaving examples and prose length to semantic review."""

    issues: list[str] = []
    if quantities.body_section_count is not None:
        tokens = MarkdownIt("commonmark").parse(markdown)
        section_count = sum(
            token.type == "heading_open" and token.tag == "h2" and token.level == 0
            and tokens[index + 1].content != "单元测试"
            for index, token in enumerate(tokens)
        )
        if section_count != quantities.body_section_count:
            issues.append(f"正文必须恰好有 {quantities.body_section_count} 个二级小节，当前为 {section_count} 个。")
    if include_unit_test and quantities.chapter_end_question_count is not None:
        issues.extend(unit_test_structure_issues(
            markdown, expected_question_count=quantities.chapter_end_question_count,
        ))
    # Raw Markdown character counts include code and markup; they cannot
    # validate a natural-language word range or count semantic teaching examples.
    return issues
