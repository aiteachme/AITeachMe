"""Compatibility shim for the legacy `search.scraper.base` module."""

from app.shared.infra.search.readers.base import (
    BaseReader,
    BaseScraper,
    get_registered_reader_names,
    get_registered_reader_types,
    register_reader_type,
)

__all__ = [
    "BaseReader",
    "BaseScraper",
    "get_registered_reader_names",
    "get_registered_reader_types",
    "register_reader_type",
]
