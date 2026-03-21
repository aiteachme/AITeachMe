"""学科外部标识工具。"""

from __future__ import annotations

import re
from secrets import choice

from app.core.exceptions import InvalidSubjectError

try:
    from nanoid import generate as nanoid_generate
except ImportError:
    nanoid_generate = None

SUBJECT_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
SUBJECT_ID_PREFIX = "subj_"
SUBJECT_ID_SIZE = 12
_SUBJECT_ID_PATTERN = re.compile(r"^subj_[a-z0-9]{12}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _generate_suffix() -> str:
    if nanoid_generate is not None:
        return nanoid_generate(SUBJECT_ID_ALPHABET, SUBJECT_ID_SIZE)
    return "".join(choice(SUBJECT_ID_ALPHABET) for _ in range(SUBJECT_ID_SIZE))


def generate_subject_id() -> str:
    """生成对外稳定的短 opaque subject_id。"""

    return f"{SUBJECT_ID_PREFIX}{_generate_suffix()}"


def validate_subject_id(subject_id: str) -> str:
    """校验并规范化 subject_id。"""

    normalized = subject_id.strip().lower()
    if any(item in normalized for item in ("/", "\\")) or ".." in normalized:
        raise InvalidSubjectError(subject_id)
    if not _SUBJECT_ID_PATTERN.match(normalized):
        raise InvalidSubjectError(subject_id)
    return normalized


def validate_subject(subject: str) -> str:
    """兼容当前代码中仍在使用的 slug 校验。"""

    normalized = subject.strip().lower()
    if any(item in normalized for item in ("/", "\\")) or ".." in normalized:
        raise InvalidSubjectError(subject)
    if normalized.startswith(SUBJECT_ID_PREFIX):
        return validate_subject_id(normalized)
    if not _SLUG_PATTERN.match(normalized):
        raise InvalidSubjectError(subject)
    return normalized
