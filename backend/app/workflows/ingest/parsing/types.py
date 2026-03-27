"""Shared parser execution types for ingest workflows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParserRunOptions(BaseModel):
    """Execution options passed to a concrete parser attempt."""

    timeout_s: int = 60
    asset_image_limit: int = 32
    skip_image_supplement: bool = False
    asset_name_prefix: str = ""
    parser_parallelism: int = 8
    enable_page_vision_ocr: bool = False
    enable_asset_vision_ocr: bool = False
    asset_vision_ocr_limit: int = 16
    llm_ocr_page_concurrency: int = 10
    ocr_page_limit: int = 24
    ocr_text_char_threshold: int = 80
    asset_gallery_limit: int = 24
    ocr_language_mode: Literal["zh", "en"] = "zh"
