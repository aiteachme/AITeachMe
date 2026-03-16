"""Business logic for subject-scoped `knowledge/*` endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from app.agents.digest.workflow import run_digest_workflow
from app.core.database import get_session
from app.core.exceptions import DocSetNotFoundError, InvalidRawFileStateError
from app.repositories.ingest_repo import get_raw_file_by_id
from app.repositories.knowledge_repo import (
    bulk_create_doc_set_sources,
    bulk_create_documents,
    count_chunks_by_doc_set,
    count_documents_by_doc_set,
    create_doc_build_job,
    create_doc_set,
    get_doc_set_by_id,
    get_graph_nodes_by_document_id,
    get_latest_doc_build_job,
    list_documents_by_doc_set,
    list_doc_sets_by_subject,
    update_doc_build_job,
    update_doc_set_status,
)
from app.repositories.models import (
    DocBuildJob,
    DocSet,
    DocSetSourceFile,
    Document,
    DocumentOutlineNode,
    ParseStatus,
    PipelineStage,
)
from app.schemas.knowledge import OutlineNode
from app.services.file_service import get_subject_files_or_raise
from app.services.presenters import require_id


@dataclass(frozen=True)
class KnowledgeBuildContext:
    docset_id: int
    build_job_id: int


def _build_tree(nodes: list[DocumentOutlineNode]) -> list[OutlineNode]:
    node_map: dict[int, OutlineNode] = {}
    roots: list[OutlineNode] = []

    for node in nodes:
        node_id = require_id(node.id, "DocumentOutlineNode.id")
        node_map[node_id] = OutlineNode(
            id=node_id,
            title=node.title,
            level=node.level,
            children=[],
        )

    for node in nodes:
        node_id = require_id(node.id, "DocumentOutlineNode.id")
        current = node_map[node_id]
        if node.parent_id is not None and node.parent_id in node_map:
            node_map[node.parent_id].children.append(current)
        else:
            roots.append(current)

    return roots


def get_docset_or_raise(session: Session, *, subject: str, docset_id: int) -> DocSet:
    doc_set = get_doc_set_by_id(session, docset_id)
    if doc_set is None or doc_set.subject != subject:
        raise DocSetNotFoundError(docset_id)
    return doc_set


def create_knowledge_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    title: str,
    description: str,
) -> KnowledgeBuildContext:
    raw_files = get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
    for raw_file in raw_files:
        if raw_file.parse_status != ParseStatus.PARSED:
            raise InvalidRawFileStateError(
                require_id(raw_file.id, "RawFile.id"),
                raw_file.parse_status,
                ParseStatus.PARSED,
            )
        if not raw_file.markdown_path:
            raise InvalidRawFileStateError(
                require_id(raw_file.id, "RawFile.id"),
                raw_file.parse_status,
                "parsed markdown to exist",
            )

    doc_set = create_doc_set(
        session,
        DocSet(
            subject=subject,
            title=title.strip() or subject,
            description=description.strip(),
            build_status=PipelineStage.PENDING,
        ),
    )
    docset_id = require_id(doc_set.id, "DocSet.id")

    job = create_doc_build_job(
        session,
        DocBuildJob(
            doc_set_id=docset_id,
            stage=PipelineStage.PENDING,
            progress=0,
            message="Build queued.",
        ),
    )
    build_job_id = require_id(job.id, "DocBuildJob.id")

    bulk_create_doc_set_sources(
        session,
        [
            DocSetSourceFile(doc_set_id=docset_id, raw_file_id=require_id(raw_file.id, "RawFile.id"))
            for raw_file in raw_files
        ],
    )

    bulk_create_documents(
        session,
        [
            Document(
                doc_set_id=docset_id,
                subject=subject,
                source_file_id=require_id(raw_file.id, "RawFile.id"),
                title=raw_file.filename,
                pipeline_stage=PipelineStage.PENDING,
            )
            for raw_file in raw_files
        ],
    )

    return KnowledgeBuildContext(docset_id=docset_id, build_job_id=build_job_id)


async def run_knowledge_build_background(
    *,
    subject: str,
    docset_id: int,
    build_job_id: int,
) -> None:
    with get_session() as session:
        get_docset_or_raise(session, subject=subject, docset_id=docset_id)
        documents = [
            {
                "document_id": require_id(document.id, "Document.id"),
                "source_file_id": document.source_file_id,
                "title": document.title,
                "pipeline_stage": document.pipeline_stage,
            }
            for document in list_documents_by_doc_set(session, docset_id)
        ]
        update_doc_set_status(session, docset_id, build_status=PipelineStage.PENDING)
        update_doc_build_job(
            session,
            build_job_id,
            stage=PipelineStage.PENDING,
            progress=0,
            message=f"Preparing {len(documents)} source files.",
            error=None,
        )

    total = max(len(documents), 1)

    for index, document in enumerate(documents, start=1):
        document_id = document["document_id"]
        source_file_id = document["source_file_id"]

        with get_session() as session:
            raw_file = get_raw_file_by_id(session, source_file_id)
            if raw_file is None or raw_file.subject != subject or not raw_file.markdown_path:
                update_doc_set_status(session, docset_id, build_status=PipelineStage.FAILED)
                update_doc_build_job(
                    session,
                    build_job_id,
                    stage=PipelineStage.FAILED,
                    progress=int(((index - 1) / total) * 100),
                    message="Build failed before digest started.",
                    error=f"Missing parsed markdown for file {source_file_id}.",
                )
                return

            markdown_path = Path(raw_file.markdown_path)
            markdown_text = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
            update_doc_build_job(
                session,
                build_job_id,
                stage=document["pipeline_stage"],
                progress=int(((index - 1) / total) * 100),
                message=f"Building document {index}/{total}: {document['title']}",
                error=None,
            )

        result = await run_digest_workflow(
            document_id=document_id,
            subject=subject,
            raw_markdown=markdown_text,
            current_stage=PipelineStage.PENDING,
        )

        if result.get("error"):
            with get_session() as session:
                update_doc_set_status(session, docset_id, build_status=PipelineStage.FAILED)
                update_doc_build_job(
                    session,
                    build_job_id,
                    stage=PipelineStage.FAILED,
                    progress=int(index / total * 100),
                    message=f"Build failed on document {index}/{total}.",
                    error=result.get("error"),
                )
            return

        with get_session() as session:
            update_doc_set_status(session, docset_id, build_status=result["current_stage"])
            update_doc_build_job(
                session,
                build_job_id,
                stage=result["current_stage"],
                progress=int(index / total * 100),
                message=f"Built document {index}/{total}.",
                error=None,
            )

    with get_session() as session:
        update_doc_set_status(session, docset_id, build_status=PipelineStage.EMBEDDED)
        update_doc_build_job(
            session,
            build_job_id,
            stage=PipelineStage.EMBEDDED,
            progress=100,
            message="Build completed.",
            error=None,
        )


def get_knowledge_status(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> tuple[DocSet, DocBuildJob | None, int, int]:
    doc_set = get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    latest_job = get_latest_doc_build_job(session, docset_id)
    docs_count = count_documents_by_doc_set(session, docset_id)
    chunks_count = count_chunks_by_doc_set(session, docset_id)
    return doc_set, latest_job, docs_count, chunks_count


def list_knowledge_sets(
    session: Session,
    *,
    subject: str,
    limit: int,
    offset: int,
) -> tuple[list[DocSet], int, dict[int, int]]:
    items, total = list_doc_sets_by_subject(session, subject, limit=limit, offset=offset)
    counts = {
        require_id(item.id, "DocSet.id"): count_documents_by_doc_set(
            session, require_id(item.id, "DocSet.id")
        )
        for item in items
    }
    return items, total, counts


def get_knowledge_documents(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> tuple[DocSet, list[Document]]:
    doc_set = get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    documents = list_documents_by_doc_set(session, docset_id)
    return doc_set, documents


def get_knowledge_tree(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> tuple[DocSet, list[tuple[Document, list[OutlineNode]]]]:
    doc_set, documents = get_knowledge_documents(session, subject=subject, docset_id=docset_id)
    result: list[tuple[Document, list[OutlineNode]]] = []
    for document in documents:
        nodes = get_graph_nodes_by_document_id(session, require_id(document.id, "Document.id"))
        result.append((document, _build_tree(nodes)))
    return doc_set, result
