"""Compatibility LlamaIndex retriever components for the ATM search stack.

The canonical course index lifecycle now lives in
``app.shared.infra.search.llamaindex_index``.  This package keeps older
LlamaIndex retriever-style imports working on top of that managed index.

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
