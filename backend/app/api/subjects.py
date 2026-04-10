from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.subject import (
    SubjectCreateRequest,
    SubjectDeleteData,
    SubjectDeletePreviewData,
    SubjectDeletePreviewRequest,
    SubjectDeleteRequest,
    SubjectItem,
    SubjectListRequest,
    SubjectNameSuggestionRequest,
    SubjectNameSuggestionResponse,
    SubjectUpdateRequest,
)
from app.services.subject_service import (
    create_subject_record,
    delete_subject_record,
    list_subject_records,
    preview_subject_delete,
    update_subject_record,
)

router = APIRouter(prefix="/api/v1/subjects", tags=["subjects"])


@router.post(
    "/add",
    response_model=ApiResponse[SubjectItem],
    summary="创建学科",
    responses=build_error_responses([400, 409, 500]),
)
async def create_subject_api(
    body: SubjectCreateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(
        create_subject_record(
            session,
            owner_user_id=user.user_id,
            name=body.name,
        )
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[SubjectItem]],
    summary="学科列表",
    responses=build_error_responses([500]),
)
async def list_subjects_api(
    body: SubjectListRequest = Body(default=SubjectListRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[SubjectItem]]:
    return ok_response(
        list_subject_records(
            session,
            owner_user_id=user.user_id,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/delete/preview",
    response_model=ApiResponse[SubjectDeletePreviewData],
    summary="删除学科预览",
    responses=build_error_responses([400, 404, 500]),
)
async def preview_delete_subject_api(
    body: SubjectDeletePreviewRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectDeletePreviewData]:
    return ok_response(
        preview_subject_delete(
            session,
            owner_user_id=user.user_id,
            subject_id=body.subject_id,
        )
    )


@router.post(
    "/delete",
    response_model=ApiResponse[SubjectDeleteData],
    summary="删除学科",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def delete_subject_api(
    body: SubjectDeleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectDeleteData]:
    return ok_response(
        delete_subject_record(
            session,
            owner_user_id=user.user_id,
            subject_id=body.subject_id,
            force=body.force,
        )
    )


@router.post(
    "/update",
    response_model=ApiResponse[SubjectItem],
    summary="更新学科",
    responses=build_error_responses([400, 404, 500]),
)
async def update_subject_api(
    body: SubjectUpdateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SubjectItem]:
    return ok_response(
        update_subject_record(
            session,
            owner_user_id=user.user_id,
            subject_id=body.subject_id,
            name=body.name,
        )
    )


@router.post(
    "/suggest-name",
    response_model=ApiResponse[SubjectNameSuggestionResponse],
    summary="根据用户输入快速生成学科名称",
    responses=build_error_responses([400, 500]),
)
async def suggest_subject_name(
    body: SubjectNameSuggestionRequest = Body(...),
) -> ApiResponse[SubjectNameSuggestionResponse]:
    from app.shared.infra.llm_support.text import acompletion
    from app.schemas.llm import ChatMessage

    prompt_text = (body.prompt or "").strip()
    filenames = body.filenames or []

    # Build a minimal LLM prompt
    hints = []
    if prompt_text:
        hints.append(f"用户输入：{prompt_text}")
    if filenames:
        hints.append(f"文件名：{', '.join(filenames[:5])}")

    if not hints:
        return ok_response(SubjectNameSuggestionResponse(name="新学科"))

    messages: list[ChatMessage] = [
        {"role": "system", "content": (
            "你是一个学科名称生成器。根据用户输入的学习目标和文件名，生成一个简短的学科名称（2-8个字）。"
            "只输出名称，不要其他内容。例如：高等数学、Python编程、机器学习、电路分析、英语写作。"
        )},
        {"role": "user", "content": "\n".join(hints)},
    ]

    try:
        result = await acompletion(messages, max_tokens=30, temperature=0.3)
        name = result.strip().strip('"\'').strip()
        # Ensure reasonable length
        if not name or len(name) > 20:
            name = prompt_text[:20] if prompt_text else "新学科"
    except Exception:
        # Fallback: truncate prompt
        name = prompt_text[:20] if prompt_text else "新学科"

    return ok_response(SubjectNameSuggestionResponse(name=name))
