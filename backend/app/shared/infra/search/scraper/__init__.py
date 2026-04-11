"""Compatibility shim for the legacy `search.scraper` namespace."""

from app.shared.infra.search.readers import (
    BS4Scraper,
    DOCXScraper,
    PDFScraper,
    PPTXScraper,
    TextScraper,
    BaseReader,
    BaseScraper,
    get_registered_reader_names,
    get_registered_reader_types,
    register_reader_type,
)

__all__ = [
    "BaseReader",
    "BaseScraper",
    "BS4Scraper",
    "DOCXScraper",
    "PDFScraper",
    "PPTXScraper",
    "TextScraper",
    "get_registered_reader_names",
    "get_registered_reader_types",
    "register_reader_type",
]
