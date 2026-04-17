"""Support helpers for docs-sync workflow."""

from __future__ import annotations


def normalize_docs_sync_inputs(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
) -> tuple[str, str, int | None]:
    return subject.strip(), markdown or "", build_revision_no


__all__ = ["normalize_docs_sync_inputs"]

