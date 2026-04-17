"""Provider and parse-decision contracts for ingest parsing."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderName = Literal[
    "local",
    "mineru",
    "ocr",
    "multimodal",
    "deepdoc",
    "docling",
]


class ProviderCapability(BaseModel):
    """Runtime capability advertised by a parse provider."""

    name: ProviderName
    available: bool = True
    supported_extensions: set[str] = Field(default_factory=set)
    features: set[str] = Field(default_factory=set)
    quality_level: Literal["low", "medium", "high"] = "medium"
    latency_level: Literal["fast", "medium", "slow"] = "medium"
    cost_level: Literal["free", "local", "external", "llm"] = "local"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def supports(self, extension: str) -> bool:
        normalized = extension.lower().strip()
        if normalized and not normalized.startswith("."):
            normalized = f".{normalized}"
        return normalized in self.supported_extensions


class ParseDecision(BaseModel):
    """Chosen parse route for one uploaded file."""

    requested_provider: str | None = None
    primary_provider: ProviderName = "local"
    primary_reason: str
    fallback_chain: list[ProviderName] = Field(default_factory=list)
    conversion_plan: list[str] = Field(default_factory=list)
    enhance_plan: list[str] = Field(default_factory=list)
    strict: bool = False
    unsupported_requested_provider: bool = False
    requested_provider_unavailable: bool = False
    can_preview_before_primary: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def uses_mineru(self) -> bool:
        return self.primary_provider == "mineru"


__all__ = [
    "ParseDecision",
    "ProviderCapability",
    "ProviderName",
]
