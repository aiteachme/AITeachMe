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


_STRUCTURED_REPAIR_CONTEXT_CHARS = 6000
_JSON_SIMPLE_ESCAPE_CHARS = {'"', "\\", "/", "b", "f", "n", "r", "t"}
_COMMON_LATEX_COMMANDS = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "theta",
    "lambda",
    "mu",
    "nabla",
    "pi",
    "rho",
    "sigma",
    "tau",
    "phi",
    "varphi",
    "omega",
    "lim",
    "frac",
    "dfrac",
    "tfrac",
    "sqrt",
    "sum",
    "prod",
    "int",
    "iint",
    "iiint",
    "partial",
    "infty",
    "cdot",
    "times",
    "div",
    "pm",
    "mp",
    "le",
    "leq",
    "ge",
    "geq",
    "ne",
    "neq",
    "neg",
    "approx",
    "equiv",
    "forall",
    "exists",
    "because",
    "to",
    "rightarrow",
    "leftarrow",
    "Rightarrow",
    "Leftrightarrow",
    "in",
    "notin",
    "subset",
    "subseteq",
    "supset",
    "cup",
    "cap",
    "emptyset",
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "ln",
    "log",
    "exp",
    "left",
    "right",
    "langle",
    "rangle",
    "begin",
    "end",
    "cases",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "aligned",
    "align",
    "array",
    "big",
    "Big",
    "bigg",
    "Bigg",
    "text",
    "mathrm",
    "mathbf",
    "mathbb",
    "mathcal",
    "overline",
    "underline",
    "hat",
    "bar",
    "vec",
    "dot",
    "ddot",
    "dots",
    "cdots",
    "ldots",
}


def _clip_structured_repair_text(value: Any, *, limit: int = _STRUCTURED_REPAIR_CONTEXT_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head].rstrip()}\n...\n{text[-tail:].lstrip()}"


def _build_structured_fallback_messages(
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    failure_reason: str | None = None,
    invalid_response: str | None = None,
) -> list[ChatMessage]:
    schema = json.dumps(
        _model_json_schema(response_model),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    fallback_lines = [
        "Return only valid JSON that can be parsed directly.",
        "Do not include markdown code fences, commentary, or extra text.",
        (
            "Every array element must satisfy the schema item type; do not output "
            "sentinel, null, primitive, or omitted placeholder values where the schema expects objects."
        ),
        (
            "Regenerate the full JSON object from scratch. "
            "Do not return a patch or partial continuation."
        ),
        f"The JSON must satisfy this schema: {schema}",
    ]
    clipped_reason = _clip_structured_repair_text(failure_reason)
    clipped_response = _clip_structured_repair_text(invalid_response)
    if clipped_reason or clipped_response:
        repair_context = ["Previous structured output did not validate."]
        if clipped_reason:
            repair_context.extend(["Validation/parsing error:", clipped_reason])
        if clipped_response:
            repair_context.extend(["Previous invalid response:", clipped_response])
        fallback_lines.append("\n".join(repair_context))
    return [
        *messages,
        {"role": "user", "content": "\n".join(fallback_lines)},
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


def _looks_like_latex_escape(value: str, slash_index: int) -> bool:
    command_start = slash_index + 1
    command_end = command_start
    while command_end < len(value) and value[command_end].isalpha():
        command_end += 1
    command = value[command_start:command_end]
    if not command:
        return False
    return command in _COMMON_LATEX_COMMANDS or command[0] == "f"


def _repair_json_string_escapes(raw: str) -> str | None:
    """Escape model-emitted LaTeX backslashes inside JSON strings."""

    if "\\" not in raw:
        return None

    changed = False
    result: list[str] = []
    in_string = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == '"':
            result.append(char)
            if not in_string:
                in_string = True
            else:
                backslash_count = 0
                cursor = index - 1
                while cursor >= 0 and raw[cursor] == "\\":
                    backslash_count += 1
                    cursor -= 1
                if backslash_count % 2 == 0:
                    in_string = False
            index += 1
            continue

        if not in_string or char != "\\":
            result.append(char)
            index += 1
            continue

        next_char = raw[index + 1] if index + 1 < len(raw) else ""
        if next_char == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", raw[index + 2 : index + 6] or ""):
            result.append(raw[index : index + 6])
            index += 6
            continue
        if next_char in {'"', "\\", "/"}:
            result.append(raw[index : index + 2])
            index += 2
            continue
        if _looks_like_latex_escape(raw, index):
            result.append("\\\\")
            changed = True
        elif next_char in _JSON_SIMPLE_ESCAPE_CHARS:
            result.append(raw[index : index + 2])
            index += 2
            continue
        else:
            result.append("\\\\")
            changed = True
        index += 1

    repaired = "".join(result)
    return repaired if changed and repaired != raw else None


def _extract_json_candidates(raw_text: str) -> list[str]:
    stripped = (raw_text or "").strip()
    candidates: list[str] = []
    if stripped:
        repaired_stripped = _repair_json_string_escapes(stripped)
        if repaired_stripped:
            candidates.append(repaired_stripped)
        candidates.append(stripped)

    for match in _JSON_FENCE_RE.finditer(raw_text or ""):
        fenced = match.group(1).strip()
        if fenced:
            repaired_fenced = _repair_json_string_escapes(fenced)
            if repaired_fenced:
                candidates.append(repaired_fenced)
            candidates.append(fenced)

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end != -1 and end >= start:
            sliced = stripped[start : end + 1]
            repaired_sliced = _repair_json_string_escapes(sliced)
            if repaired_sliced:
                candidates.append(repaired_sliced)
            candidates.append(sliced)

    repaired = _repair_truncated_json(stripped)
    if repaired and repaired != stripped:
        repaired_escapes = _repair_json_string_escapes(repaired)
        if repaired_escapes:
            candidates.append(repaired_escapes)
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


def repair_json_string_escapes(raw_text: str) -> str | None:
    """Repair model-emitted LaTeX backslashes before partial JSON parsing."""

    return _repair_json_string_escapes(raw_text)


def parse_structured_response_text(response_model: type[T], raw_text: str) -> T:
    """Parse and validate raw model JSON using the shared repair policy."""

    return _parse_structured_response_text(response_model, raw_text)
