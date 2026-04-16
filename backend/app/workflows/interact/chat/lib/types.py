"""Structured data models used by the interact workflow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.chats import ChatContextItem


class RecentMessage(BaseModel):
    """One recent persisted chat message."""

    role: Literal["user", "assistant"]
    content: str


class WeakPointSummary(BaseModel):
    """One weak-point summary used for tutoring."""

    knowledge_point: str
    mastery_text: str


class MistakeSummary(BaseModel):
    """One recent mistake summary used for tutoring."""

    question_stem: str
    user_answer: str
    correct_answer: str
    analysis: str


class RetrievedContext(BaseModel):
    """One retrieved KnowledgeUnit-backed context formatted for prompting and citations."""

    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    low_relevance: bool
    knowledge_unit_id: int | None = None
    knowledge_unit_name: str | None = None
    knowledge_unit_type: str | None = None
    relation_path: str | None = None
    evidence_quote: str | None = None
    mastery_score: float | None = None
    retrieval_source: str = "vector"

    def to_context_item(self) -> ChatContextItem:
        """Convert the retrieval record into the stored chat citation payload."""

        return ChatContextItem(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            title=self.title,
            header_path=self.header_path,
            score=round(self.score, 4),
            knowledge_unit_id=self.knowledge_unit_id,
            knowledge_unit_name=self.knowledge_unit_name,
            knowledge_unit_type=self.knowledge_unit_type,
            relation_path=self.relation_path,
            evidence_quote=self.evidence_quote,
            mastery_score=None if self.mastery_score is None else round(self.mastery_score, 4),
            retrieval_source=self.retrieval_source,
        )
