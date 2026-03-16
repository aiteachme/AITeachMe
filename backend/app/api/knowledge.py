"""Subject-scoped knowledge-set build and query routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.knowledge import (
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeGetRequest,
    KnowledgeGetResponse,
    KnowledgeListRequest,
    KnowledgeListResponse,
    KnowledgeStatusRequest,
    KnowledgeStatusResponse,
    KnowledgeTreeRequest,
    KnowledgeTreeResponse,
)
from app.services.knowledge_service import (
    create_knowledge_build,
    get_knowledge_documents,
    get_knowledge_status,
    get_knowledge_tree,
    list_knowledge_sets,
    run_knowledge_build_background,
)
from app.services.presenters import (
    to_knowledge_get_response,
    to_knowledge_list_response,
    to_knowledge_tree_response,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])


@router.post(
    "/build",
    response_model=KnowledgeBuildResponse,
    summary="Build a knowledge set",
    description="Create one knowledge set from multiple parsed source files and start the digest workflow in the background.",
    response_description="New knowledge build identifiers.",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def build_knowledge(
    background_tasks: BackgroundTasks,
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: KnowledgeBuildRequest = Body(...),
    session: Session = Depends(get_db),
) -> KnowledgeBuildResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    context = create_knowledge_build(
        session,
        subject=normalized_subject,
        file_ids=body.file_ids,
        title=body.title,
        description=body.desc,
    )
    background_tasks.add_task(
        run_knowledge_build_background,
        subject=normalized_subject,
        docset_id=context.docset_id,
        build_job_id=context.build_job_id,
    )
    return KnowledgeBuildResponse(docset_id=context.docset_id, build_job_id=context.build_job_id)


@router.post(
    "/status",
    response_model=KnowledgeStatusResponse,
    summary="Get knowledge build status",
    description="Return aggregated digest status for one knowledge set.",
    response_description="Knowledge build status.",
    responses=build_error_responses([400, 404, 500]),
)
async def get_knowledge_build_status(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: KnowledgeStatusRequest = Body(...),
    session: Session = Depends(get_db),
) -> KnowledgeStatusResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    doc_set, latest_job, docs_count, chunks_count = get_knowledge_status(
        session,
        subject=normalized_subject,
        docset_id=body.docset_id,
    )
    return KnowledgeStatusResponse(
        docset_id=body.docset_id,
        build_job_id=latest_job.id if latest_job is not None else None,
        stage=latest_job.stage if latest_job is not None else doc_set.build_status,
        progress=latest_job.progress if latest_job is not None else 0,
        message=latest_job.message if latest_job is not None else "No build job recorded.",
        docs_count=docs_count,
        chunks_count=chunks_count,
        error=latest_job.error if latest_job is not None else None,
    )


@router.post(
    "/list",
    response_model=KnowledgeListResponse,
    summary="List knowledge sets",
    description="Return a paginated knowledge-set list for one subject.",
    response_description="Paginated knowledge-set list.",
    responses=build_error_responses([400, 404, 500]),
)
async def list_knowledge(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: KnowledgeListRequest = Body(default=KnowledgeListRequest()),
    session: Session = Depends(get_db),
) -> KnowledgeListResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    items, total, counts = list_knowledge_sets(
        session,
        subject=normalized_subject,
        limit=body.limit,
        offset=body.offset,
    )
    return to_knowledge_list_response(items, total, counts)


@router.post(
    "/get",
    response_model=KnowledgeGetResponse,
    summary="Get knowledge-set detail",
    description="Return one knowledge set and its generated documents.",
    response_description="Knowledge-set detail.",
    responses=build_error_responses([400, 404, 500]),
)
async def get_knowledge(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: KnowledgeGetRequest = Body(...),
    session: Session = Depends(get_db),
) -> KnowledgeGetResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    doc_set, documents = get_knowledge_documents(
        session,
        subject=normalized_subject,
        docset_id=body.docset_id,
    )
    return to_knowledge_get_response(doc_set, documents)


@router.post(
    "/tree",
    response_model=KnowledgeTreeResponse,
    summary="Get knowledge outline trees",
    description="Return per-document outline trees for one knowledge set.",
    response_description="Knowledge trees.",
    responses=build_error_responses([400, 404, 500]),
)
async def get_knowledge_outline(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: KnowledgeTreeRequest = Body(...),
    session: Session = Depends(get_db),
) -> KnowledgeTreeResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    doc_set, trees = get_knowledge_tree(
        session,
        subject=normalized_subject,
        docset_id=body.docset_id,
    )
    return to_knowledge_tree_response(doc_set, trees)
