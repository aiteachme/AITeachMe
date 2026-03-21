"""Digest 领域事件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class DigestBuildRequestedEvent:
    """Digest 构建请求已开始执行。"""

    event_name: ClassVar[str] = "digest.build.requested"

    subject: str
    job_id: int
    file_ids: list[int]
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DigestGraphCompletedEvent:
    """图谱构建完成。"""

    event_name: ClassVar[str] = "digest.graph.completed"

    subject: str
    job_id: int
    file_ids: list[int]
    chunk_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DigestGraphFailedEvent:
    """图谱构建失败。"""

    event_name: ClassVar[str] = "digest.graph.failed"

    subject: str
    job_id: int
    file_ids: list[int]
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class CurriculumDeriveCompletedEvent:
    """课程结构派生完成。"""

    event_name: ClassVar[str] = "digest.curriculum.completed"

    subject: str
    graph_job_id: int
    curriculum_job_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class CurriculumDeriveFailedEvent:
    """课程结构派生失败。"""

    event_name: ClassVar[str] = "digest.curriculum.failed"

    subject: str
    graph_job_id: int
    curriculum_job_id: int
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


# ── DocGen 知识文档生成事件 ──


@dataclass(slots=True)
class DocGenRequestedEvent:
    """知识文档生成请求已开始执行。"""

    event_name: ClassVar[str] = "digest.docgen.requested"

    subject: str
    job_id: int
    file_ids: list[int]
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenCompletedEvent:
    """知识文档生成完成。"""

    event_name: ClassVar[str] = "digest.docgen.completed"

    subject: str
    job_id: int
    doc_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenFailedEvent:
    """知识文档生成失败。"""

    event_name: ClassVar[str] = "digest.docgen.failed"

    subject: str
    job_id: int
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


