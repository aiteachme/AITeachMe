"""LlamaIndex adapter layer for the ATM search stack.

Bridges existing embedding / vector-store / rerank infrastructure into
LlamaIndex-compatible components so that workflow code can use the
LlamaIndex retriever API without changing the underlying storage layer.
"""

from app.shared.infra.search.llamaindex_adapter.embedding import ATMEmbedding
from app.shared.infra.search.llamaindex_adapter.retriever import (
    ATMKnowledgeRetriever,
    build_knowledge_retriever,
)
from app.shared.infra.search.llamaindex_adapter.vector_store import ATMVectorStore

__all__ = [
    "ATMEmbedding",
    "ATMKnowledgeRetriever",
    "ATMVectorStore",
    "build_knowledge_retriever",
]
