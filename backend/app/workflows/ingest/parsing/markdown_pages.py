"""Shared helpers for page-marked markdown."""

from __future__ import annotations

import re

from pydantic import BaseModel

PAGE_MARKER_RE = re.compile(r"(?m)^<!-- page:(?P<page>\d+) -->\s*$")


class MarkdownPageSection(BaseModel):
    """One markdown section associated with a PDF page."""

    page_number: int
    marker: str
    body: str


def split_markdown_pages(markdown: str) -> list[MarkdownPageSection]:
    """Split markdown into page sections using HTML page markers."""

    matches = list(PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        return []

    sections: list[MarkdownPageSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(
            MarkdownPageSection(
                page_number=int(match.group("page")),
                marker=match.group(0),
                body=markdown[start:end],
            )
        )
    return sections


def join_markdown_pages(sections: list[MarkdownPageSection]) -> str:
    """Join page sections back into one markdown string."""

    parts: list[str] = []
    for section in sections:
        parts.append(section.marker)
        parts.append(section.body)

    markdown = "\n".join(part.rstrip("\n") for part in parts).strip()
    if markdown and not markdown.endswith("\n"):
        markdown = f"{markdown}\n"
    return markdown
