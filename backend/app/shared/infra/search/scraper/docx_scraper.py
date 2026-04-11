"""Compatibility shim for the legacy `search.scraper.docx_scraper` module."""

from app.shared.infra.search.readers.docx_scraper import DOCXScraper, extract_docx_text

__all__ = ["DOCXScraper", "extract_docx_text"]
