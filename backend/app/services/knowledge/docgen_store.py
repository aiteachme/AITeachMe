"""Backward-compatibility shim — canonical module is ``app.utils.docgen_store``.

This file re-exports every public symbol so that existing ``from
app.services.knowledge.docgen_store import ...`` statements keep working.
New code should import from ``app.utils.docgen_store`` directly.
"""

from app.utils.docgen_store import (  # noqa: F401
    STALE_BUILD_LOCK_TTL,
    KnowledgeBuildLock,
    KnowledgeDocsManifest,
    acquire_knowledge_build_lock,
    clear_docgen_staging,
    clear_published_knowledge_docs_files,
    is_knowledge_build_locked,
    read_knowledge_build_lock,
    read_knowledge_manifest,
    release_knowledge_build_lock,
    write_knowledge_manifest,
)

__all__ = [
    "STALE_BUILD_LOCK_TTL",
    "KnowledgeBuildLock",
    "KnowledgeDocsManifest",
    "acquire_knowledge_build_lock",
    "clear_docgen_staging",
    "clear_published_knowledge_docs_files",
    "is_knowledge_build_locked",
    "read_knowledge_build_lock",
    "read_knowledge_manifest",
    "release_knowledge_build_lock",
    "write_knowledge_manifest",
]
