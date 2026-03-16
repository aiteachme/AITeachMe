"""知识集合服务层。"""

from __future__ import annotations

from pathlib import Path

import structlog
from sqlmodel import Session

from app.agents.digest.chunker import chunk_markdown
from app.agents.digest.cleaner import clean_markdown
from app.agents.digest.embedder import embed_chunks
from app.agents.digest.outliner import OutlineItem, extract_outline
from app.core.database import get_session
from app.core.exceptions import DocSetNotFoundError, InvalidRawFileStateError, KnowledgeRetryNotAllowedError
from app.models import (
    DigestStep,
    DocBuildJob,
    DocSet,
    DocSetSourceFile,
    Document,
    DocumentChunk,
    DocumentOutlineNode,
    TaskStatus,
)
from app.repositories.ingest_repo import get_raw_file_by_id
from app.repositories.knowledge_repo import (
    bulk_create_chunks,
    bulk_create_doc_set_sources,
    bulk_create_documents,
    bulk_insert_embeddings,
    clear_doc_set_generated_data,
    count_chunks_by_doc_set,
    count_documents_by_doc_set,
    create_graph_node,
    create_doc_build_job,
    create_doc_set,
    delete_doc_set_cascade,
    get_doc_set_by_id,
    get_graph_nodes_by_document_id,
    get_latest_doc_build_job,
    list_doc_set_source_files,
    list_doc_sets_by_subject,
    list_documents_by_doc_set,
    update_doc_build_job,
    update_document_content,
    update_document_step,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.knowledge import (
    DocSetItem,
    DocumentItem,
    DocumentTreeItem,
    KnowledgeBuildData,
    KnowledgeDeleteData,
    KnowledgeGetData,
    KnowledgeStatusData,
    KnowledgeTreeData,
    OutlineNode,
)
from app.services.file_service import get_subject_files_or_raise
from app.services.presenters import require_id

logger = structlog.get_logger()


def _persist_outline_nodes(
    session: Session,
    *,
    document_id: int,
    items: list[OutlineItem],
    parent_id: int | None = None,
    order_ref: list[int] | None = None,
) -> None:
    """递归写入大纲节点。"""

    current_order_ref = order_ref or [0]
    for item in items:
        node = create_graph_node(
            session,
            DocumentOutlineNode(
                document_id=document_id,
                parent_id=parent_id,
                title=item.title,
                level=item.level,
                order_index=current_order_ref[0],
            ),
        )
        current_order_ref[0] += 1
        _persist_outline_nodes(
            session,
            document_id=document_id,
            items=item.children,
            parent_id=require_id(node.id, "DocumentOutlineNode.id"),
            order_ref=current_order_ref,
        )


def _build_tree(nodes: list[DocumentOutlineNode]) -> list[OutlineNode]:
    node_map: dict[int, OutlineNode] = {}
    roots: list[OutlineNode] = []

    for node in nodes:
        node_id = require_id(node.id, "DocumentOutlineNode.id")
        node_map[node_id] = OutlineNode(id=node_id, title=node.title, level=node.level, children=[])

    for node in nodes:
        node_id = require_id(node.id, "DocumentOutlineNode.id")
        current = node_map[node_id]
        if node.parent_id is not None and node.parent_id in node_map:
            node_map[node.parent_id].children.append(current)
        else:
            roots.append(current)
    return roots


def get_docset_or_raise(session: Session, *, subject: str, docset_id: int) -> DocSet:
    """按学科读取知识集合。"""

    doc_set = get_doc_set_by_id(session, docset_id)
    if doc_set is None or doc_set.subject != subject:
        raise DocSetNotFoundError(docset_id)
    return doc_set


def request_knowledge_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    title: str,
    description: str,
) -> KnowledgeBuildData:
    """受理知识构建请求。"""

    raw_files = get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
    for raw_file in raw_files:
        raw_file_id = require_id(raw_file.id, "RawFile.id")
        if raw_file.status != TaskStatus.COMPLETED.value:
            raise InvalidRawFileStateError(raw_file_id, raw_file.status, TaskStatus.COMPLETED.value)
        if not raw_file.markdown_path:
            raise InvalidRawFileStateError(raw_file_id, raw_file.status, "markdown_ready")

    doc_set = create_doc_set(
        session,
        DocSet(
            subject=subject,
            title=title.strip() or subject,
            description=description.strip(),
        ),
    )
    docset_id = require_id(doc_set.id, "DocSet.id")
    job = create_doc_build_job(
        session,
        DocBuildJob(
            doc_set_id=docset_id,
            status=TaskStatus.PROCESSING.value,
            progress=0,
            current_step=None,
            message="知识构建已排队。",
            error_message=None,
        ),
    )
    bulk_create_doc_set_sources(
        session,
        [
            DocSetSourceFile(doc_set_id=docset_id, raw_file_id=require_id(item.id, "RawFile.id"))
            for item in raw_files
        ],
    )
    bulk_create_documents(
        session,
        [
            Document(
                doc_set_id=docset_id,
                subject=subject,
                source_file_id=require_id(item.id, "RawFile.id"),
                title=item.filename,
                markdown_content="",
                current_step=None,
            )
            for item in raw_files
        ],
    )
    return KnowledgeBuildData(docset_id=docset_id, build_job_id=require_id(job.id, "DocBuildJob.id"))


def retry_knowledge_build(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> KnowledgeBuildData:
    """重试失败的知识构建。"""

    doc_set = get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    latest_job = get_latest_doc_build_job(session, docset_id)
    if latest_job is None or latest_job.status != TaskStatus.FAILED.value:
        raise KnowledgeRetryNotAllowedError(docset_id, latest_job.status if latest_job else "missing")

    source_links = list_doc_set_source_files(session, docset_id)
    raw_files = []
    for link in source_links:
        raw_file = get_raw_file_by_id(session, link.raw_file_id)
        if raw_file is None or raw_file.subject != subject:
            raise InvalidRawFileStateError(link.raw_file_id, "missing", TaskStatus.COMPLETED.value)
        if raw_file.status != TaskStatus.COMPLETED.value or not raw_file.markdown_path:
            raise InvalidRawFileStateError(link.raw_file_id, raw_file.status, TaskStatus.COMPLETED.value)
        raw_files.append(raw_file)

    clear_doc_set_generated_data(session, docset_id)
    bulk_create_documents(
        session,
        [
            Document(
                doc_set_id=docset_id,
                subject=subject,
                source_file_id=require_id(item.id, "RawFile.id"),
                title=item.filename,
                markdown_content="",
                current_step=None,
            )
            for item in raw_files
        ],
    )
    job = create_doc_build_job(
        session,
        DocBuildJob(
            doc_set_id=docset_id,
            status=TaskStatus.PROCESSING.value,
            progress=0,
            current_step=None,
            message="知识构建重试已排队。",
            error_message=None,
        ),
    )
    return KnowledgeBuildData(docset_id=docset_id, build_job_id=require_id(job.id, "DocBuildJob.id"))


async def run_knowledge_build_background(
    *,
    subject: str,
    docset_id: int,
    build_job_id: int,
) -> None:
    """后台执行知识构建。"""

    with get_session() as session:
        get_docset_or_raise(session, subject=subject, docset_id=docset_id)
        documents = list_documents_by_doc_set(session, docset_id)

    total_steps = max(len(documents) * 5, 1)
    completed_steps = 0

    for document in documents:
        document_id = require_id(document.id, "Document.id")
        raw_file = None
        with get_session() as session:
            raw_file = get_raw_file_by_id(session, document.source_file_id)
            if raw_file is None or raw_file.subject != subject or not raw_file.markdown_path:
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.FAILED.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=None,
                    message="构建失败。",
                    error_message=f"缺少源文件 {document.source_file_id} 的 Markdown。",
                )
                return

        try:
            raw_markdown = Path(raw_file.markdown_path).read_text(encoding="utf-8")
            cleaned_markdown = clean_markdown(raw_markdown)
            with get_session() as session:
                update_document_step(session, document_id, DigestStep.CLEANED.value)
                completed_steps += 1
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.PROCESSING.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=DigestStep.CLEANED.value,
                    message=f"已清洗文档 {document.title}",
                    error_message=None,
                )

            outline_items = await extract_outline(cleaned_markdown)
            with get_session() as session:
                _persist_outline_nodes(session, document_id=document_id, items=outline_items)
                update_document_step(session, document_id, DigestStep.OUTLINED.value)
                completed_steps += 1
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.PROCESSING.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=DigestStep.OUTLINED.value,
                    message=f"已提取文档 {document.title} 大纲",
                    error_message=None,
                )

            with get_session() as session:
                update_document_content(session, document_id, cleaned_markdown)
                update_document_step(session, document_id, DigestStep.STORED.value)
                completed_steps += 1
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.PROCESSING.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=DigestStep.STORED.value,
                    message=f"已写入文档 {document.title} 内容",
                    error_message=None,
                )

            chunks = chunk_markdown(cleaned_markdown)
            with get_session() as session:
                update_document_step(session, document_id, DigestStep.CHUNKED.value)
                completed_steps += 1
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.PROCESSING.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=DigestStep.CHUNKED.value,
                    message=f"已切分文档 {document.title}",
                    error_message=None,
                )

            embeddings = await embed_chunks(chunks)
            db_chunks = [
                DocumentChunk(
                    document_id=document_id,
                    title=chunk.title,
                    level=chunk.level,
                    header_path=chunk.header_path,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                )
                for chunk in chunks
            ]
            with get_session() as session:
                db_chunks = bulk_create_chunks(session, db_chunks)
                bulk_insert_embeddings(
                    session,
                    [require_id(chunk.id, "DocumentChunk.id") for chunk in db_chunks],
                    embeddings,
                )
                update_document_step(session, document_id, DigestStep.EMBEDDED.value)
                completed_steps += 1
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.PROCESSING.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=DigestStep.EMBEDDED.value,
                    message=f"已完成文档 {document.title} 向量化",
                    error_message=None,
                )
        except Exception as exc:
            logger.error("knowledge_build_failed", docset_id=docset_id, document_id=document_id, error=str(exc))
            with get_session() as session:
                update_doc_build_job(
                    session,
                    build_job_id,
                    status=TaskStatus.FAILED.value,
                    progress=int(completed_steps / total_steps * 100),
                    current_step=None,
                    message="知识构建失败。",
                    error_message=str(exc),
                )
            return

    with get_session() as session:
        update_doc_build_job(
            session,
            build_job_id,
            status=TaskStatus.COMPLETED.value,
            progress=100,
            current_step=DigestStep.EMBEDDED.value,
            message="知识构建完成。",
            error_message=None,
        )


def get_knowledge_status(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> KnowledgeStatusData:
    """读取知识构建状态。"""

    get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    latest_job = get_latest_doc_build_job(session, docset_id)
    return KnowledgeStatusData(
        docset_id=docset_id,
        build_job_id=require_id(latest_job.id, "DocBuildJob.id") if latest_job and latest_job.id is not None else None,
        status=latest_job.status if latest_job else TaskStatus.PENDING.value,
        current_step=latest_job.current_step,
        progress=latest_job.progress if latest_job else 0,
        message=latest_job.message if latest_job else "尚未发起构建。",
        docs_count=count_documents_by_doc_set(session, docset_id),
        chunks_count=count_chunks_by_doc_set(session, docset_id),
        error_message=latest_job.error_message if latest_job else None,
    )


def list_knowledge_sets(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[DocSetItem]:
    """分页读取知识集合列表。"""

    items, total = list_doc_sets_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    data_items: list[DocSetItem] = []
    for item in items:
        latest_job = get_latest_doc_build_job(session, require_id(item.id, "DocSet.id"))
        data_items.append(
            DocSetItem(
                id=require_id(item.id, "DocSet.id"),
                title=item.title,
                description=item.description,
                status=latest_job.status if latest_job else None,
                documents_count=count_documents_by_doc_set(session, require_id(item.id, "DocSet.id")),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
    return build_paginated_data(items=data_items, page=page, size=size, total=total)


def get_knowledge_detail(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> KnowledgeGetData:
    """读取知识集合详情。"""

    doc_set = get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    latest_job = get_latest_doc_build_job(session, docset_id)
    documents = list_documents_by_doc_set(session, docset_id)
    return KnowledgeGetData(
        docset_id=docset_id,
        title=doc_set.title,
        description=doc_set.description,
        status=latest_job.status if latest_job else None,
        documents=[
            DocumentItem(
                id=require_id(document.id, "Document.id"),
                source_file_id=document.source_file_id,
                title=document.title,
                markdown_content=document.markdown_content,
                current_step=document.current_step,
            )
            for document in documents
        ],
    )


def get_knowledge_tree(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> KnowledgeTreeData:
    """读取知识大纲树。"""

    doc_set = get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    documents = list_documents_by_doc_set(session, docset_id)
    tree_items: list[DocumentTreeItem] = []
    for document in documents:
        nodes = get_graph_nodes_by_document_id(session, require_id(document.id, "Document.id"))
        tree_items.append(
            DocumentTreeItem(
                document_id=require_id(document.id, "Document.id"),
                title=document.title,
                nodes=_build_tree(nodes),
            )
        )
    return KnowledgeTreeData(docset_id=docset_id, title=doc_set.title, documents=tree_items)


def delete_knowledge(
    session: Session,
    *,
    subject: str,
    docset_id: int,
) -> KnowledgeDeleteData:
    """删除知识集合。"""

    get_docset_or_raise(session, subject=subject, docset_id=docset_id)
    delete_doc_set_cascade(session, docset_id)
    return KnowledgeDeleteData(deleted=True, docset_id=docset_id)
