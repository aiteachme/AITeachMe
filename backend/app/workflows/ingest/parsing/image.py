"""Image parser used by the ingest workflow."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env, get_env_choice
from app.shared.infra.exceptions import FileParseError, LLMCallError, MissingLLMApiKeyError
from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.settings.support import llm_provider_requires_api_key
from app.shared.infra.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, USER
from app.workflows.ingest.parsing.types import ParserRunOptions
from app.workflows.ingest.parsing.utils import MIME_MAP, save_image_bytes
from app.workflows.ingest.parsing.prompts import get_image_parse_prompt


logger = structlog.get_logger()

_UNCLEAR_MARKDOWN = "[unclear]"
_VisualModelSelector = Literal["vision", "ocr"]


async def parse_image_with_llm_vision(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Convert a directly uploaded image into markdown via the vision model."""

    path = Path(file_path)
    logger.info(
        "parse_image_start",
        filename=path.name,
        ocr_language_mode=options.ocr_language_mode,
        model_selector="vision",
    )

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
            model_selector="vision",
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
    model_selector: _VisualModelSelector = "vision",
) -> str:
    """Run one visual model on image bytes and return markdown text."""

    if not image_bytes or len(image_bytes) < 100:
        logger.warning("parse_image_bytes_skipped", reason="image_bytes_too_small", size=len(image_bytes))
        return _UNCLEAR_MARKDOWN

    resolved_model = _resolve_visual_model(model_selector)
    api_key, base_url = _resolve_visual_endpoint(model_selector)
    if llm_provider_requires_api_key(base_url=base_url) and not api_key:
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
        completion_kwargs = {
            "timeout": 120,
            "temperature": 0.3,
        }
        if base_url:
            completion_kwargs["api_base"] = base_url
        if api_key is not None:
            completion_kwargs["api_key"] = api_key
        text = await acompletion(
            messages=messages,
            task_type=TaskType.VISION,
            model=resolved_model,
            **completion_kwargs,
        )
    except Exception as exc:
        logger.error(
            "parse_image_bytes_llm_failed",
            error=str(exc),
            mime_type=mime_type,
            language_mode=language_mode,
            model_selector=model_selector,
            model=resolved_model,
            exc_info=True,
        )
        return _UNCLEAR_MARKDOWN

    if not text or not text.strip():
        logger.warning(
            "parse_image_bytes_empty_response",
            mime_type=mime_type,
            model_selector=model_selector,
            model=resolved_model,
        )
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
        logger.warning(
            "parse_image_bytes_refused",
            response_preview=text[:100],
            model_selector=model_selector,
            model=resolved_model,
        )
        return _UNCLEAR_MARKDOWN

    return text


def _resolve_visual_model(model_selector: _VisualModelSelector) -> str:
    settings = get_settings()
    if model_selector == "vision":
        candidate = (settings.models.vision or "").strip() or (settings.models.primary or "").strip()
        if candidate:
            return candidate
        raise LLMCallError(reason="models.vision is not configured")

    candidate = (settings.models.ocr or "").strip() or (settings.models.primary or "").strip()
    if candidate:
        return candidate
    raise LLMCallError(reason="models.ocr is not configured")


def _resolve_visual_endpoint(
    model_selector: _VisualModelSelector,
) -> tuple[str | None, str]:
    if model_selector == "ocr":
        api_key = (
            (get_env_choice("OCR_API_KEY") or "").strip()
            or (get_env_choice("LLM_API_KEY") or "").strip()
            or None
        )
        base_url = (
            (get_env("OCR_BASE_URL") or "").strip()
            or get_env("LLM_BASE_URL", "https://api.openai.com/v1")
        )
        return api_key, base_url

    api_key = (get_env_choice("LLM_API_KEY") or "").strip() or None
    base_url = get_env("LLM_BASE_URL", "https://api.openai.com/v1")
    return api_key, base_url
