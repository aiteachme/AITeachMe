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


class ParsedBlock(BaseModel):
    """Normalized content block produced by a parser/provider.

    This is the future evidence contract. Current code can persist markdown
    first and add block persistence incrementally.
    """

    block_id: str
    type: str = "text"
    text: str = ""
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    reading_order: int | None = None
    asset_name: str | None = None
    confidence: float | None = None
    provider: str = "local"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderQualitySignals(BaseModel):
    """Quality signals used by future arbitration and reporting."""

    chars: int = 0
    block_count: int = 0
    table_count: int = 0
    figure_count: int = 0
    equation_count: int = 0
    pages_with_text: int = 0
    pages_with_ocr: int = 0
    suspected_garbled_pages: list[int] = Field(default_factory=list)
    missing_page_ratio: float = 0.0
    avg_ocr_confidence: float | None = None


__all__ = [
    "ParseDecision",
    "ParsedBlock",
    "ProviderCapability",
    "ProviderName",
    "ProviderQualitySignals",
]
