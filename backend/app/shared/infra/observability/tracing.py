"""Tracing helpers for workflow-scoped LLM observability.

This module is a backward-compatible re-export facade.  The actual
implementation is split across focused submodules:

- ``sanitize``  – LangSmith value sanitization and redaction
- ``tracker``   – In-memory LLM call tracking and span primitives
- ``builder``   – LangSmith metadata/tags/extra construction
- ``scope``     – Trace-context management, LangSmith scopes, @traceable wrappers
"""

from __future__ import annotations

# ── Re-exports from sanitize ─────────────────────────────────────────
from app.shared.infra.observability.sanitize import (
    get_langsmith_max_text_chars,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
    sanitize_langsmith_text,
    sanitize_langsmith_value,
)

# ── Re-exports from tracker ──────────────────────────────────────────
from app.shared.infra.observability.tracker import (
    LLMCallRecord,
    LLMCallTracker,
    Span,
    Tracer,
    get_tracer,
    get_tracker,
)

# ── Re-exports from builder ──────────────────────────────────────────
from app.shared.infra.observability.builder import (
    build_langsmith_extra,
    build_langsmith_metadata,
    build_langsmith_tags,
)

# ── Re-exports from scope ────────────────────────────────────────────
from app.shared.infra.observability.scope import (
    LANGSMITH_RUN_TYPES,
    LLMTraceContext,
    LangSmithRunType,
    annotate_traceable,
    get_langsmith_project_name,
    get_llm_trace_context,
    langsmith_capture_inputs_enabled,
    langsmith_capture_outputs_enabled,
    langsmith_trace,
    langsmith_tracing_enabled,
    langsmith_tracing_requested,
    langsmith_tracing_scope,
    llm_trace_scope,
    normalize_langsmith_run_type,
    trace_substep,
    traceable_with_context,
)

__all__ = [
    "LLMCallRecord",
    "LLMCallTracker",
    "LLMTraceContext",
    "LangSmithRunType",
    "Span",
    "Tracer",
    "annotate_traceable",
    "build_langsmith_extra",
    "build_langsmith_metadata",
    "build_langsmith_tags",
    "get_langsmith_max_text_chars",
    "get_langsmith_project_name",
    "get_llm_trace_context",
    "get_tracer",
    "get_tracker",
    "langsmith_capture_inputs_enabled",
    "langsmith_capture_outputs_enabled",
    "langsmith_trace",
    "langsmith_tracing_enabled",
    "langsmith_tracing_requested",
    "langsmith_tracing_scope",
    "llm_trace_scope",
    "normalize_langsmith_run_type",
    "sanitize_langsmith_input",
    "sanitize_langsmith_output",
    "sanitize_langsmith_text",
    "sanitize_langsmith_value",
    "trace_substep",
    "traceable_with_context",
]
