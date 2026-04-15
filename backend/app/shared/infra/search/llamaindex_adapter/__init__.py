"""LlamaIndex adapter layer for the ATM search stack.

Bridges search-facing vector-store / retriever infrastructure into
LlamaIndex-compatible components so that workflow code can use the
LlamaIndex retriever API without changing the underlying storage layer.

The embedding adapter itself now lives in ``app.shared.infra.embedding``.
"""

from app.shared.infra.search.llamaindex_adapter.retriever import (
    ATMKnowledgeRetriever,
    build_knowledge_retriever,
)
from app.shared.infra.search.llamaindex_adapter.vector_store import ATMVectorStore

__all__ = [
    "ATMKnowledgeRetriever",
    "ATMVectorStore",
    "build_knowledge_retriever",
]
