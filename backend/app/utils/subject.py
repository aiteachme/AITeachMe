"""
学科名称校验工具

规则：仅允许 [a-zA-Z0-9_-]，长度 1~64，拒绝路径穿越字符，存储为小写。
"""

import re
from app.core.exceptions import InvalidSubjectError

_SUBJECT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_PATH_TRAVERSAL_CHARS = frozenset(["/", "\\", ".."])


def validate_subject(subject: str) -> str:
    """校验学科名称，通过后返回小写形式；不合法时抛出 InvalidSubjectError。"""
    # 拒绝路径穿越字符
    if any(c in subject for c in ("/", "\\")):
        raise InvalidSubjectError(subject)
    if ".." in subject:
        raise InvalidSubjectError(subject)

    if not _SUBJECT_PATTERN.match(subject):
        raise InvalidSubjectError(subject)

    return subject.lower()
