"""Parse route decisions for ingest workflows."""

from __future__ import annotations

from app.workflows.ingest.parsing.formats import (
    IMAGE_EXTENSIONS,
    MARKITDOWN_GENERIC_EXTENSIONS,
    normalize_extension,
)
from app.workflows.ingest.parsing.features import builtin_pdf_parsing_enabled
from app.workflows.ingest.parsing.provider_contracts import ParseDecision, ProviderCapability


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

DEFAULT_PADDLE_OCR_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }
)

DEFAULT_MARKITDOWN_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        *MARKITDOWN_GENERIC_EXTENSIONS,
    }
)

DEFAULT_OCR_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".ppt",
        ".pptx",
        *IMAGE_EXTENSIONS,
    }
)

AUTO_EXTERNAL_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".doc",
        ".docx",
        ".pdf",
        ".ppt",
        ".pptx",
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


def build_paddle_ocr_capability(*, available: bool) -> ProviderCapability:
    return ProviderCapability(
        name="paddle_ocr",
        available=available,
        supported_extensions=set(DEFAULT_PADDLE_OCR_EXTENSIONS),
        features={"layout", "ocr", "markdown", "assets"},
        quality_level="high",
        latency_level="slow",
        cost_level="external",
    )


def build_markitdown_capability(*, available: bool) -> ProviderCapability:
    supported_extensions = set(DEFAULT_MARKITDOWN_EXTENSIONS)
    features = {"markdown", "office", "pdf", "html", "spreadsheet"}
    if not builtin_pdf_parsing_enabled():
        supported_extensions.discard(".pdf")
        features.discard("pdf")

    return ProviderCapability(
        name="markitdown",
        available=available,
        supported_extensions=supported_extensions,
        features=features,
        quality_level="medium",
        latency_level="medium",
        cost_level="local",
    )


def build_ocr_capability(*, available: bool) -> ProviderCapability:
    return ProviderCapability(
        name="ocr",
        available=available,
        supported_extensions=set(DEFAULT_OCR_EXTENSIONS),
        features={"ocr", "vision", "markdown", "assets"},
        quality_level="high",
        latency_level="slow",
        cost_level="llm",
    )


def build_parse_decision(
    *,
    extension: str,
    requested_provider: str | None,
    mineru_available: bool,
    paddle_ocr_available: bool = False,
    ocr_available: bool = False,
    markitdown_available: bool = False,
    strict: bool = False,
) -> ParseDecision:
    """Choose the primary parsing provider for the current file.

    Current default behavior:
    - text / markdown stay local;
    - supported document types auto-route as MinerU -> PaddleOCR -> local;
    - explicit provider requests are still honored for backward compatibility.
    """

    normalized_extension = normalize_extension(extension)
    normalized_request = (requested_provider or "").strip().lower() or None
    mineru = build_mineru_capability(available=mineru_available)
    paddle_ocr = build_paddle_ocr_capability(available=paddle_ocr_available)
    ocr = build_ocr_capability(available=ocr_available)
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

    if normalized_request == "ocr":
        ocr_supports_extension = ocr.supports(normalized_extension)
        if ocr.available and ocr_supports_extension:
            return ParseDecision(
                requested_provider="ocr",
                primary_provider="ocr",
                primary_reason="用户选择 OCR 解析服务，且当前视觉 OCR capability 支持该文件类型。",
                fallback_chain=["local", "markitdown"],
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "ocr_supported": True,
                    "ocr_available": True,
                },
            )
        if not ocr.available:
            return ParseDecision(
                requested_provider="ocr",
                primary_provider="local",
                primary_reason="用户选择 OCR 解析服务，但当前 OCR 模型网关不可用；按 fallback 策略改用本地解析。",
                fallback_chain=["markitdown"],
                requested_provider_unavailable=True,
                metadata={
                    "extension": normalized_extension,
                    "ocr_supported": ocr_supports_extension,
                    "ocr_available": False,
                },
            )
        if strict:
            return ParseDecision(
                requested_provider="ocr",
                primary_provider="ocr",
                primary_reason="用户选择 OCR 解析服务，但当前 OCR capability 不支持该文件类型。",
                strict=True,
                unsupported_requested_provider=True,
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "ocr_supported": ocr_supports_extension,
                    "ocr_available": ocr.available,
                },
            )
        return ParseDecision(
            requested_provider="ocr",
            primary_provider="local",
            primary_reason="用户选择 OCR 解析服务，但当前 OCR capability 不支持该文件类型；按 fallback 策略改用本地解析。",
            fallback_chain=["markitdown"],
            unsupported_requested_provider=True,
            metadata={
                "extension": normalized_extension,
                "ocr_supported": ocr_supports_extension,
                "ocr_available": ocr.available,
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

    if normalized_request == "paddle_ocr":
        paddle_ocr_supports_extension = paddle_ocr.supports(normalized_extension)
        if paddle_ocr.available and paddle_ocr_supports_extension:
            return ParseDecision(
                requested_provider="paddle_ocr",
                primary_provider="paddle_ocr",
                primary_reason=(
                    "用户显式选择 PaddleOCR，且当前 PaddleOCR capability 支持该文件类型。"
                ),
                fallback_chain=["local", "ocr", "multimodal"],
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "paddle_ocr_supported": True,
                    "paddle_ocr_available": True,
                },
            )
        if not paddle_ocr.available:
            return ParseDecision(
                requested_provider="paddle_ocr",
                primary_provider="local",
                primary_reason=(
                    "用户显式选择 PaddleOCR，但当前 PaddleOCR 未配置或不可用；"
                    "按 fallback 策略改用本地解析。"
                ),
                fallback_chain=["ocr", "multimodal"],
                requested_provider_unavailable=True,
                metadata={
                    "extension": normalized_extension,
                    "paddle_ocr_supported": paddle_ocr_supports_extension,
                    "paddle_ocr_available": False,
                },
            )
        if strict:
            return ParseDecision(
                requested_provider="paddle_ocr",
                primary_provider="paddle_ocr",
                primary_reason="用户显式选择 PaddleOCR，但当前 PaddleOCR capability 不支持该文件类型。",
                strict=True,
                unsupported_requested_provider=True,
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "paddle_ocr_supported": paddle_ocr_supports_extension,
                    "paddle_ocr_available": paddle_ocr.available,
                },
            )
        return ParseDecision(
            requested_provider="paddle_ocr",
            primary_provider="local",
            primary_reason=(
                "用户显式选择 PaddleOCR，但当前 PaddleOCR capability 不支持该文件类型；"
                "按 fallback 策略改用本地解析。"
            ),
            fallback_chain=["ocr", "multimodal"],
            unsupported_requested_provider=True,
            metadata={
                "extension": normalized_extension,
                "paddle_ocr_supported": paddle_ocr_supports_extension,
                "paddle_ocr_available": paddle_ocr.available,
            },
        )

    if normalized_request is None and normalized_extension in AUTO_EXTERNAL_DOCUMENT_EXTENSIONS:
        mineru_supports_extension = mineru.supports(normalized_extension)
        paddle_ocr_supports_extension = paddle_ocr.supports(normalized_extension)

        if mineru.available and mineru_supports_extension:
            fallback_chain = ["local"]
            if paddle_ocr.available and paddle_ocr_supports_extension:
                fallback_chain = ["paddle_ocr", "local"]
            return ParseDecision(
                requested_provider=None,
                primary_provider="mineru",
                primary_reason=(
                    "当前文件类型支持文档解析增强，且已检测到 MinerU Token；"
                    "优先使用 MinerU，失败后自动回退到 PaddleOCR 或本地解析。"
                ),
                fallback_chain=fallback_chain,
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "route_mode": "auto_external_then_local",
                    "mineru_supported": True,
                    "mineru_available": True,
                    "paddle_ocr_supported": paddle_ocr_supports_extension,
                    "paddle_ocr_available": paddle_ocr.available,
                },
            )

        if paddle_ocr.available and paddle_ocr_supports_extension:
            return ParseDecision(
                requested_provider=None,
                primary_provider="paddle_ocr",
                primary_reason=(
                    "当前文件类型支持文档解析增强，MinerU 不可用；"
                    "自动改用 PaddleOCR，失败后回退到本地解析。"
                ),
                fallback_chain=["local"],
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "route_mode": "auto_external_then_local",
                    "mineru_supported": mineru_supports_extension,
                    "mineru_available": mineru.available,
                    "paddle_ocr_supported": True,
                    "paddle_ocr_available": True,
                },
            )

        return ParseDecision(
            requested_provider=None,
            primary_provider="local",
            primary_reason=(
                "当前文件类型支持外部增强解析，但 MinerU / PaddleOCR Token 均不可用；"
                "自动回退到本地解析链路。"
            ),
            fallback_chain=[],
            metadata={
                "extension": normalized_extension,
                "route_mode": "auto_local_only",
                "mineru_supported": mineru_supports_extension,
                "mineru_available": mineru.available,
                "paddle_ocr_supported": paddle_ocr_supports_extension,
                "paddle_ocr_available": paddle_ocr.available,
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
    "DEFAULT_PADDLE_OCR_EXTENSIONS",
    "DEFAULT_OCR_EXTENSIONS",
    "build_markitdown_capability",
    "build_mineru_capability",
    "build_paddle_ocr_capability",
    "build_ocr_capability",
    "build_parse_decision",
]
