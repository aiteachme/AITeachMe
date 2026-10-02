"""Validate and normalize answers against a frozen custom question schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


MAX_STRUCTURED_ANSWER_CHARS = 20_000


class AnswerPayloadError(ValueError):
    """Raised when a structured answer does not match its frozen schema."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class NormalizedAnswer:
    payload: dict[str, str]
    display_text: str


def normalize_custom_answer(
    answer_schema: Mapping[str, object],
    *,
    answer: str | None,
    answer_payload: Mapping[str, str] | None,
) -> NormalizedAnswer:
    """Return a stable payload and plain-text projection used by existing graders/UI."""

    raw_fields = answer_schema.get("fields")
    fields = [item for item in raw_fields if isinstance(item, Mapping)] if isinstance(raw_fields, list) else []
    if not fields:
        raise AnswerPayloadError(
            "QUESTION_ANSWER_SCHEMA_INVALID",
            "题目的作答结构已损坏，请重新生成题目。",
        )

    field_keys = [str(item.get("key") or "").strip() for item in fields]
    if any(not key for key in field_keys) or len(set(field_keys)) != len(field_keys):
        raise AnswerPayloadError(
            "QUESTION_ANSWER_SCHEMA_INVALID",
            "题目的作答结构已损坏，请重新生成题目。",
        )

    if answer_payload is None:
        if len(fields) != 1:
            raise AnswerPayloadError(
                "QUESTION_ANSWER_PAYLOAD_REQUIRED",
                "该题型需要按字段提交作答内容。",
            )
        source: dict[str, str] = {field_keys[0]: str(answer or "")}
    else:
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in answer_payload.items()):
            raise AnswerPayloadError("QUESTION_ANSWER_FIELD_TYPE", "作答字段必须是文本。")
        source = dict(answer_payload)
        extra_keys = sorted(set(source) - set(field_keys))
        if extra_keys:
            raise AnswerPayloadError(
                "QUESTION_ANSWER_FIELD_UNKNOWN",
                f"作答包含未定义字段：{', '.join(extra_keys)}。",
            )

    normalized: dict[str, str] = {}
    for field, key in zip(fields, field_keys, strict=True):
        if bool(field.get("required")) and key not in source:
            raise AnswerPayloadError(
                "QUESTION_ANSWER_FIELD_REQUIRED",
                f"缺少必填作答字段：{field.get('label') or key}。",
            )
        value = str(source.get(key, ""))
        # Stored V1 test fixtures and old snapshots may omit the optional
        # presentation limits. The package validator supplies the real bound;
        # runtime normalization uses the global safety cap for compatibility.
        max_length = max(1, int(field.get("max_length") or MAX_STRUCTURED_ANSWER_CHARS))
        min_length = max(0, int(field.get("min_length") or 0))
        if len(value) > max_length:
            raise AnswerPayloadError(
                "QUESTION_ANSWER_TOO_LONG",
                f"“{field.get('label') or key}”不能超过 {max_length} 个字符。",
            )
        # Empty values represent unanswered fields and remain submittable. Once a
        # learner starts answering, enforce the package's minimum useful length.
        if value.strip() and len(value.strip()) < min_length:
            raise AnswerPayloadError(
                "QUESTION_ANSWER_TOO_SHORT",
                f"“{field.get('label') or key}”至少需要 {min_length} 个字符。",
            )
        normalized[key] = value

    if sum(len(value) for value in normalized.values()) > MAX_STRUCTURED_ANSWER_CHARS:
        raise AnswerPayloadError(
            "QUESTION_ANSWER_TOO_LONG",
            f"作答内容合计不能超过 {MAX_STRUCTURED_ANSWER_CHARS} 个字符。",
        )

    if len(fields) == 1:
        display_text = normalized[field_keys[0]]
    else:
        display_text = "\n\n".join(
            f"{field.get('label') or key}：{normalized[key]}"
            for field, key in zip(fields, field_keys, strict=True)
        )
    return NormalizedAnswer(payload=normalized, display_text=display_text)


def normalize_custom_reference_answer(
    answer_schema: Mapping[str, object],
    *,
    answer: str | None,
    answer_payload: Mapping[str, str] | None,
) -> NormalizedAnswer:
    """Normalize a generated reference answer against the frozen field contract.

    A single-field V1 package may continue returning ``correct_answer``. V2 and
    structured packages must return the field-keyed payload so the reference
    answer cannot be silently collapsed into the first field.
    """

    raw_fields = answer_schema.get("fields")
    fields = [item for item in raw_fields if isinstance(item, Mapping)] if isinstance(raw_fields, list) else []
    if len(fields) != 1 and answer_payload is None:
        raise AnswerPayloadError(
            "QUESTION_REFERENCE_PAYLOAD_REQUIRED",
            "多字段题型必须按字段返回参考答案。",
        )
    normalized = normalize_custom_answer(
        answer_schema,
        answer=answer,
        answer_payload=answer_payload,
    )
    for field in fields:
        if field.get("required") and not normalized.payload[str(field["key"])].strip():
            raise AnswerPayloadError("QUESTION_REFERENCE_FIELD_EMPTY", "参考答案的必填字段不能为空。")
    return normalized


__all__ = [
    "AnswerPayloadError",
    "MAX_STRUCTURED_ANSWER_CHARS",
    "NormalizedAnswer",
    "normalize_custom_answer",
    "normalize_custom_reference_answer",
]
