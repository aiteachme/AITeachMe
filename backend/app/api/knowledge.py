"""知识集合接口。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.knowledge import (
    DocSetItem,
    KnowledgeBuildData,
    KnowledgeBuildRequest,
    KnowledgeDeleteData,
    KnowledgeDeleteRequest,
    KnowledgeGetData,
    KnowledgeGetRequest,
    KnowledgeListRequest,
    KnowledgeRetryRequest,
    KnowledgeStatusData,
    KnowledgeStatusRequest,
    KnowledgeTreeData,
    KnowledgeTreeRequest,
)
from app.services.knowledge_service import (
    delete_knowledge,
    get_knowledge_detail,
    get_knowledge_status,
    get_knowledge_tree,
    list_knowledge_sets,
    request_knowledge_build,
    retry_knowledge_build,
    run_knowledge_build_background,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])


@router.post(
    "/build",
    response_model=ApiResponse[KnowledgeBuildData],
    summary="构建知识集合",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def build_knowledge(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: KnowledgeBuildRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeBuildData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    data = request_knowledge_build(
        session,
        subject=normalized_subject,
        file_ids=body.file_ids,
        title=body.title,
        description=body.desc,
    )
    background_tasks.add_task(
        run_knowledge_build_background,
        subject=normalized_subject,
        docset_id=data.docset_id,
        build_job_id=data.build_job_id,
    )
    return ok_response(data)


@router.post(
    "/retry",
    response_model=ApiResponse[KnowledgeBuildData],
    summary="重试知识构建",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def retry_knowledge_api(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: KnowledgeRetryRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeBuildData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    data = retry_knowledge_build(
        session,
        subject=normalized_subject,
        docset_id=body.docset_id,
    )
    background_tasks.add_task(
        run_knowledge_build_background,
        subject=normalized_subject,
        docset_id=data.docset_id,
        build_job_id=data.build_job_id,
    )
    return ok_response(data)


@router.post(
    "/status",
    response_model=ApiResponse[KnowledgeStatusData],
    summary="知识构建状态",
    responses=build_error_responses([400, 404, 500]),
)
async def get_knowledge_status_api(
    subject: str = Path(...),
    body: KnowledgeStatusRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeStatusData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        get_knowledge_status(session, subject=normalized_subject, docset_id=body.docset_id)
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[DocSetItem]],
    summary="知识集合列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_knowledge_api(
    subject: str = Path(...),
    body: KnowledgeListRequest = Body(default=KnowledgeListRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[DocSetItem]]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        list_knowledge_sets(
            session,
            subject=normalized_subject,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/get",
    response_model=ApiResponse[KnowledgeGetData],
    summary="知识集合详情",
    responses=build_error_responses([400, 404, 500]),
)
async def get_knowledge_api(
    subject: str = Path(...),
    body: KnowledgeGetRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeGetData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        get_knowledge_detail(session, subject=normalized_subject, docset_id=body.docset_id)
    )


@router.post(
    "/tree",
    response_model=ApiResponse[KnowledgeTreeData],
    summary="知识大纲树",
    responses=build_error_responses([400, 404, 500]),
)
async def get_knowledge_tree_api(
    subject: str = Path(...),
    body: KnowledgeTreeRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeTreeData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        get_knowledge_tree(session, subject=normalized_subject, docset_id=body.docset_id)
    )


@router.post(
    "/delete",
    response_model=ApiResponse[KnowledgeDeleteData],
    summary="删除知识集合",
    responses=build_error_responses([400, 404, 500]),
)
async def delete_knowledge_api(
    subject: str = Path(...),
    body: KnowledgeDeleteRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDeleteData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        delete_knowledge(session, subject=normalized_subject, docset_id=body.docset_id)
    )
