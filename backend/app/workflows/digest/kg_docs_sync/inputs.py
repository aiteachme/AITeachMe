"""Knowledge-doc sync input resolvers."""

from __future__ import annotations

import re

from sqlmodel import Session

from app.repositories.knowledge.docgen_repo import get_current_published_docs
from app.shared.infra.database import managed_session
from app.shared.infra.tools.builtin.markdown_processing import normalize_mermaid_blocks

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")


def _clean_heading_title(raw: str) -> str:
    title = re.sub(r"\{#ku_[\w-]+\}", "", raw).strip()
    title = re.sub(r"<!--\s*ATM_KU:\s*ku_[\w-]+\s*-->", "", title).strip()
    title = re.sub(r"\[(type|prerequisite|related):[^\]]+\]", "", title, flags=re.IGNORECASE).strip()
    return title


def extract_doc_chapter_metadatas(markdown: str) -> list[dict[str, object]]:
    lines = markdown.splitlines()
    chapters: list[dict[str, object]] = []
    current_title: str | None = None
    current_content: list[str] = []

    def _flush() -> None:
        nonlocal current_title, current_content
        if not current_title:
            return
        summary = " ".join(
            segment.strip()
            for segment in current_content
            if segment.strip() and not segment.strip().startswith("#")
        ).strip()
        if len(summary) > 1200:
            summary = summary[:1200].rstrip() + "..."
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": current_title,
                "summary": summary,
                "research_summary": "",
                "tags": [],
                "source_file_ids": [],
            }
        )
        current_title = None
        current_content = []

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            title = _clean_heading_title(match.group("title"))
            if title:
                _flush()
                current_title = title
            continue
        if current_title:
            current_content.append(line)
    _flush()
    return chapters[:60]


def _merge_current_doc_markdown(session: Session, subject: str) -> str:
    docs = get_current_published_docs(session, subject)
    parts = [
        normalize_mermaid_blocks(
            str(doc.markdown_content or doc.content_markdown or "").strip()
        )
        for doc in docs
        if str(doc.markdown_content or doc.content_markdown or "").strip()
    ]
    if not parts:
        return ""
    return ("\n\n---\n\n".join(parts)).strip()


def load_knowledge_doc_markdown(subject: str) -> tuple[str, str]:
    with managed_session() as session:
        merged = _merge_current_doc_markdown(session, subject).strip()
    if merged:
        return merged, "database"
    return "", "none"


def resolve_graph_input_paths(*, file_ids: list[int], knowledge_doc_markdown: str) -> list[str]:
    paths: list[str] = []
    if file_ids:
        paths.append("chunks")
    if knowledge_doc_markdown.strip():
        paths.append("knowledge_doc")
    return paths or ["chunks"]


__all__ = [
    "extract_doc_chapter_metadatas",
    "load_knowledge_doc_markdown",
    "resolve_graph_input_paths",
]
