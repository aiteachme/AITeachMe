"""学科标识校验工具。"""

from __future__ import annotations

import re

from app.core.exceptions import InvalidSubjectError

_SUBJECT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_subject(subject: str) -> str:
    """校验并规范化学科标识。"""

    if any(item in subject for item in ("/", "\\")) or ".." in subject:
        raise InvalidSubjectError(subject)
    if not _SUBJECT_PATTERN.match(subject):
        raise InvalidSubjectError(subject)
    return subject.lower()
