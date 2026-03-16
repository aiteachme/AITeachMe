"""Subject-scoped chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.repositories.chat_repo import list_messages_by_subject
from app.schemas.chat import ChatHistoryResponse, ChatListRequest, ChatSendRequest
from app.services.chat_service import chat_stream
from app.services.presenters import to_chat_history_response
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/chat", tags=["chat"])


@router.post(
    "/send",
    summary="Send a chat message",
    description="Run retrieval-augmented chat for a subject and stream the assistant response as SSE.",
    response_description="SSE event stream.",
    responses={200: {"description": "SSE event stream."}, **build_error_responses([400, 404, 500, 502, 503])},
)
async def send_chat(
    request: Request,
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ChatSendRequest = Body(...),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    generator = chat_stream(
        request,
        session,
        subject=normalized_subject,
        question=body.question,
        selected_context=body.selected_context,
        source_chunk_id=body.source_chunk_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post(
    "/list",
    response_model=ChatHistoryResponse,
    summary="List chat history",
    description="Return a paginated chat history list for one subject.",
    response_description="Paginated chat history.",
    responses=build_error_responses([400, 404, 500]),
)
async def list_chat(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ChatListRequest = Body(default=ChatListRequest()),
    session: Session = Depends(get_db),
) -> ChatHistoryResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    items, total = list_messages_by_subject(
        session,
        normalized_subject,
        limit=body.limit,
        offset=body.offset,
    )
    return to_chat_history_response(items, total)
