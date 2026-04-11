"""Compatibility shim for the legacy `search.scraper.common` module."""

from app.shared.infra.search.readers.common import (
    build_error_page,
    extract_core_title,
    extract_paragraphs_from_xml,
    fetch_url,
    normalize_scraped_text,
    open_zip_archive,
)

__all__ = [
    "build_error_page",
    "extract_core_title",
    "extract_paragraphs_from_xml",
    "fetch_url",
    "normalize_scraped_text",
    "open_zip_archive",
]
