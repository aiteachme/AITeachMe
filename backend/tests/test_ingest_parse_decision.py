from __future__ import annotations

from app.workflows.ingest.common.parsing.decision import (
    DEFAULT_MINERU_EXTENSIONS,
    build_mineru_capability,
    build_parse_decision,
)


def test_explicit_mineru_supported_extension_routes_to_mineru() -> None:
    decision = build_parse_decision(
        extension=".pdf",
        requested_provider="mineru",
        mineru_available=True,
    )

    assert decision.primary_provider == "mineru"
    assert decision.uses_mineru is True
    assert decision.unsupported_requested_provider is False
    assert decision.can_preview_before_primary is False


def test_explicit_mineru_unsupported_extension_falls_back_to_local() -> None:
    decision = build_parse_decision(
        extension=".md",
        requested_provider="mineru",
        mineru_available=True,
    )

    assert decision.primary_provider == "local"
    assert decision.uses_mineru is False
    assert decision.unsupported_requested_provider is True
    assert "ocr" in decision.fallback_chain


def test_default_parse_decision_uses_local() -> None:
    decision = build_parse_decision(
        extension=".pdf",
        requested_provider=None,
        mineru_available=False,
    )

    assert decision.primary_provider == "local"
    assert decision.requested_provider is None
    assert decision.unsupported_requested_provider is False


def test_explicit_mineru_unavailable_falls_back_to_local() -> None:
    decision = build_parse_decision(
        extension=".pdf",
        requested_provider="mineru",
        mineru_available=False,
    )

    assert decision.primary_provider == "local"
    assert decision.uses_mineru is False
    assert decision.requested_provider_unavailable is True
    assert decision.unsupported_requested_provider is False


def test_mineru_capability_normalizes_extension_support() -> None:
    capability = build_mineru_capability(available=True)

    assert DEFAULT_MINERU_EXTENSIONS
    assert capability.supports("PDF")
    assert capability.supports(".docx")
    assert not capability.supports(".md")

