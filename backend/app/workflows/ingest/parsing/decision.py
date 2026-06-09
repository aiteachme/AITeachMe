"""Parse route decisions for ingest workflows."""

from __future__ import annotations

from app.workflows.ingest.parsing.lib.formats import (
    is_image_extension,
    normalize_extension,
)
from app.workflows.ingest.parsing.lib.features import builtin_pdf_parsing_enabled
from app.workflows.ingest.parsing.lib.provider_contracts import ParseDecision, ProviderCapability


# Conservative defaults for MinerU Cloud-style document parsing. Deployments may
# expose a wider or narrower list; later provider discovery can replace this.
DEFAULT_MINERU_EXTENSIONS = frozenset(
    {
        ".pdf",
        # 当前链路调整：.docx 改为仅走本地解析，不再自动或显式走 MinerU。
        # ".docx",
        ".pptx",
        # 旧链路：.doc 已停用，不再支持上传和解析。
        # ".doc",
        # demo / 未扩展链路：当前上传白名单不会走到这些扩展。
        # AI 提示：如果任务不是扩大上传入口，可以先不看这些 capability 设计。
        # ".xls",
        # ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        # ".html",
        # ".htm",
    }
)

DEFAULT_PADDLE_OCR_EXTENSIONS = frozenset(
    {
        ".pdf",
        # 当前链路调整：.docx 改为仅走本地解析，不再自动或显式走 PaddleOCR。
        # ".docx",
        # 旧链路：.doc 已停用，不再支持上传和解析。
        # ".doc",
        # 图片直传只走 PaddleOCR / MinerU 外部链路，不进入本地 OCR。
        ".png",
        ".jpg",
        ".jpeg",
        # ".webp",
        ".bmp",
        # ".tif",
        # ".tiff",
    }
)

DEFAULT_MARKITDOWN_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        # 当前上传入口只开放 PDF / DOCX / PPTX / Markdown / 文本；
        # PPT 和通用 Office 表格类不再声明为本地 MarkItDown capability。
        # 如后续恢复上传入口，再同步恢复这里和 parsers.py 的 registry。
        # ".ppt",
        # 旧链路：.doc 已停用，不再支持上传和解析。
        # ".doc",
        # *MARKITDOWN_GENERIC_EXTENSIONS,
    }
)

DEFAULT_OCR_EXTENSIONS = frozenset(
    {
        ".pdf",
        # 图片直传不走 LLM OCR 兜底，因此这里不展开 IMAGE_EXTENSIONS。
        # *IMAGE_EXTENSIONS,
    }
)

AUTO_EXTERNAL_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".pptx",
        # 当前链路调整：.docx 改为本地解析优先，不再加入自动外部链路。
        # ".docx",
        # 旧链路：.doc 已停用。
        # ".doc",
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
    features = {"markdown", "office", "pdf"}
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
    - supported document types auto-route as PaddleOCR -> MinerU -> local;
    - pptx auto-routes to MinerU when configured, otherwise local MarkItDown;
    - docx stays local-only even when external providers are available;
    - doc is treated as unsupported;
    - explicit provider requests are still honored for backward compatibility.
    """

    normalized_extension = normalize_extension(extension)
    normalized_request = (requested_provider or "").strip().lower() or None
    mineru = build_mineru_capability(available=mineru_available)
    paddle_ocr = build_paddle_ocr_capability(available=paddle_ocr_available)
    ocr = build_ocr_capability(available=ocr_available)
    markitdown = build_markitdown_capability(available=markitdown_available)

    if normalized_extension == ".doc":
        return ParseDecision(
            requested_provider=normalized_request,
            primary_provider="local",
            primary_reason=".doc 链路已停用，当前版本不再支持上传或解析该格式。",
            fallback_chain=[],
            metadata={
                "extension": normalized_extension,
                "route_mode": "unsupported_doc",
                "doc_supported": False,
            },
        )

    if is_image_extension(normalized_extension):
        mineru_supports_extension = mineru.supports(normalized_extension)
        paddle_ocr_supports_extension = paddle_ocr.supports(normalized_extension)
        image_metadata = {
            "extension": normalized_extension,
            "route_mode": "image_external_only",
            "image_external_required": True,
            "paddle_ocr_supported": paddle_ocr_supports_extension,
            "paddle_ocr_available": paddle_ocr.available,
            "mineru_supported": mineru_supports_extension,
            "mineru_available": mineru.available,
        }

        if paddle_ocr.available and paddle_ocr_supports_extension:
            fallback_chain = ["mineru"] if mineru.available and mineru_supports_extension else []
            return ParseDecision(
                requested_provider=normalized_request,
                primary_provider="paddle_ocr",
                primary_reason=(
                    "图片上传仅走外部解析链路；已检测到 PaddleOCR Token，"
                    "优先使用 PaddleOCR，失败后尝试 MinerU。"
                ),
                fallback_chain=fallback_chain,
                can_preview_before_primary=False,
                metadata=image_metadata,
            )

        if mineru.available and mineru_supports_extension:
            return ParseDecision(
                requested_provider=normalized_request,
                primary_provider="mineru",
                primary_reason=(
                    "图片上传仅走外部解析链路；PaddleOCR 未配置或不可用，"
                    "自动改用 MinerU。"
                ),
                fallback_chain=[],
                can_preview_before_primary=False,
                metadata=image_metadata,
            )

        return ParseDecision(
            requested_provider=normalized_request,
            primary_provider="local",
            primary_reason="图片上传当前没有可用的外部解析 provider，且不提供本地兜底解析。",
            fallback_chain=[],
            requested_provider_unavailable=normalized_request is not None,
            metadata={
                **image_metadata,
                "route_mode": "image_external_unavailable",
            },
        )

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

        if paddle_ocr.available and paddle_ocr_supports_extension:
            fallback_chain = ["local"]
            if mineru.available and mineru_supports_extension:
                fallback_chain = ["mineru", "local"]
            return ParseDecision(
                requested_provider=None,
                primary_provider="paddle_ocr",
                primary_reason=(
                    "当前文件类型支持文档解析增强，且已检测到 PaddleOCR Token；"
                    "优先使用 PaddleOCR，失败后自动回退到 MinerU 或本地解析。"
                ),
                fallback_chain=fallback_chain,
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "route_mode": "auto_external_then_local",
                    "paddle_ocr_supported": True,
                    "paddle_ocr_available": True,
                    "mineru_supported": mineru_supports_extension,
                    "mineru_available": mineru.available,
                },
            )

        if mineru.available and mineru_supports_extension:
            return ParseDecision(
                requested_provider=None,
                primary_provider="mineru",
                primary_reason=(
                    "当前文件类型支持文档解析增强，但 PaddleOCR 不可用；"
                    "自动改用 MinerU，失败后回退到本地解析。"
                ),
                fallback_chain=["local"],
                can_preview_before_primary=False,
                metadata={
                    "extension": normalized_extension,
                    "route_mode": "auto_external_then_local",
                    "paddle_ocr_supported": paddle_ocr_supports_extension,
                    "paddle_ocr_available": paddle_ocr.available,
                    "mineru_supported": True,
                    "mineru_available": True,
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
