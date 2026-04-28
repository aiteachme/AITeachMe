"""Subject external identifier helpers."""

from __future__ import annotations

import re
from secrets import choice

from app.shared.infra.exceptions import InvalidSubjectError

try:
    from nanoid import generate as nanoid_generate
except ImportError:
    nanoid_generate = None

SUBJECT_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
SUBJECT_ID_PREFIX = "subj_"
SUBJECT_ID_SIZE = 12
GLOBAL_SUBJECT = ""
GLOBAL_SUBJECT_ALIASES = frozenset({"", "global", "_global", "__global__"})
_SUBJECT_ID_PATTERN = re.compile(r"^subj_[a-z0-9]{12}$")


def _generate_suffix() -> str:
    if nanoid_generate is not None:
        return nanoid_generate(SUBJECT_ID_ALPHABET, SUBJECT_ID_SIZE)
    return "".join(choice(SUBJECT_ID_ALPHABET) for _ in range(SUBJECT_ID_SIZE))


def generate_subject_id() -> str:
    """Generate a stable opaque public subject_id."""

    return f"{SUBJECT_ID_PREFIX}{_generate_suffix()}"


def validate_subject_id(subject_id: str) -> str:
    """Validate and normalize a subject_id."""

    normalized = subject_id.strip().lower()
    if any(item in normalized for item in ("/", "\\")) or ".." in normalized:
        raise InvalidSubjectError(subject_id)
    if not _SUBJECT_ID_PATTERN.match(normalized):
        raise InvalidSubjectError(subject_id)
    return normalized


def is_global_subject(subject_id: str | None) -> bool:
    """Return whether a raw subject token means the global chat scope."""

    normalized = (subject_id or "").strip().lower()
    return normalized in GLOBAL_SUBJECT_ALIASES


def normalize_subject_scope(
    subject_id: str | None,
    *,
    allow_global: bool = False,
) -> str:
    """Normalize a subject id, optionally accepting the global chat scope."""

    if allow_global and is_global_subject(subject_id):
        return GLOBAL_SUBJECT
    return validate_subject_id(subject_id or "")
