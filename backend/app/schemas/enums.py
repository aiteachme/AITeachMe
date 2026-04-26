"""接口文档使用的枚举。"""

from __future__ import annotations

from enum import Enum


class TaskStatusValue(str, Enum):
    """任务状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DigestStepValue(str, Enum):
    """知识构建步骤。"""

    CLEANED = "cleaned"
    OUTLINED = "outlined"
    STORED = "stored"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"


class ChatRoleValue(str, Enum):
    """聊天角色。"""

    USER = "user"
    ASSISTANT = "assistant"


class QuestionTypeValue(str, Enum):
    """题目类型。"""

    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"


class DifficultyValue(str, Enum):
    """题目难度。"""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
