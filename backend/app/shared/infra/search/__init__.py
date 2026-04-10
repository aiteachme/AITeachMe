"""Search helpers exposed to the rest of the app."""

from .context_compression import ContextCompressor, ContextManager
from .factory import get_reader_for_url, get_retriever, get_retrievers_for_subject, get_scraper_for_url
from .source_curation import SourceCurator
from .types import ScrapedPage, SearchResult, WebSearchResult

__all__ = [
    "ContextCompressor",
    "ContextManager",
    "ScrapedPage",
    "SearchResult",
    "SourceCurator",
    "WebSearchResult",
    "get_reader_for_url",
    "get_retriever",
    "get_retrievers_for_subject",
    "get_scraper_for_url",
]
