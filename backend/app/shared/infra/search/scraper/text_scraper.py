"""Compatibility shim for the legacy `search.scraper.text_scraper` module."""

from app.shared.infra.search.readers.text_scraper import TextScraper

__all__ = ["TextScraper"]
