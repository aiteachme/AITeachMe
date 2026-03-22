"""Prompt exports for ingest workflows."""

from app.workflows.ingest.prompts.prompts import (
    PROMPTS,
    SYSTEM_PROMPT_IMAGE_PARSE,
    SYSTEM_PROMPT_IMAGE_PARSE_EN,
    SYSTEM_PROMPT_IMAGE_PARSE_ZH,
    get_image_parse_prompt,
)

__all__ = [
    "PROMPTS",
    "SYSTEM_PROMPT_IMAGE_PARSE",
    "SYSTEM_PROMPT_IMAGE_PARSE_ZH",
    "SYSTEM_PROMPT_IMAGE_PARSE_EN",
    "get_image_parse_prompt",
]
