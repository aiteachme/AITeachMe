"""LLM runtime defaults that should remain code-owned."""

from __future__ import annotations

DEFAULT_LLM_CONCURRENCY_LIMIT = 32
DEFAULT_LLM_TOKEN_BUDGET = 4000

__all__ = [
    "DEFAULT_LLM_CONCURRENCY_LIMIT",
    "DEFAULT_LLM_TOKEN_BUDGET",
]
