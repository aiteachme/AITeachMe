"""Shared parser execution types for ingest workflows."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParserRunOptions(BaseModel):
    """Execution options passed to a concrete parser attempt."""

    timeout_s: int = 90
    asset_image_limit: int = 24
    skip_image_supplement: bool = False

