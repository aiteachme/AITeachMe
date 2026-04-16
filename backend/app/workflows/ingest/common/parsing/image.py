"""Image parser used by the ingest workflow."""

from __future__ import annotations

import base64
from pathlib import Path

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import FileParseError, MissingLLMApiKeyError
from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, USER
from app.workflows.ingest.common.parsing.types import ParserRunOptions
from app.workflows.ingest.common.parsing.utils import MIME_MAP, save_image_bytes
from app.workflows.ingest.common.parsing.prompts import get_image_parse_prompt


logger = structlog.get_logger()

_UNCLEAR_MARKDOWN = "[unclear]"


async def parse_image_with_llm_vision(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Convert an image into markdown and persist the original asset."""

    path = Path(file_path)
    logger.info("parse_image_start", filename=path.name, ocr_language_mode=options.ocr_language_mode)

    image_bytes = path.read_bytes()
    original_filename = save_image_bytes(
        image_bytes,
        asset_dir,
        name_hint=f"original_{path.stem}",
        ext=path.suffix,
        name_prefix=options.asset_name_prefix,
    )

    try:
        mime_type = MIME_MAP.get(path.suffix.lower(), "image/png")
        text = await parse_image_bytes_with_llm_vision(
            image_bytes,
            mime_type=mime_type,
            language_mode=options.ocr_language_mode,
        )
    except Exception as exc:
        logger.error("parse_image_failed", filename=path.name, error=str(exc))
        raise FileParseError(path.name, reason=f"Image parsing failed: {exc}") from exc

    if not text.strip():
        raise FileParseError(path.name, reason="Image parsing returned empty markdown.")

    return f"{text.strip()}\n\n![Original image]({original_filename})\n"


async def parse_image_bytes_with_llm_vision(
    image_bytes: bytes,
    *,
    mime_type: str,
    language_mode: str = "zh",
) -> str:
    """Run LLM vision parsing on image bytes and return markdown text."""

    if not image_bytes or len(image_bytes) < 100:
        logger.warning("parse_image_bytes_skipped", reason="image_bytes_too_small", size=len(image_bytes))
        return _UNCLEAR_MARKDOWN

    settings = get_settings()
    ocr_model = settings.ocr_model or settings.llm_model
    ocr_api_key = (get_env("OCR_API_KEY") or get_env("LLM_API_KEY") or "").strip()
    ocr_base_url = (
        get_env("OCR_BASE_URL")
        or get_env("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    if not ocr_api_key:
        raise MissingLLMApiKeyError()

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    prompt = populate_prompt(get_image_parse_prompt(language_mode))
    messages: list[ChatMessage] = [
        {
            "role": USER,
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        }
    ]

    try:
        text = await acompletion(
            messages=messages,
            task_type=TaskType.VISION,
            model=f"openai/{ocr_model}",
            api_base=ocr_base_url,
            api_key=ocr_api_key,
            timeout=120,
            temperature=0.3,
        )
    except Exception as exc:
        logger.error(
            "parse_image_bytes_llm_failed",
            error=str(exc),
            mime_type=mime_type,
            language_mode=language_mode,
            ocr_model=ocr_model,
            exc_info=True,
        )
        return _UNCLEAR_MARKDOWN

    if not text or not text.strip():
        logger.warning("parse_image_bytes_empty_response", mime_type=mime_type, ocr_model=ocr_model)
        return _UNCLEAR_MARKDOWN

    text_lower = text.lower().strip()
    refuse_patterns = [
        "请提供",
        "please provide",
        "i cannot see",
        "no image",
        "unable to process",
    ]
    if any(pattern in text_lower for pattern in refuse_patterns):
        logger.warning("parse_image_bytes_refused", response_preview=text[:100], ocr_model=ocr_model)
        return _UNCLEAR_MARKDOWN

    return text

