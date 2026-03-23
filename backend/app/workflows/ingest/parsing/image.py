"""Image parser used by the ingest workflow."""

from __future__ import annotations

import base64
from pathlib import Path

import structlog

from app.core.exceptions import FileParseError
from app.core.llm import acompletion
from app.core.prompt_loader import populate_prompt
from app.schemas.llm import ChatMessage, USER
from app.workflows.ingest.parsing.types import ParserRunOptions
from app.workflows.ingest.parsing.utils import MIME_MAP, save_image_bytes
from app.workflows.ingest.prompts import get_image_parse_prompt


logger = structlog.get_logger()


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
    text = await acompletion(messages)
    if not text or not text.strip():
        raise FileParseError("image_bytes", reason="Image OCR returned empty markdown.")
    return text
