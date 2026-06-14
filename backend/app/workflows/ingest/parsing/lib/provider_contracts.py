"""Provider and parse-decision contracts for ingest parsing."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderName = Literal[
    "local",
    "mineru",
    "paddle_ocr",
    "ocr",
    "multimodal",
    "deepdoc",
    "docling",
    "markitdown",
]


class ExternalProviderTimeoutError(RuntimeError):
    """Raised when an external parse provider misses the end-to-end time budget."""

    def __init__(self, provider_name: str, timeout_s: float) -> None:
        self.provider_name = str(provider_name or "external_provider")
        self.timeout_s = float(timeout_s)
        timeout_display = int(timeout_s) if float(timeout_s).is_integer() else timeout_s
        super().__init__(f"{self.provider_name} 解析超时：{timeout_display} 秒内未拿到最终结果")


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

    @property
    def uses_markitdown(self) -> bool:
        return self.primary_provider == "markitdown"

    @property
    def uses_paddle_ocr(self) -> bool:
        return self.primary_provider == "paddle_ocr"

    @property
    def uses_ocr(self) -> bool:
        return self.primary_provider == "ocr"


__all__ = [
    "ExternalProviderTimeoutError",
    "ParseDecision",
    "ProviderCapability",
    "ProviderName",
]
