"""
所有 SQLModel 表模型和枚举定义

两层模型设计：SQLModel(table=True) 同时作为 ORM 和领域实体。
枚举（ParseStatus、PipelineStage、QuestionType、Difficulty）定义在此。
"""

from enum import Enum
from datetime import datetime
from typing import Any, Optional
from sqlmodel import SQLModel, Field, Column, UniqueConstraint
import sqlalchemy as sa


# ─── 枚举 ───


class ParseStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"


class PipelineStage(str, Enum):
    """Digest 流水线阶段，支持断点恢复"""
    PENDING = "pending"
    CLEANED = "cleaned"
    OUTLINED = "outlined"
    STORED = "stored"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    FAILED = "failed"


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ─── RawFile ───


class RawFile(SQLModel, table=True):
    __tablename__ = "raw_file"

    id: int | None = Field(default=None, primary_key=True)
    subject: str
    filename: str
    filetype: str
    file_path: str
    parse_status: str = Field(default=ParseStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Knowledge ───


class Knowledge(SQLModel, table=True):
    __tablename__ = "knowledge"

    id: int | None = Field(default=None, primary_key=True)
    subject: str
    raw_file_id: int = Field(
        sa_column=Column(sa.Integer, sa.ForeignKey("raw_file.id"), unique=True)
    )
    title: str
    markdown_content: str = ""
    pipeline_stage: str = Field(default=PipelineStage.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Chunk（unique(knowledge_id, chunk_index)）───


class Chunk(SQLModel, table=True):
    __tablename__ = "chunk"
    __table_args__ = (UniqueConstraint("knowledge_id", "chunk_index"),)

    id: int | None = Field(default=None, primary_key=True)
    knowledge_id: int = Field(foreign_key="knowledge.id")
    title: str
    level: int  # 1~3
    header_path: str
    chunk_index: int
    content: str


# ─── KnowledgeGraphNode ───


class KnowledgeGraphNode(SQLModel, table=True):
    __tablename__ = "knowledge_graph_node"

    id: int | None = Field(default=None, primary_key=True)
    knowledge_id: int = Field(foreign_key="knowledge.id")
    parent_id: int | None = Field(default=None, foreign_key="knowledge_graph_node.id")
    title: str
    level: int
    order_index: int


# ─── ChatMessage（turn_id 为 UUID 字符串）───


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_message"

    id: int | None = Field(default=None, primary_key=True)
    subject: str
    user_id: str = Field(default="local")
    turn_id: str  # UUID 字符串
    role: str  # user / assistant
    content: str
    contexts: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Exam ───


class Exam(SQLModel, table=True):
    __tablename__ = "exam"

    id: int | None = Field(default=None, primary_key=True)
    subject: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Question（options 使用 sa.JSON）───


class Question(SQLModel, table=True):
    __tablename__ = "question"

    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    question_key: str
    type: str
    stem: str
    options: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    answer: str
    explanation: str
    knowledge_point: str
    difficulty: str


# ─── ExamSubmission ───


class ExamSubmission(SQLModel, table=True):
    __tablename__ = "exam_submission"

    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    user_id: str = Field(default="local")
    score: float
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


# ─── AnswerRecord ───


class AnswerRecord(SQLModel, table=True):
    __tablename__ = "answer_record"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: int = Field(foreign_key="exam_submission.id")
    question_id: int = Field(foreign_key="question.id")
    user_answer: str
    is_correct: bool


# ─── Mistake ───


class Mistake(SQLModel, table=True):
    __tablename__ = "mistake"

    id: int | None = Field(default=None, primary_key=True)
    answer_record_id: int = Field(foreign_key="answer_record.id")
    analysis: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── UserProfile ───


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profile"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local")
    subject: str
    knowledge_point: str
    mastery: float | None = None
    attempts: int = 0
    correct: int = 0
    updated_at: datetime = Field(default_factory=datetime.utcnow)
