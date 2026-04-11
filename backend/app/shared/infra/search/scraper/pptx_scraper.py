"""Compatibility shim for the legacy `search.scraper.pptx_scraper` module."""

from app.shared.infra.search.readers.pptx_scraper import PPTXScraper, extract_pptx_text

__all__ = ["PPTXScraper", "extract_pptx_text"]
