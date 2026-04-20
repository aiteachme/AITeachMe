"""Parse route decisions for ingest workflows."""

from __future__ import annotations

from app.workflows.ingest.common.parsing.formats import MARKITDOWN_GENERIC_EXTENSIONS, normalize_extension
from app.workflows.ingest.common.parsing.provider_contracts import ParseDecision, ProviderCapability


# Conservative defaults for MinerU Cloud-style document parsing. Deployments may
# expose a wider or narrower list; later provider discovery can replace this.
DEFAULT_MINERU_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".html",
        ".htm",
    }
)

DEFAULT_MARKITDOWN_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".ppt",
        ".pptx",
        *MARKITDOWN_GENERIC_EXTENSIONS,
    }
)


def build_mineru_capability(*, available: bool) -> ProviderCapability:
    return ProviderCapability(
        name="mineru",
        available=available,
        supported_extensions=set(DEFAULT_MINERU_EXTENSIONS),
        features={"layout", "ocr", "table", "formula", "markdown", "assets"},
        quality_level="high",
        latency_level="slow",
        cost_level="external",
    )


def build_markitdown_capability(*, available: bool) -> ProviderCapability:
    return ProviderCapability(
        name="markitdown",
        available=available,
        supported_extensions=set(DEFAULT_MARKITDOWN_EXTENSIONS),
        features={"markdown", "office", "pdf", "html", "spreadsheet"},
        quality_level="medium",
        latency_level="medium",
        cost_level="local",
    )


def build_parse_decision(
    *,
    extension: str,
    requested_provider: str | None,
    mineru_available: bool,
    markitdown_available: bool = False,
    strict: bool = False,
) -> ParseDecision:
    """Choose the primary parsing provider for the current file.

    This is intentionally small for the first landing:
    - explicit MinerU wins when the extension is supported;
    - unsupported explicit MinerU falls back to local unless strict is true;
    - auto/default stays local for now.
    """

    normalized_extension = normalize_extension(extension)
    normalized_request = (requested_provider or "").strip().lower() or None
    mineru = build_mineru_capability(available=mineru_available)
    markitdown = build_markitdown_capability(available=markitdown_available)

    if normalized_request == "markitdown":
        markitdown_supports_extension = markitdown.supports(normalized_extension)
        if markitdown.available and markitdown_supports_extension:
            return ParseDecision(
                requested_provider="markitdown",
                primary_provider="markitdown",
                primary_reason=(
                    "用户显式选择 MarkItDown，且当前 MarkItDown capability 支持该文件类型。"
                ),
                fallback_chain=["local", "ocr", "multimodal"],
                metadata={
                    "extension": normalized_extension,
                    "markitdown_supported": True,
                    "markitdown_available": True,
                },
            )
        if not markitdown.available:
            return ParseDecision(
                requested_provider="markitdown",
                primary_provider="local",
                primary_reason=(
                    "用户显式选择 MarkItDown，但当前 MarkItDown 不可用；"
                    "按 fallback 策略改用本地解析。"
                ),
                fallback_chain=["ocr", "multimodal"],
                requested_provider_unavailable=True,
                metadata={
                    "extension": normalized_extension,
                    "markitdown_supported": markitdown_supports_extension,
                    "markitdown_available": False,
                },
            )
        if strict:
            return ParseDecision(
                requested_provider="markitdown",
                primary_provider="markitdown",
                primary_reason="用户显式选择 MarkItDown，但当前 MarkItDown capability 不支持该文件类型。",
                strict=True,
                unsupported_requested_provider=True,
                metadata={
                    "extension": normalized_extension,
                    "markitdown_supported": markitdown_supports_extension,
                    "markitdown_available": markitdown.available,
                },
            )
        return ParseDecision(
            requested_provider="markitdown",
            primary_provider="local",
            primary_reason=(
                "用户显式选择 MarkItDown，但当前 MarkItDown capability 不支持该文件类型；"
                "按 fallback 策略改用本地解析。"
            ),
            fallback_chain=["ocr", "multimodal"],
            unsupported_requested_provider=True,
            metadata={
                "extension": normalized_extension,
                "markitdown_supported": markitdown_supports_extension,
                "markitdown_available": markitdown.available,
            },
        )

    if normalized_request == "mineru":
        mineru_supports_extension = mineru.supports(normalized_extension)
        if mineru.available and mineru_supports_extension:
            return ParseDecision(
                requested_provider="mineru",
                primary_provider="mineru",
                primary_reason=(
                    "用户显式选择 MinerU，且当前 MinerU capability 支持该文件类型。"
                ),
                fallback_chain=["local", "ocr", "multimodal"],
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "mineru_supported": True,
                    "mineru_available": True,
                },
            )
        if not mineru.available:
            return ParseDecision(
                requested_provider="mineru",
                primary_provider="local",
                primary_reason=(
                    "用户显式选择 MinerU，但当前 MinerU 未配置或不可用；"
                    "按 fallback 策略改用本地解析。"
                ),
                fallback_chain=["ocr", "multimodal"],
                requested_provider_unavailable=True,
                metadata={
                    "extension": normalized_extension,
                    "mineru_supported": mineru_supports_extension,
                    "mineru_available": False,
                },
            )
        if strict:
            return ParseDecision(
                requested_provider="mineru",
                primary_provider="mineru",
                primary_reason="用户显式选择 MinerU，但当前 MinerU capability 不支持该文件类型。",
                strict=True,
                unsupported_requested_provider=True,
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "mineru_supported": mineru.supports(normalized_extension),
                    "mineru_available": mineru.available,
                },
            )
        return ParseDecision(
            requested_provider="mineru",
            primary_provider="local",
            primary_reason=(
                "用户显式选择 MinerU，但当前 MinerU capability 不支持该文件类型；"
                "按 fallback 策略改用本地解析。"
            ),
            fallback_chain=["ocr", "multimodal"],
            unsupported_requested_provider=True,
            metadata={
                "extension": normalized_extension,
                "mineru_supported": mineru_supports_extension,
                "mineru_available": mineru.available,
            },
        )

    return ParseDecision(
        requested_provider=normalized_request,
        primary_provider="local",
        primary_reason="未选择外部解析 provider，使用本地解析作为主路径。",
        fallback_chain=["ocr", "multimodal"],
        metadata={"extension": normalized_extension},
    )


__all__ = [
    "DEFAULT_MARKITDOWN_EXTENSIONS",
    "DEFAULT_MINERU_EXTENSIONS",
    "build_markitdown_capability",
    "build_mineru_capability",
    "build_parse_decision",
]
