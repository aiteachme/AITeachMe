"""Course external identifier helpers."""

from __future__ import annotations

import re
from secrets import choice

from app.shared.infra.exceptions import InvalidCourseError

try:
    from nanoid import generate as nanoid_generate
except ImportError:
    nanoid_generate = None

COURSE_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
COURSE_ID_PREFIX = "course_"
COURSE_ID_SIZE = 12
GLOBAL_COURSE = ""
GLOBAL_COURSE_ALIASES = frozenset({"", "global", "_global", "__global__"})
_COURSE_ID_PATTERN = re.compile(
    rf"^{re.escape(COURSE_ID_PREFIX)}[a-z0-9]{{{COURSE_ID_SIZE}}}$"
)


def _generate_suffix() -> str:
    if nanoid_generate is not None:
        return nanoid_generate(COURSE_ID_ALPHABET, COURSE_ID_SIZE)
    return "".join(choice(COURSE_ID_ALPHABET) for _ in range(COURSE_ID_SIZE))


def generate_course_id() -> str:
    """Generate a stable opaque public course_id."""

    return f"{COURSE_ID_PREFIX}{_generate_suffix()}"


def validate_course_id(course_id: str) -> str:
    """Validate and normalize a course_id."""

    normalized = course_id.strip().lower()
    if any(item in normalized for item in ("/", "\\")) or ".." in normalized:
        raise InvalidCourseError(course_id)
    if not _COURSE_ID_PATTERN.match(normalized):
        raise InvalidCourseError(course_id)
    return normalized


def is_global_course(course_id: str | None) -> bool:
    """Return whether a raw course token means the global chat scope."""

    normalized = (course_id or "").strip().lower()
    return normalized in GLOBAL_COURSE_ALIASES


def normalize_course_scope(
    course_id: str | None,
    *,
    allow_global: bool = False,
) -> str:
    """Normalize a course id, optionally accepting the global chat scope."""

    if allow_global and is_global_course(course_id):
        return GLOBAL_COURSE
    return validate_course_id(course_id or "")
