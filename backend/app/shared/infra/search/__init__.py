"""Stable package exports for the shared search stack.

`search` is intentionally broader than local RAG:
- retrievers discover candidate sources
- readers load URL content (with legacy scraper aliases)
- knowledge retrieval searches the local subject corpus
"""

from .api import get_knowledge_search_notice, search_knowledge, web_search
from .context_compression import ContextCompressor, ContextManager
from .factory import (
    get_external_retriever_names,
    get_reader_for_url,
    get_retriever,
    get_retrievers_for_subject,
    get_scraper_for_url,
)
from .knowledge import RetrievalConfig, RetrievalPipeline, RetrievedChunk, rerank_chunks
from .retrievers import get_registered_retriever_names
from .readers import get_registered_reader_names
from .source_curation import SourceCurator
from .types import ScrapedPage, SearchResult, WebSearchResult

__all__ = [
    "ContextCompressor",
    "ContextManager",
    "RetrievalConfig",
    "RetrievalPipeline",
    "RetrievedChunk",
    "ScrapedPage",
    "SearchResult",
    "SourceCurator",
    "WebSearchResult",
    "get_external_retriever_names",
    "get_registered_reader_names",
    "get_registered_retriever_names",
    "get_reader_for_url",
    "get_knowledge_search_notice",
    "get_retriever",
    "get_retrievers_for_subject",
    "get_scraper_for_url",
    "rerank_chunks",
    "search_knowledge",
    "web_search",
]



