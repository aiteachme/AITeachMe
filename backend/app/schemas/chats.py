"""Chat API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import ChatRoleValue


class ChatContextItem(BaseModel):
    """One retrieval citation attached to an assistant message."""

    chunk_id: int = Field(description="Knowledge chunk ID.")
    file_id: str = Field(description="Raw file ID.")
    title: str = Field(description="Chunk title.")
    header_path: str = Field(description="Chunk header path.")
    score: float = Field(description="Retrieval score.")
    knowledge_unit_id: int | None = Field(default=None, description="Linked KnowledgeUnit ID.")
    knowledge_unit_name: str | None = Field(default=None, description="Linked KnowledgeUnit name.")
    knowledge_unit_type: str | None = Field(default=None, description="Linked KnowledgeUnit type.")
    relation_path: str | None = Field(default=None, description="KG path explanation used for retrieval.")
    evidence_quote: str | None = Field(default=None, description="Evidence quote used for text backtracking.")
    mastery_score: float | None = Field(default=None, description="Current user's mastery score for this KnowledgeUnit.")
    retrieval_source: str = Field(default="vector", description="Retrieval source: knowledge_unit or vector.")


class ChatSelectionContext(BaseModel):
    """Structured context captured around a doc text selection."""

    selected_text: str | None = Field(default=None, description="Exact selected text.")
    anchor_id: str | None = Field(default=None, description="Nearest doc heading anchor.")
    anchor_title: str | None = Field(default=None, description="Nearest doc heading title.")
    heading_path: list[str] = Field(default_factory=list, description="Heading path from document root to selection.")
    before_text: str | None = Field(default=None, description="Text window before the selection.")
    after_text: str | None = Field(default=None, description="Text window after the selection.")
    section_title: str | None = Field(default=None, description="Title of the section used for wider context.")
    section_excerpt: str | None = Field(default=None, description="Wider section excerpt around the selection.")
    section_truncated: bool = Field(default=False, description="Whether the wider section was truncated.")
    local_context_truncated: bool = Field(default=False, description="Whether the local before/after window was truncated.")


class ChatSendRequest(BaseModel):
    """Request body for sending one chat message."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "什么是条件概率？",
                "session_id": "dbe63613-08f6-4818-8317-cdf8d7a794a8",
                "source": "quick_chat",
                "anchor_id": "chapter-1",
                "selected_text": "条件概率表示在 B 已经发生的前提下 A 发生的概率。",
                "selection_context": {
                    "selected_text": "条件概率表示在 B 已经发生的前提下 A 发生的概率。",
                    "anchor_title": "条件概率",
                    "heading_path": ["概率基础", "条件概率"],
                    "before_text": "前面介绍了样本空间与事件。",
                    "after_text": "后面会用乘法公式继续推导。",
                    "section_title": "条件概率",
                    "section_excerpt": "条件概率用于描述在某个事件已经发生时另一个事件发生的可能性。",
                    "section_truncated": False,
                    "local_context_truncated": False,
                },
                "source_chunk_id": 12,
            }
        }
    )

    question: str = Field(description="Current user question.")
    session_id: str | None = Field(default=None, description="Optional session ID. Auto-created when omitted.")
    source: str | None = Field(default=None, description="Optional source tag, e.g. quick_chat, exam_question, or build_assistant.")
    model: str | None = Field(default=None, description="Optional per-message chat model. Omit or use settings for configured defaults.")
    anchor_id: str | None = Field(default=None, description="Optional doc heading or exam-question anchor for highlighted QA.")
    selected_text: str | None = Field(default=None, description="Exact highlighted text or question preview for display and persistence.")
    selected_context: str | None = Field(default=None, description="Legacy highlighted context string.")
    selection_context: ChatSelectionContext | None = Field(default=None, description="Structured doc-selection context for the prompt.")
    source_chunk_id: int | None = Field(default=None, description="Optional source chunk ID for the highlighted context.")
    attached_file_ids: list[str] = Field(default_factory=list, description="Optional user-library file IDs attached to this chat turn.")


class ChatListRequest(PageParams):
    """Pagination request for chat history."""

    session_id: str | None = Field(default=None, description="Optional session ID filter.")


class ChatClearRequest(BaseModel):
    """Request body for clearing chat history."""

    model_config = ConfigDict(json_schema_extra={"example": {"session_id": "optional-session-id"}})

    session_id: str | None = Field(default=None, description="Optional session ID to clear only one session.")


class ChatClearData(BaseModel):
    """Result payload for clearing chat history."""

    cleared: bool = Field(description="Whether the history was cleared.")
    deleted_count: int = Field(description="Deleted message count.", ge=0)


class ChatSessionListRequest(PageParams):
    """Pagination request for chat sessions."""

    include_all_courses: bool = Field(
        default=False,
        description="When true, list recent sessions across all courses owned by the user.",
    )


class ChatThreadListRequest(PageParams):
    """Pagination request for doc-selection chat turns."""

    source: str | None = Field(
        default="quick_chat",
        description="Optional source tag filter, defaults to doc quick chat.",
    )


class ChatSessionCreateRequest(BaseModel):
    """Request body for creating a chat session."""

    title: str | None = Field(default=None, description="Optional session title.")
    source: str | None = Field(default=None, description="Optional source tag.")


class ChatSessionDeleteRequest(BaseModel):
    """Request body for deleting one chat session."""

    session_id: str = Field(description="Target session ID.")


class ChatSessionItem(BaseModel):
    """One chat session item."""

    id: str = Field(description="Session ID.")
    title: str = Field(description="Session title.")
    course_id: str | None = Field(default=None, description="Course ID this session belongs to.")
    course_name: str | None = Field(default=None, description="Display name of the course this session belongs to.")
    source: str | None = Field(default=None, description="Session source.")
    anchor_id: str | None = Field(default=None, description="Doc heading or exam-question anchor for anchored sessions.")
    selected_text: str | None = Field(default=None, description="Selected text or question preview for anchored sessions.")
    source_chunk_id: int | None = Field(default=None, description="Optional source chunk ID for doc-selection sessions.")
    message_count: int = Field(description="Message count in this session.", ge=0)
    created_at: datetime = Field(description="Created time.")
    updated_at: datetime = Field(description="Updated time.")
    last_message_at: datetime = Field(description="Last message time.")


class ChatSessionCreateData(BaseModel):
    """Result payload for creating one session."""

    session: ChatSessionItem = Field(description="Created session.")


class ChatSessionDeleteData(BaseModel):
    """Result payload for deleting one session."""

    deleted: bool = Field(description="Whether session was deleted.")
    deleted_message_count: int = Field(description="Deleted message count.", ge=0)


class SSETokenEvent(BaseModel):
    """SSE token event payload."""

    content: str = Field(description="Incremental assistant text.")


class SSEDoneEvent(BaseModel):
    """SSE done event payload."""

    turn_id: str = Field(description="Persisted turn ID.")
    session_id: str = Field(description="Resolved session ID.")
    session_title: str | None = Field(default=None, description="Generated session title when available.")
    contexts: list[ChatContextItem] | None = Field(default=None, description="Retrieved citation list.")
    client_actions: list[dict] | None = Field(default=None, description="Optional client actions emitted by the assistant turn.")


class SSEErrorEvent(BaseModel):
    """SSE error event payload."""

    detail: str = Field(description="Error detail.")
    error_code: str = Field(description="Stable error code.")


class ChatMessageItem(BaseModel):
    """One persisted chat message."""

    id: int = Field(description="Message ID.")
    turn_id: str = Field(description="Conversation turn ID.")
    role: ChatRoleValue = Field(description="Message role.")
    content: str = Field(description="Message content.")
    contexts: list[ChatContextItem] | None = Field(default=None, description="Assistant citation list.")
    created_at: datetime = Field(description="Created time.")


class ChatThreadTurnItem(BaseModel):
    """One persisted turn with thread metadata for doc-selection QA."""

    turn_id: str = Field(description="Conversation turn ID.")
    session_id: str = Field(description="Resolved session ID.")
    source: str | None = Field(default=None, description="Source tag, e.g. quick_chat.")
    anchor_id: str | None = Field(default=None, description="Doc heading anchor.")
    selected_text: str | None = Field(default=None, description="Selected text for this turn.")
    source_chunk_id: int | None = Field(default=None, description="Optional source chunk ID.")
    created_at: datetime = Field(description="Turn bind time.")
    messages: list[ChatMessageItem] = Field(
        default_factory=list,
        description="Messages under this turn, sorted by time asc.",
    )
