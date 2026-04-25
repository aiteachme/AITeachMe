"""聊天接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.chats import (
    ChatClearData,
    ChatClearRequest,
    ChatListRequest,
    ChatMessageItem,
    ChatSendRequest,
    ChatThreadListRequest,
    ChatThreadTurnItem,
    ChatSessionCreateData,
    ChatSessionCreateRequest,
    ChatSessionDeleteData,
    ChatSessionDeleteRequest,
    ChatSessionItem,
    ChatSessionListRequest,
)
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.workflows.interact.chat import (
    chat_stream,
    clear_chat_history,
    create_session,
    delete_session,
    list_chat_history,
    list_chat_threads,
    list_chat_sessions,
)
from app.workflows.support.auth import set_guest_cookie_for_user
from app.workflows.support.subjects import get_subject_record
from app.utils.subject import GLOBAL_SUBJECT

router = APIRouter(prefix="/api/v1/subjects/{subject}/chats", tags=["chats"])
global_router = APIRouter(prefix="/api/v1/chats", tags=["chats"])


def _normalize_chat_subject(subject: str | None) -> str:
    return normalize_subject_slug(subject, allow_global=True)


def _prepare_chat_subject(
    session: Session,
    *,
    raw_subject: str | None,
    user_id: str,
) -> str:
    normalized_subject = _normalize_chat_subject(raw_subject)
    if normalized_subject != GLOBAL_SUBJECT:
        get_subject_record(session, normalized_subject, owner_user_id=user_id)
    return normalized_subject


async def _send_chat_response(
    request: Request,
    *,
    raw_subject: str | None,
    body: ChatSendRequest,
    user: CurrentUserContext,
    session: Session,
) -> StreamingResponse:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    stream_response = StreamingResponse(
        chat_stream(
            request,
            session,
            subject=normalized_subject,
            user_id=user.user_id,
            session_id=body.session_id,
            question=body.question,
            source=body.source,
            anchor_id=body.anchor_id,
            selected_text=body.selected_text,
            selected_context=body.selected_context,
            selection_context=body.selection_context,
            source_chunk_id=body.source_chunk_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    set_guest_cookie_for_user(stream_response, user_id=user.user_id)
    return stream_response


def _list_chat_response(
    *,
    raw_subject: str | None,
    body: ChatListRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[PaginatedData[ChatMessageItem]]:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    return ok_response(
        list_chat_history(
            session,
            subject=normalized_subject,
            user_id=user.user_id,
            page=body.page,
            size=body.size,
            session_id=body.session_id,
        )
    )


def _clear_chat_response(
    *,
    raw_subject: str | None,
    body: ChatClearRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[ChatClearData]:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    return ok_response(
        clear_chat_history(
            session,
            subject=normalized_subject,
            user_id=user.user_id,
            session_id=body.session_id,
        )
    )


def _list_chat_sessions_response(
    *,
    raw_subject: str | None,
    body: ChatSessionListRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[PaginatedData[ChatSessionItem]]:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    return ok_response(
        list_chat_sessions(
            session,
            subject=normalized_subject,
            user_id=user.user_id,
            page=body.page,
            size=body.size,
        )
    )


def _list_chat_threads_response(
    *,
    raw_subject: str | None,
    body: ChatThreadListRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[PaginatedData[ChatThreadTurnItem]]:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    return ok_response(
        list_chat_threads(
            session,
            subject=normalized_subject,
            user_id=user.user_id,
            page=body.page,
            size=body.size,
            source=body.source,
        )
    )


def _create_chat_session_response(
    *,
    raw_subject: str | None,
    body: ChatSessionCreateRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[ChatSessionCreateData]:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    created = create_session(
        session,
        subject=normalized_subject,
        user_id=user.user_id,
        title=body.title,
        source=body.source,
    )
    return ok_response(ChatSessionCreateData(session=created))


def _delete_chat_session_response(
    *,
    raw_subject: str | None,
    body: ChatSessionDeleteRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[ChatSessionDeleteData]:
    normalized_subject = _prepare_chat_subject(
        session,
        raw_subject=raw_subject,
        user_id=user.user_id,
    )
    return ok_response(
        delete_session(
            session,
            subject=normalized_subject,
            user_id=user.user_id,
            session_id=body.session_id,
        )
    )


@router.post(
    "/send",
    summary="发送消息",
    description="保留原生 SSE 返回。",
    responses={200: {"description": "SSE 事件流。"}, **build_error_responses([400, 404, 500, 502, 503])},
)
async def send_chat(
    request: Request,
    subject: str = Path(...),
    body: ChatSendRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    return await _send_chat_response(
        request,
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[ChatMessageItem]],
    summary="聊天记录列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_chat_api(
    subject: str = Path(...),
    body: ChatListRequest = Body(default=ChatListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatMessageItem]]:
    return _list_chat_response(
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@router.post(
    "/clear",
    response_model=ApiResponse[ChatClearData],
    summary="清空聊天记录",
    responses=build_error_responses([400, 404, 500]),
)
async def clear_chat_api(
    subject: str = Path(...),
    body: ChatClearRequest = Body(default=ChatClearRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatClearData]:
    return _clear_chat_response(
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@router.post(
    "/sessions/list",
    response_model=ApiResponse[PaginatedData[ChatSessionItem]],
    summary="会话列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_chat_sessions_api(
    subject: str = Path(...),
    body: ChatSessionListRequest = Body(default=ChatSessionListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatSessionItem]]:
    return _list_chat_sessions_response(
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@router.post(
    "/threads/list",
    response_model=ApiResponse[PaginatedData[ChatThreadTurnItem]],
    summary="划词问答轮次列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_chat_threads_api(
    subject: str = Path(...),
    body: ChatThreadListRequest = Body(default=ChatThreadListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatThreadTurnItem]]:
    return _list_chat_threads_response(
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@router.post(
    "/sessions/create",
    response_model=ApiResponse[ChatSessionCreateData],
    summary="创建会话",
    responses=build_error_responses([400, 404, 500]),
)
async def create_chat_session_api(
    subject: str = Path(...),
    body: ChatSessionCreateRequest = Body(default=ChatSessionCreateRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatSessionCreateData]:
    return _create_chat_session_response(
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@router.post(
    "/sessions/delete",
    response_model=ApiResponse[ChatSessionDeleteData],
    summary="删除会话",
    responses=build_error_responses([400, 404, 500]),
)
async def delete_chat_session_api(
    subject: str = Path(...),
    body: ChatSessionDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatSessionDeleteData]:
    return _delete_chat_session_response(
        raw_subject=subject,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/send",
    summary="Send global chat message",
    description="Returns native SSE.",
    responses={200: {"description": "SSE event stream."}, **build_error_responses([400, 500, 502, 503])},
)
async def send_global_chat(
    request: Request,
    body: ChatSendRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    return await _send_chat_response(
        request,
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[ChatMessageItem]],
    summary="List global chat history",
    responses=build_error_responses([400, 500]),
)
async def list_global_chat_api(
    body: ChatListRequest = Body(default=ChatListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatMessageItem]]:
    return _list_chat_response(
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/clear",
    response_model=ApiResponse[ChatClearData],
    summary="Clear global chat history",
    responses=build_error_responses([400, 500]),
)
async def clear_global_chat_api(
    body: ChatClearRequest = Body(default=ChatClearRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatClearData]:
    return _clear_chat_response(
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/sessions/list",
    response_model=ApiResponse[PaginatedData[ChatSessionItem]],
    summary="List global chat sessions",
    responses=build_error_responses([400, 500]),
)
async def list_global_chat_sessions_api(
    body: ChatSessionListRequest = Body(default=ChatSessionListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatSessionItem]]:
    return _list_chat_sessions_response(
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/threads/list",
    response_model=ApiResponse[PaginatedData[ChatThreadTurnItem]],
    summary="List global chat threads",
    responses=build_error_responses([400, 500]),
)
async def list_global_chat_threads_api(
    body: ChatThreadListRequest = Body(default=ChatThreadListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatThreadTurnItem]]:
    return _list_chat_threads_response(
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/sessions/create",
    response_model=ApiResponse[ChatSessionCreateData],
    summary="Create global chat session",
    responses=build_error_responses([400, 500]),
)
async def create_global_chat_session_api(
    body: ChatSessionCreateRequest = Body(default=ChatSessionCreateRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatSessionCreateData]:
    return _create_chat_session_response(
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )


@global_router.post(
    "/sessions/delete",
    response_model=ApiResponse[ChatSessionDeleteData],
    summary="Delete global chat session",
    responses=build_error_responses([400, 500]),
)
async def delete_global_chat_session_api(
    body: ChatSessionDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatSessionDeleteData]:
    return _delete_chat_session_response(
        raw_subject=GLOBAL_SUBJECT,
        body=body,
        user=user,
        session=session,
    )
