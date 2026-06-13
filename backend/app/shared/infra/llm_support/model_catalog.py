"""Code-owned model catalog and routing defaults."""

from __future__ import annotations

PRIMARY_GATEWAY_MODEL_ALLOWLIST: tuple[str, ...] = (
    "codex-auto-review",
    "gpt-4o-audio-preview",
    "gpt-4o-realtime-preview",
    "gpt-5.2",
    "gpt-5.2-2025-12-11",
    "gpt-5.2-chat-latest",
    "gpt-5.2-pro",
    "gpt-5.2-pro-2025-12-11",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.4",
    "gpt-5.4-2026-03-05",
    "gpt-5.4-mini",
    "gpt-5.5",
    "gpt-image-1",
    "gpt-image-1.5",
    "gpt-image-2",
)

FALLBACK_RUNTIME_MODEL_OVERRIDES: tuple[str, ...] = ("gemini-3.1-flash-lite",)

ALLOWED_RUNTIME_MODEL_OVERRIDES: tuple[str, ...] = (
    *PRIMARY_GATEWAY_MODEL_ALLOWLIST,
    *FALLBACK_RUNTIME_MODEL_OVERRIDES,
)

PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET = frozenset(PRIMARY_GATEWAY_MODEL_ALLOWLIST)
ALLOWED_RUNTIME_MODEL_OVERRIDES_SET = frozenset(ALLOWED_RUNTIME_MODEL_OVERRIDES)

__all__ = [
    "ALLOWED_RUNTIME_MODEL_OVERRIDES",
    "ALLOWED_RUNTIME_MODEL_OVERRIDES_SET",
    "FALLBACK_RUNTIME_MODEL_OVERRIDES",
    "PRIMARY_GATEWAY_MODEL_ALLOWLIST",
    "PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET",
]
