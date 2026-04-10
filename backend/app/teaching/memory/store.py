"""Compatibility facade for the canonical memory store."""

from app.shared.infra.memory.store import SQLiteMemoryStore, get_memory_store

__all__ = ["SQLiteMemoryStore", "get_memory_store"]
