"""Parser planning and capability-aware routing for ingest workflows."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.shared.infra.env_support import get_env, get_env_choice
from app.shared.infra.exceptions import FileParseError, UnsupportedFileTypeError
from app.shared.infra.llm_support import get_llm_concurrency_limit
from app.shared.infra.settings import get_settings
from app.shared.infra.settings.support import llm_provider_requires_api_key
from app.workflows.ingest.parsing.defaults import (
    DEFAULT_PARSE_CONCURRENCY,
    DEFAULT_PARSER_TIMEOUT_S,
)
from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.formats import (
    categorize_text_extension,
    is_image_extension,
    is_text_extension,
    normalize_extension,
)
from app.workflows.ingest.parsing.parsers import (
    DEFAULT_PARSER_CHAIN,
    get_available_parsers,
    resolve_parser_extension,
)
from app.workflows.ingest.parsing.types import ParserRunOptions

_LARGE_DOCX_PAGE_COUNT = 60
_MIN_INTERNAL_PARALLELISM = 5
_MAX_INTERNAL_PARALLELISM = 10


class ParsePlan(BaseModel):
    """Materialized parser execution plan stored in workflow state."""

    mode: str
    parser_chain: list[str] = Field(default_factory=list)
    decision_reason: str
    options: ParserRunOptions = Field(default_factory=ParserRunOptions)


def build_parse_plan(
    *,
    file_path: str | Path,
    filetype: str,
    file_size_bytes: int | None,
    classification: ClassificationResult | None,
) -> ParsePlan:
    """Choose parser chain and runtime budget from file signals and capabilities."""

    settings = get_settings()
    extension = resolve_parser_extension(file_path, normalize_extension(filetype))
    visual_calls_available = _llm_visual_calls_available()
    allow_image_vision = settings.has_vision_model and visual_calls_available
    allow_document_ocr = settings.has_document_ocr_model and visual_calls_available
    available_parsers = get_available_parsers(extension, allow_llm_vision=allow_image_vision)
    if not available_parsers:
        if is_image_extension(extension):
            raise FileParseError(
                Path(file_path).name,
                reason="图片文件只支持 PaddleOCR 或 MinerU 外部解析，当前不提供本地兜底。",
            )
        raise UnsupportedFileTypeError(extension)

    file_mb = round((file_size_bytes or 0) / (1024 * 1024), 2)
    estimated_pages = classification.estimated_pages if classification else 0
    parser_parallelism = _derive_parser_parallelism(
        base_concurrency=DEFAULT_PARSE_CONCURRENCY,
        file_mb=file_mb,
        estimated_pages=estimated_pages,
    )
    ocr_language_mode = _derive_ocr_language_mode(classification)
    options = ParserRunOptions(
        timeout_s=DEFAULT_PARSER_TIMEOUT_S,
        parser_parallelism=parser_parallelism,
        llm_ocr_page_concurrency=max(1, min(parser_parallelism, get_llm_concurrency_limit())),
        ocr_language_mode=ocr_language_mode,
    )
    preferred_order = _preferred_parser_order(
        extension=extension,
        file_mb=file_mb,
        estimated_pages=estimated_pages,
        classification=classification,
        image_vision_enabled=allow_image_vision,
    )

    parser_chain = [name for name in preferred_order if name in available_parsers]
    if not parser_chain:
        parser_chain = [name for name in DEFAULT_PARSER_CHAIN.get(extension, []) if name in available_parsers]
    if not parser_chain:
        raise UnsupportedFileTypeError(extension)

    mode, reason = _decide_mode_and_options(
        extension=extension,
        file_mb=file_mb,
        estimated_pages=estimated_pages,
        classification=classification,
        document_ocr_enabled=allow_document_ocr,
        options=options,
    )
    return ParsePlan(
        mode=mode,
        parser_chain=parser_chain,
        decision_reason=reason,
        options=options,
    )


def _preferred_parser_order(
    *,
    extension: str,
    file_mb: float,
    estimated_pages: int,
    classification: ClassificationResult | None,
    image_vision_enabled: bool,
) -> list[str]:
    # 图片直传由 ParseDecision 路由到 PaddleOCR / MinerU，不能进入本地 parser chain。
    # if is_image_extension(extension):
    #     if not image_vision_enabled:
    #         return []
    #     return ["llm_vision"]

    if is_text_extension(extension):
        return ["text_native"]

    if extension == ".pdf":
        return ["markitdown"]

    if extension == ".docx":
        # Mammoth is the default local DOCX parser; native archive parsing is the fallback.
        return ["mammoth", "docx_native"]

    # 旧链路：.doc 已停用，不再支持上传和解析。
    # if extension == ".doc":
    #     # Convert DOC to DOCX first, then reuse the DOCX parser chain.
    #     return ["doc_markitdown", "doc_mammoth", "doc_native"]

    return _classification_first(classification, extension)


def _classification_first(
    classification: ClassificationResult | None,
    extension: str,
) -> list[str]:
    preferred_order: list[str] = []
    if classification is not None:
        preferred_order.extend([classification.recommended_parser, *classification.fallback_parsers])
    preferred_order.extend(DEFAULT_PARSER_CHAIN.get(extension, []))
    return list(dict.fromkeys(name for name in preferred_order if name))


def _decide_mode_and_options(
    *,
    extension: str,
    file_mb: float,
    estimated_pages: int,
    classification: ClassificationResult | None,
    document_ocr_enabled: bool,
    options: ParserRunOptions,
) -> tuple[str, str]:
    # 图片直传由 ParseDecision 路由到 PaddleOCR / MinerU，不能进入本地 parser chain。
    # if is_image_extension(extension):
    #     if file_mb > _VISION_MAX_MB:
    #         options.timeout_s = max(options.timeout_s, 150)
    #         return "vision_large_image", "Image file routed to LLM vision with extended timeout."
    #     options.asset_image_limit = 1
    #     return "vision_image", "Image file routed directly to LLM vision."

    if is_text_extension(extension):
        options.asset_image_limit = 0
        text_category = categorize_text_extension(extension)
        if text_category == "markdown":
            return "native_markdown", "Markdown file is normalized directly without document conversion."
        if text_category == "structured_text":
            return "native_structured_text", "Structured text file is preserved inside fenced markdown."
        return "native_text", "Text file is normalized directly without document conversion."

    if extension == ".pdf":
        options.asset_image_limit = 0
        options.skip_image_supplement = True
        options.enable_asset_vision_ocr = False
        options.enable_page_vision_ocr = False
        return "local_markitdown", "PDF local fallback is handled by MarkItDown; OCR/layout PDFs should use PaddleOCR or MinerU."

    if extension == ".docx":
        if file_mb >= 10 or estimated_pages >= _LARGE_DOCX_PAGE_COUNT:
            options.asset_image_limit = 10
            options.skip_image_supplement = True
            options.enable_asset_vision_ocr = document_ocr_enabled
            options.asset_vision_ocr_limit = 6
            return "fast_docx", "Large DOCX prefers native parsing and skips secondary image sweep."
        options.enable_asset_vision_ocr = document_ocr_enabled
        options.asset_vision_ocr_limit = 8
        return "balanced_docx", "DOCX uses balanced parser ordering."

    # 旧链路：.doc 已停用，不再支持上传和解析。
    # if extension == ".doc":
    #     if file_mb >= 10 or estimated_pages >= _LARGE_DOCX_PAGE_COUNT:
    #         options.asset_image_limit = 10
    #         options.skip_image_supplement = True
    #         options.enable_asset_vision_ocr = document_ocr_enabled
    #         options.asset_vision_ocr_limit = 6
    #         return "fast_doc_via_docx", "Large DOC converts to DOCX first, then uses the DOCX parser chain."
    #     options.enable_asset_vision_ocr = document_ocr_enabled
    #     options.asset_vision_ocr_limit = 8
    #     return "balanced_doc_via_docx", "DOC converts to DOCX first, then uses the DOCX parser chain."

    return "balanced_default", "Default parser chain selected."


def _derive_parser_parallelism(
    *,
    base_concurrency: int,
    file_mb: float,
    estimated_pages: int,
) -> int:
    dynamic = max(base_concurrency, 1)
    if file_mb >= 5:
        dynamic += 1
    if file_mb >= 15:
        dynamic += 1
    if estimated_pages >= 30:
        dynamic += 1
    if estimated_pages >= 100:
        dynamic += 2
    return min(max(dynamic, _MIN_INTERNAL_PARALLELISM), _MAX_INTERNAL_PARALLELISM)


def _derive_ocr_language_mode(classification: ClassificationResult | None) -> str:
    if classification and classification.detected_language == "en":
        return "en"
    return "zh"


def _llm_visual_calls_available() -> bool:
    return bool(get_env_choice("LLM_API_KEY")) or not llm_provider_requires_api_key(
        base_url=get_env("LLM_BASE_URL")
    )
