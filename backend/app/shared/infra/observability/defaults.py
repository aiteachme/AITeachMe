"""Observability defaults outside the project settings surface."""

from __future__ import annotations

DEFAULT_TIMING_TOP_K = 5
DEFAULT_LANGSMITH_MAX_TEXT_CHARS = 50000
DEFAULT_LLM_OBSERVABILITY_MAX_RECORDS = 1000

__all__ = [
    "DEFAULT_LANGSMITH_MAX_TEXT_CHARS",
    "DEFAULT_LLM_OBSERVABILITY_MAX_RECORDS",
    "DEFAULT_TIMING_TOP_K",
]
