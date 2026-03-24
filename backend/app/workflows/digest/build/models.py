"""Coordination models for unified build."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterPrior(BaseModel):
    """单个章节的先验信息"""

    chapter_index: int
    title: str
    section_titles: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    chunk_uids: list[str] = Field(default_factory=list)


class ChapterPriors(BaseModel):
    """章节先验信息集合（doc lane → kg lane）"""

    chapters: list[ChapterPrior] = Field(default_factory=list)


class TopicAnchor(BaseModel):
    """主题锚点"""

    topic_name: str
    node_type: str = "Topic"
    confidence: float = 1.0
    chunk_uids: list[str] = Field(default_factory=list)


class TopicAnchorSnapshot(BaseModel):
    """主题锚点快照（kg lane → doc lane）"""

    anchors: list[TopicAnchor] = Field(default_factory=list)


class DocGap(BaseModel):
    """文档覆盖缺口（文档讲了，图谱没有）"""

    chapter_index: int
    chapter_title: str
    missing_terms: list[str] = Field(default_factory=list)
    severity: float = 0.0  # 0-1


class GraphGap(BaseModel):
    """图谱覆盖缺口（图谱有了，文档没讲）"""

    node_id: int
    node_name: str
    node_type: str
    chunk_uids: list[str] = Field(default_factory=list)
    no_chapter_coverage: bool = False


class OrphanSignal(BaseModel):
    """孤儿信号（例子/定义很多，但概念薄弱）"""

    chapter_index: int
    chapter_title: str
    orphan_type: str  # "example" | "definition"
    orphan_count: int


class TaxonomyDrift(BaseModel):
    """分类漂移（文档和图谱命名分裂）"""

    chunk_uids: list[str] = Field(default_factory=list)
    doc_name: str
    graph_name: str
    semantic_distance: float = 0.0


class CoverageReport(BaseModel):
    """覆盖缺口报告"""

    doc_over_graph_gaps: list[DocGap] = Field(default_factory=list)
    graph_over_doc_gaps: list[GraphGap] = Field(default_factory=list)
    orphan_signals: list[OrphanSignal] = Field(default_factory=list)
    taxonomy_drifts: list[TaxonomyDrift] = Field(default_factory=list)

    def has_gaps(self) -> bool:
        """是否有缺口"""
        return bool(
            self.doc_over_graph_gaps
            or self.graph_over_doc_gaps
            or self.orphan_signals
            or self.taxonomy_drifts
        )

    def gap_count(self) -> int:
        """缺口总数"""
        return (
            len(self.doc_over_graph_gaps)
            + len(self.graph_over_doc_gaps)
            + len(self.orphan_signals)
            + len(self.taxonomy_drifts)
        )
