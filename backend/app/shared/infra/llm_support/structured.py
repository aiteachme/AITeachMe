"""Structured output parsing helpers for LiteLLM-backed calls."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMCallError

T = TypeVar("T")

JSON_OBJECT_RESPONSE_FORMAT: dict[str, str] = {"type": "json_object"}
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _serialize_structured_result(result: Any) -> str:
    serializer = getattr(result, "model_dump_json", None)
    if callable(serializer):
        return serializer()
    return json.dumps(result, ensure_ascii=False, default=str)


def _model_json_schema(response_model: type[T]) -> dict[str, Any]:
    schema_builder = getattr(response_model, "model_json_schema", None)
    if callable(schema_builder):
        return schema_builder()
    legacy_builder = getattr(response_model, "schema", None)
    if callable(legacy_builder):
        return legacy_builder()
    return {}


def _build_structured_fallback_messages(
    response_model: type[T],
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    schema = json.dumps(
        _model_json_schema(response_model),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    fallback_instruction = (
        "Return only valid JSON that can be parsed directly. "
        "Do not include markdown code fences, commentary, or extra text. "
        f"The JSON must satisfy this schema: {schema}"
    )
    return [
        *messages,
        {"role": "user", "content": fallback_instruction},
    ]


def _structured_model_validate(response_model: type[T], payload: Any) -> T:
    validator = getattr(response_model, "model_validate", None)
    if callable(validator):
        return validator(payload)
    legacy_validator = getattr(response_model, "parse_obj", None)
    if callable(legacy_validator):
        return legacy_validator(payload)
    return response_model(**payload)


def _repair_truncated_json(raw: str) -> str | None:
    """Try to fix truncated JSON by appending missing closing brackets/braces."""

    stripped = raw.rstrip()
    if not stripped:
        return None

    stack: list[str] = []
    in_string = False
    escape_next = False
    for char in stripped:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in ("{", "["):
            stack.append("}" if char == "{" else "]")
        elif char in ("}", "]"):
            if stack and stack[-1] == char:
                stack.pop()

    if not stack:
        return None
    if in_string:
        stripped += '"'
    stripped += "".join(reversed(stack))
    return stripped


def _extract_json_candidates(raw_text: str) -> list[str]:
    stripped = (raw_text or "").strip()
    candidates: list[str] = []
    if stripped:
        candidates.append(stripped)

    for match in _JSON_FENCE_RE.finditer(raw_text or ""):
        fenced = match.group(1).strip()
        if fenced:
            candidates.append(fenced)

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end != -1 and end >= start:
            candidates.append(stripped[start : end + 1])

    repaired = _repair_truncated_json(stripped)
    if repaired and repaired != stripped:
        candidates.append(repaired)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _parse_structured_response_text(response_model: type[T], raw_text: str) -> T:
    candidates = _extract_json_candidates(raw_text)
    errors: list[str] = []
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"json_decode_error:{exc.msg}")
            continue
        try:
            return _structured_model_validate(response_model, payload)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"model_validate_error:{exc}")

    reason = errors[0] if errors else "empty_or_non_json_response"
    raise LLMCallError(reason=f"structured_parse_failed: {reason}")
