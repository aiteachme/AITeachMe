"""Shared OpenAPI helpers for API routes."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.common import ErrorResponse


_DEFAULT_ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "Request parameters are invalid.",
    404: "Requested resource was not found.",
    409: "The requested operation conflicts with the current resource state.",
    413: "Uploaded file exceeds the configured size limit.",
    422: "Business validation failed even though the request body was well-formed.",
    500: "The server hit an unexpected internal error.",
    502: "The upstream LLM or external dependency call failed.",
    503: "A required dependency or feature is currently unavailable.",
}


def build_error_responses(status_codes: Iterable[int]) -> dict[int, dict[str, object]]:
    """Build a standard OpenAPI error response mapping for route decorators."""

    return {
        status_code: {
            "model": ErrorResponse,
            "description": _DEFAULT_ERROR_DESCRIPTIONS.get(
                status_code,
                "This endpoint may return a business or infrastructure error.",
            ),
        }
        for status_code in status_codes
    }
