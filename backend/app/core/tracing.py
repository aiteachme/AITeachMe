"""兼容性 shim — 实际实现已移至 app.infra.tracing。"""
from app.infra.tracing import (  # noqa: F401
    LLMCallRecord,
    LLMCallTracker,
    Span,
    Tracer,
    get_tracker,
    get_tracer,
)
