"""Document Parse Provider interface — hot-swappable external parsing services.

改进 8 (§10.4): Inspired by RAGFlow's multi-parser support and MinerU's auto-engine.

Providers allow the system to route document parsing to external services (MinerU,
Docling, etc.) when available, while falling back to local parsers when they're not.

Usage:
    # Check available providers at startup
    registry = ProviderRegistry()
    registry.log_available_providers()

    # Route a document to the best available provider
    provider = registry.select_provider(extension=".pdf", preference="quality")
    result = await provider.parse(file_path, options)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


# ── Provider Protocol ──


class ProviderCapability(str, Enum):
    """What a provider can do."""
    PDF_PARSE = "pdf_parse"
    OCR = "ocr"
    TABLE_RECOGNITION = "table_recognition"
    FORMULA_RECOGNITION = "formula_recognition"
    LAYOUT_DETECTION = "layout_detection"


class ProviderParseResult(BaseModel):
    """Standardized output from any provider."""
    markdown: str
    provider_name: str
    page_count: int = 0
    elapsed_s: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentParseProvider(ABC):
    """Abstract base class for document parsing providers.

    Implement this to add support for external parsing services like
    MinerU, Docling, Marker, etc. The system will auto-detect available
    providers at startup and route documents accordingly.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name, e.g. 'MinerU', 'Docling'."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> set[ProviderCapability]:
        """Set of capabilities this provider supports."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is currently available (service up, API keys set, etc.)."""
        ...

    @abstractmethod
    async def parse(
        self,
        file_path: Path,
        *,
        options: dict[str, Any] | None = None,
    ) -> ProviderParseResult:
        """Parse a document and return standardized result."""
        ...

    def supports_extension(self, extension: str) -> bool:
        """Whether this provider can handle the given file extension."""
        return extension.lower() in {".pdf"}  # Default: PDF only


# ── Built-in Local Provider ──


class LocalParserProvider(DocumentParseProvider):
    """Default provider using local parsing libraries (pymupdf, markitdown, etc.).

    This is always available and serves as the fallback when no external
    providers are configured.
    """

    @property
    def name(self) -> str:
        return "local"

    @property
    def capabilities(self) -> set[ProviderCapability]:
        caps = {ProviderCapability.PDF_PARSE}
        try:
            import fitz  # noqa: F401
            caps.add(ProviderCapability.OCR)
        except ImportError:
            pass
        return caps

    def is_available(self) -> bool:
        return True  # Always available

    async def parse(
        self,
        file_path: Path,
        *,
        options: dict[str, Any] | None = None,
    ) -> ProviderParseResult:
        # Local provider delegates to the existing fast_parse_file pipeline.
        # This is a placeholder — the actual routing happens in orchestrator.py.
        raise NotImplementedError(
            "LocalParserProvider.parse() should not be called directly. "
            "Use the orchestrator's fast_parse_file() instead."
        )


# ── Placeholder External Providers ──
# These will be implemented when the external services are ready.


class MinerUProvider(DocumentParseProvider):
    """MinerU external parsing service provider.

    To enable: set MINERU_ENDPOINT in .env, e.g.:
        MINERU_ENDPOINT=http://localhost:8765

    MinerU provides high-accuracy PDF parsing with:
    - Layout detection (LayoutLMv3)
    - Formula recognition (UniMERNet)
    - Table recognition (TableMaster)
    - OCR (PaddleOCR)
    """

    def __init__(self, endpoint: str | None = None):
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return "mineru"

    @property
    def capabilities(self) -> set[ProviderCapability]:
        return {
            ProviderCapability.PDF_PARSE,
            ProviderCapability.OCR,
            ProviderCapability.TABLE_RECOGNITION,
            ProviderCapability.FORMULA_RECOGNITION,
            ProviderCapability.LAYOUT_DETECTION,
        }

    def is_available(self) -> bool:
        if not self._endpoint:
            return False
        # TODO: Add health check ping to endpoint
        return True

    async def parse(
        self,
        file_path: Path,
        *,
        options: dict[str, Any] | None = None,
    ) -> ProviderParseResult:
        # TODO: Implement MinerU API call
        # POST file to self._endpoint/api/v1/parse
        raise NotImplementedError("MinerU provider not yet implemented")


class DoclingProvider(DocumentParseProvider):
    """IBM Docling document parsing provider.

    To enable: set DOCLING_ENDPOINT in .env, or install docling SDK:
        pip install docling

    Docling provides ML-based layout detection and table structure recognition.
    """

    def __init__(self, endpoint: str | None = None):
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return "docling"

    @property
    def capabilities(self) -> set[ProviderCapability]:
        return {
            ProviderCapability.PDF_PARSE,
            ProviderCapability.TABLE_RECOGNITION,
            ProviderCapability.LAYOUT_DETECTION,
        }

    def is_available(self) -> bool:
        if not self._endpoint:
            return False
        return True

    async def parse(
        self,
        file_path: Path,
        *,
        options: dict[str, Any] | None = None,
    ) -> ProviderParseResult:
        raise NotImplementedError("Docling provider not yet implemented")


# ── Provider Registry ──


class ProviderRegistry:
    """Registry for document parse providers.

    At startup, registers all configured providers and logs availability.
    At runtime, selects the best available provider for each document.
    """

    def __init__(self) -> None:
        self._providers: list[DocumentParseProvider] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all known providers, checking env config."""
        import os

        # External providers (check env vars)
        mineru_endpoint = os.environ.get("MINERU_ENDPOINT")
        if mineru_endpoint:
            self._providers.append(MinerUProvider(endpoint=mineru_endpoint))

        docling_endpoint = os.environ.get("DOCLING_ENDPOINT")
        if docling_endpoint:
            self._providers.append(DoclingProvider(endpoint=docling_endpoint))

        # Local provider is always registered last (fallback)
        self._providers.append(LocalParserProvider())

    def register(self, provider: DocumentParseProvider) -> None:
        """Register a custom provider."""
        self._providers.insert(0, provider)  # Higher priority than defaults

    @property
    def available_providers(self) -> list[DocumentParseProvider]:
        """All currently available providers."""
        return [p for p in self._providers if p.is_available()]

    def select_provider(
        self,
        extension: str,
        preference: str = "speed",  # "speed" | "quality"
    ) -> DocumentParseProvider | None:
        """Select the best available provider for a file extension.

        Args:
            extension: File extension (e.g. ".pdf")
            preference: "speed" prefers local, "quality" prefers external

        Returns:
            Best available provider, or None if no provider supports this extension.
        """
        candidates = [
            p for p in self.available_providers
            if p.supports_extension(extension)
        ]
        if not candidates:
            return None

        if preference == "quality":
            # Prefer external providers (MinerU > Docling > local)
            for provider in candidates:
                if provider.name != "local":
                    return provider

        # Default: prefer local (fastest)
        return candidates[-1] if candidates else None

    def log_available_providers(self) -> None:
        """Log all registered providers and their availability status."""
        for provider in self._providers:
            available = provider.is_available()
            logger.info(
                "provider_status",
                provider=provider.name,
                available=available,
                capabilities=[c.value for c in provider.capabilities],
            )
        available_names = [p.name for p in self.available_providers]
        logger.info(
            "provider_registry_summary",
            registered=len(self._providers),
            available=len(available_names),
            available_providers=available_names,
        )
