"""Stable package exports for the shared search stack.

`search` is intentionally broader than local RAG:
- retrievers discover candidate sources
- readers load URL content
- knowledge retrieval searches the local subject corpus
- llamaindex_adapter bridges to LlamaIndex components
"""

from .api import get_knowledge_search_notice, search_knowledge, web_search
from .cache import (
    get_compression_runtime_cache,
    get_reader_runtime_cache,
    get_retriever_runtime_cache,
    reset_search_runtime_caches,
)
from .context_compression import ContextCompressor, ContextManager
from .factory import (
    get_external_retriever_names,
    get_reader_for_url,
    get_retriever,
    get_retrievers_for_subject,
)
from .knowledge import RetrievalConfig, RetrievalPipeline, RetrievedChunk, rerank_chunks
from .llamaindex_index import (
    IndexedChunk,
    SubjectIndexHit,
    clear_subject_index,
    delete_chunks,
    query_subject_index,
    rebuild_subject_index,
    retrieve_subject_chunks,
    upsert_chunks,
)
from .llamaindex_adapter import ATMKnowledgeRetriever, ATMVectorStore, build_knowledge_retriever
from .readers import get_registered_reader_names
from .retrievers import get_registered_retriever_names
from .source_curation import SourceCurator
from .types import ScrapedPage, SearchResult, WebSearchResult

__all__ = [
    "ATMKnowledgeRetriever",
    "ATMVectorStore",
    "ContextCompressor",
    "ContextManager",
    "IndexedChunk",
    "RetrievalConfig",
    "RetrievalPipeline",
    "RetrievedChunk",
    "ScrapedPage",
    "SearchResult",
    "SourceCurator",
    "SubjectIndexHit",
    "WebSearchResult",
    "build_knowledge_retriever",
    "clear_subject_index",
    "delete_chunks",
    "get_compression_runtime_cache",
    "get_external_retriever_names",
    "get_reader_for_url",
    "get_reader_runtime_cache",
    "get_registered_reader_names",
    "get_registered_retriever_names",
    "get_knowledge_search_notice",
    "get_retriever",
    "get_retriever_runtime_cache",
    "get_retrievers_for_subject",
    "query_subject_index",
    "rebuild_subject_index",
    "rerank_chunks",
    "reset_search_runtime_caches",
    "retrieve_subject_chunks",
    "search_knowledge",
    "upsert_chunks",
    "web_search",
]
