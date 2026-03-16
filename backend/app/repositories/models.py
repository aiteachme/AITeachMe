"""SQLModel table definitions used by the backend."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel, UniqueConstraint


class ParseStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"


class PipelineStage(str, Enum):
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


class Subject(SQLModel, table=True):
    __tablename__ = "subject"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RawFile(SQLModel, table=True):
    __tablename__ = "raw_file"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    filename: str
    filetype: str
    file_path: str
    markdown_path: str | None = None
    asset_dir: str | None = None
    parse_status: str = Field(default=ParseStatus.PENDING)
    parse_error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocSet(SQLModel, table=True):
    __tablename__ = "doc_set"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    title: str
    description: str = ""
    build_status: str = Field(default=PipelineStage.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocBuildJob(SQLModel, table=True):
    __tablename__ = "doc_build_job"

    id: int | None = Field(default=None, primary_key=True)
    doc_set_id: int = Field(foreign_key="doc_set.id", index=True)
    stage: str = Field(default=PipelineStage.PENDING)
    progress: int = 0
    message: str = ""
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocSetSourceFile(SQLModel, table=True):
    __tablename__ = "doc_set_source_file"
    __table_args__ = (UniqueConstraint("doc_set_id", "raw_file_id"),)

    id: int | None = Field(default=None, primary_key=True)
    doc_set_id: int = Field(foreign_key="doc_set.id", index=True)
    raw_file_id: int = Field(foreign_key="raw_file.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    __tablename__ = "document"

    id: int | None = Field(default=None, primary_key=True)
    doc_set_id: int = Field(foreign_key="doc_set.id", index=True)
    subject: str = Field(index=True)
    source_file_id: int = Field(foreign_key="raw_file.id", index=True)
    title: str
    markdown_content: str = ""
    pipeline_stage: str = Field(default=PipelineStage.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunk"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    title: str
    level: int
    header_path: str
    chunk_index: int
    content: str


class DocumentOutlineNode(SQLModel, table=True):
    __tablename__ = "document_outline_node"

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    parent_id: int | None = Field(default=None, foreign_key="document_outline_node.id")
    title: str
    level: int
    order_index: int


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_message"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    turn_id: str
    role: str
    content: str
    contexts: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Exam(SQLModel, table=True):
    __tablename__ = "exam"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


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


class ExamSubmission(SQLModel, table=True):
    __tablename__ = "exam_submission"

    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    user_id: str = Field(default="local")
    score: float
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


class AnswerRecord(SQLModel, table=True):
    __tablename__ = "answer_record"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: int = Field(foreign_key="exam_submission.id")
    question_id: int = Field(foreign_key="question.id")
    user_answer: str
    is_correct: bool


class Mistake(SQLModel, table=True):
    __tablename__ = "mistake"

    id: int | None = Field(default=None, primary_key=True)
    answer_record_id: int = Field(foreign_key="answer_record.id")
    analysis: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profile"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    knowledge_point: str
    mastery: float | None = None
    attempts: int = 0
    correct: int = 0
    updated_at: datetime = Field(default_factory=datetime.utcnow)
