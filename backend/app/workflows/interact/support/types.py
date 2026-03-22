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
    """One retrieved chunk formatted for prompting and citations."""

    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    low_relevance: bool

    def to_context_item(self) -> ChatContextItem:
        """Convert the retrieval record into the stored chat citation payload."""

        return ChatContextItem(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            title=self.title,
            header_path=self.header_path,
            score=round(self.score, 4),
        )
