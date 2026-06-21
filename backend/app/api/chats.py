"""Chat API routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.api.sse import sse_headers
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
    list_recent_chat_sessions,
    list_chat_threads,
    list_chat_sessions,
)
from app.workflows.support.auth import set_guest_cookie_for_user
from app.workflows.support.courses import get_course_record
from app.shared.infra.database import managed_session
from app.utils.course import GLOBAL_COURSE

router = APIRouter(prefix="/api/v1/courses/{course_id}/chats", tags=["chats"])
global_router = APIRouter(prefix="/api/v1/chats", tags=["chats"])


def _normalize_chat_course_id(course_id: str | None) -> str:
    return normalize_course_id(course_id, allow_global=True)


def _prepare_chat_course_id(
    session: Session,
    *,
    raw_course_id: str | None,
    user_id: str,
) -> str:
    normalized_course_id = _normalize_chat_course_id(raw_course_id)
    if normalized_course_id != GLOBAL_COURSE:
        get_course_record(session, normalized_course_id, owner_user_id=user_id)
    return normalized_course_id


async def _send_chat_response(
    request: Request,
    response: Response,
    *,
    raw_course_id: str | None,
    body: ChatSendRequest,
) -> StreamingResponse:
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        normalized_course_id = _prepare_chat_course_id(
            session,
            raw_course_id=raw_course_id,
            user_id=user.user_id,
        )
    stream_response = StreamingResponse(
        chat_stream(
            request,
            None,
            course_id=normalized_course_id,
            user_id=user.user_id,
            session_id=body.session_id,
            question=body.question,
            scene=body.scene,
            source=body.source,
            model=body.model,
            anchor_id=body.anchor_id,
            selected_text=body.selected_text,
            selected_context=body.selected_context,
            selection_context=body.selection_context,
            source_chunk_id=body.source_chunk_id,
            attached_file_ids=body.attached_file_ids,
        ),
        media_type="text/event-stream",
        headers=sse_headers(),
    )
    set_guest_cookie_for_user(stream_response, user_id=user.user_id)
    return stream_response


def _list_chat_response(
    *,
    raw_course_id: str | None,
    body: ChatListRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[PaginatedData[ChatMessageItem]]:
    normalized_course_id = _prepare_chat_course_id(
        session,
        raw_course_id=raw_course_id,
        user_id=user.user_id,
    )
    return ok_response(
        list_chat_history(
            session,
            course_id=normalized_course_id,
            user_id=user.user_id,
            page=body.page,
            size=body.size,
            session_id=body.session_id,
        )
    )


def _clear_chat_response(
    *,
    raw_course_id: str | None,
    body: ChatClearRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[ChatClearData]:
    normalized_course_id = _prepare_chat_course_id(
        session,
        raw_course_id=raw_course_id,
        user_id=user.user_id,
    )
    return ok_response(
        clear_chat_history(
            session,
            course_id=normalized_course_id,
            user_id=user.user_id,
            session_id=body.session_id,
        )
    )


def _list_chat_sessions_response(
    *,
    raw_course_id: str | None,
    body: ChatSessionListRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[PaginatedData[ChatSessionItem]]:
    if body.include_all_courses:
        return ok_response(
            list_recent_chat_sessions(
                session,
                user_id=user.user_id,
                page=body.page,
                size=body.size,
                source=body.source,
            )
        )

    normalized_course_id = _prepare_chat_course_id(
        session,
        raw_course_id=raw_course_id,
        user_id=user.user_id,
    )
    return ok_response(
        list_chat_sessions(
            session,
            course_id=normalized_course_id,
            user_id=user.user_id,
            page=body.page,
            size=body.size,
            source=body.source,
        )
    )


def _list_chat_threads_response(
    *,
    raw_course_id: str | None,
    body: ChatThreadListRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[PaginatedData[ChatThreadTurnItem]]:
    normalized_course_id = _prepare_chat_course_id(
        session,
        raw_course_id=raw_course_id,
        user_id=user.user_id,
    )
    return ok_response(
        list_chat_threads(
            session,
            course_id=normalized_course_id,
            user_id=user.user_id,
            page=body.page,
            size=body.size,
            source=body.source,
        )
    )


def _create_chat_session_response(
    *,
    raw_course_id: str | None,
    body: ChatSessionCreateRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[ChatSessionCreateData]:
    normalized_course_id = _prepare_chat_course_id(
        session,
        raw_course_id=raw_course_id,
        user_id=user.user_id,
    )
    created = create_session(
        session,
        course_id=normalized_course_id,
        user_id=user.user_id,
        title=body.title,
        source=body.source,
    )
    return ok_response(ChatSessionCreateData(session=created))


def _delete_chat_session_response(
    *,
    raw_course_id: str | None,
    body: ChatSessionDeleteRequest,
    user: CurrentUserContext,
    session: Session,
) -> ApiResponse[ChatSessionDeleteData]:
    normalized_course_id = _prepare_chat_course_id(
        session,
        raw_course_id=raw_course_id,
        user_id=user.user_id,
    )
    return ok_response(
        delete_session(
            session,
            course_id=normalized_course_id,
            user_id=user.user_id,
            session_id=body.session_id,
        )
    )


@router.post(
    "/send",
    summary="Send course chat message",
    description="Returns native SSE.",
    responses={200: {"description": "SSE event stream."}, **build_error_responses([400, 404, 500, 502, 503])},
)
async def send_chat(
    request: Request,
    response: Response,
    course_id: str = Path(...),
    body: ChatSendRequest = Body(...),
) -> StreamingResponse:
    return await _send_chat_response(
        request,
        response,
        raw_course_id=course_id,
        body=body,
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[ChatMessageItem]],
    summary="聊天记录列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_chat_api(
    course_id: str = Path(...),
    body: ChatListRequest = Body(default=ChatListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatMessageItem]]:
    return _list_chat_response(
        raw_course_id=course_id,
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
    course_id: str = Path(...),
    body: ChatClearRequest = Body(default=ChatClearRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatClearData]:
    return _clear_chat_response(
        raw_course_id=course_id,
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
    course_id: str = Path(...),
    body: ChatSessionListRequest = Body(default=ChatSessionListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatSessionItem]]:
    return _list_chat_sessions_response(
        raw_course_id=course_id,
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
    course_id: str = Path(...),
    body: ChatThreadListRequest = Body(default=ChatThreadListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ChatThreadTurnItem]]:
    return _list_chat_threads_response(
        raw_course_id=course_id,
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
    course_id: str = Path(...),
    body: ChatSessionCreateRequest = Body(default=ChatSessionCreateRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatSessionCreateData]:
    return _create_chat_session_response(
        raw_course_id=course_id,
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
    course_id: str = Path(...),
    body: ChatSessionDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChatSessionDeleteData]:
    return _delete_chat_session_response(
        raw_course_id=course_id,
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
    response: Response,
    body: ChatSendRequest = Body(...),
) -> StreamingResponse:
    return await _send_chat_response(
        request,
        response,
        raw_course_id=GLOBAL_COURSE,
        body=body,
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
        raw_course_id=GLOBAL_COURSE,
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
        raw_course_id=GLOBAL_COURSE,
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
        raw_course_id=GLOBAL_COURSE,
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
        raw_course_id=GLOBAL_COURSE,
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
        raw_course_id=GLOBAL_COURSE,
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
        raw_course_id=GLOBAL_COURSE,
        body=body,
        user=user,
        session=session,
    )
