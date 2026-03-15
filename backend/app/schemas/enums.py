"""API-facing enums used to enrich generated OpenAPI/Redoc documentation."""

from __future__ import annotations

from enum import Enum


class PipelineStatusStage(str, Enum):
    """High-level upload pipeline stages exposed to API callers."""

    UPLOAD = "upload"
    PARSE = "parse"
    DIGEST = "digest"
    DONE = "done"
    FAILED = "failed"


class ParseStatusValue(str, Enum):
    """Raw file parsing status values returned by upload-related endpoints."""

    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"


class PipelineStageValue(str, Enum):
    """Digest pipeline stage values returned by knowledge-related endpoints."""

    PENDING = "pending"
    CLEANED = "cleaned"
    OUTLINED = "outlined"
    STORED = "stored"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    FAILED = "failed"


class ChatRoleValue(str, Enum):
    """Chat role values persisted in history and surfaced via API responses."""

    USER = "user"
    ASSISTANT = "assistant"


class QuestionTypeValue(str, Enum):
    """Supported question type values exposed by exam endpoints."""

    SINGLE_CHOICE = "single_choice"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"


class DifficultyValue(str, Enum):
    """Supported question difficulty values exposed by exam endpoints."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
