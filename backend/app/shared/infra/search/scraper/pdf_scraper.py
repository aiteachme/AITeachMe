"""Compatibility shim for the legacy `search.scraper.pdf_scraper` module."""

from app.shared.infra.search.readers.pdf_scraper import PDFScraper

__all__ = ["PDFScraper"]
