"""Runtime feature switches for ingest parsers."""

from __future__ import annotations

from app.shared.infra.env_support import get_env_bool


def builtin_pdf_parsing_enabled() -> bool:
    return get_env_bool("AITEACHME_ENABLE_BUILTIN_PDF", True)

