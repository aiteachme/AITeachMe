"""Domain/kernel-level shared primitives."""

from app.shared.kernel.events import DomainEvent, EventPublisher
from app.shared.kernel.exceptions import AITeachMeError
from app.shared.kernel.ids import require_id, require_uid
from app.shared.kernel.question_types import (
    CANONICAL_QUESTION_TYPE_KEYS,
    QuestionTypeLiteral,
    UnsupportedQuestionTypeError,
    is_supported_question_type,
    require_supported_question_type_key,
)
from app.shared.kernel.time import utcnow

__all__ = [
    "AITeachMeError",
    "DomainEvent",
    "EventPublisher",
    "CANONICAL_QUESTION_TYPE_KEYS",
    "QuestionTypeLiteral",
    "UnsupportedQuestionTypeError",
    "is_supported_question_type",
    "require_id",
    "require_supported_question_type_key",
    "require_uid",
    "utcnow",
]
