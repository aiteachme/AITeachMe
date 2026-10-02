"""Frozen V1 generation behavior, isolated from the generic text-form engine."""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.shared.kernel.question_type_compatibility import is_legacy_question_type


_NUMBERED_REQUIREMENT_RE = re.compile(r"(?:\A|\n[ \t]*\n)[ \t]*\((\d+)\)[ \t]*\S")
_STACKED_CHINESE_FRAMING_RE = re.compile(r"(?:请)?像向[^\n。！？]{1,48}(?:讲解|说明)[^\n。！？]{0,8}一样")


def _uses_legacy_feynman_contract(definition: Mapping[str, object]) -> bool:
    return is_legacy_question_type(definition) and definition.get("template_key") == "feynman_explanation_v1"


def legacy_generation_contract(definition: Mapping[str, object]) -> str:
    if not _uses_legacy_feynman_contract(definition):
        return ""
    return (
        "For the Feynman explanation template, the stem must contain exactly four "
        "blank-line-separated requirements numbered (1) through (4), covering the core meaning, "
        "reasoning, one concrete example, and one applicability boundary in that order. "
    )


def validate_legacy_question_stem(definition: Mapping[str, object], stem: str) -> None:
    if not _uses_legacy_feynman_contract(definition):
        return
    normalized = str(stem or "").strip()
    if _STACKED_CHINESE_FRAMING_RE.search(normalized):
        raise ValueError("feynman question stem contains stacked learner-facing wording")
    if [int(match.group(1)) for match in _NUMBERED_REQUIREMENT_RE.finditer(normalized)] != [1, 2, 3, 4]:
        raise ValueError(
            "feynman question stem must list exactly four blank-line-separated "
            "requirements numbered (1) through (4)"
        )
