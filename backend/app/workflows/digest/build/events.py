"""Events for unified build coordination."""

from __future__ import annotations

from pydantic import BaseModel


class UnifiedBuildStartedEvent(BaseModel):
    """统一构建开始事件"""

    subject: str
    file_count: int


class UnifiedBuildCompletedEvent(BaseModel):
    """统一构建完成事件"""

    subject: str
    doc_count: int
    chunk_count: int
    new_node_count: int
    new_edge_count: int
    elapsed_ms: int


class UnifiedBuildFailedEvent(BaseModel):
    """统一构建失败事件"""

    subject: str
    error_message: str


class ChapterPriorsPublishedEvent(BaseModel):
    """章节先验发布事件（doc lane → kg lane）"""

    subject: str
    chapter_count: int


class TopicAnchorSnapshotPublishedEvent(BaseModel):
    """主题锚点快照发布事件（kg lane → doc lane）"""

    subject: str
    topic_count: int
