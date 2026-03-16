"""项目统一使用的枚举定义。"""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """异步任务通用状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DigestStep(str, Enum):
    """知识构建的细粒度步骤。"""

    CLEANED = "cleaned"
    OUTLINED = "outlined"
    STORED = "stored"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"


class QuestionType(str, Enum):
    """题目类型。"""

    SINGLE_CHOICE = "single_choice"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"


class Difficulty(str, Enum):
    """题目难度。"""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
