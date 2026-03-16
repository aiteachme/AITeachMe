"""测验相关模型定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


class Exam(SQLModel, table=True):
    """试卷主表。"""

    __tablename__ = "exam"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Question(SQLModel, table=True):
    """试卷题目。"""

    __tablename__ = "question"

    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id", index=True)
    question_key: str = Field(index=True)
    type: str
    stem: str
    options: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    answer: str
    explanation: str
    knowledge_point: str = Field(index=True)
    difficulty: str


class ExamSubmission(SQLModel, table=True):
    """交卷记录。"""

    __tablename__ = "exam_submission"

    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id", index=True)
    user_id: str = Field(default="local", index=True)
    score: float
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


class AnswerRecord(SQLModel, table=True):
    """单题作答记录。"""

    __tablename__ = "answer_record"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: int = Field(foreign_key="exam_submission.id", index=True)
    question_id: int = Field(foreign_key="question.id", index=True)
    user_answer: str
    is_correct: bool


class Mistake(SQLModel, table=True):
    """错题本记录。"""

    __tablename__ = "mistake"

    id: int | None = Field(default=None, primary_key=True)
    answer_record_id: int = Field(foreign_key="answer_record.id", index=True)
    analysis: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
