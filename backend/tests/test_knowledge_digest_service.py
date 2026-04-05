from __future__ import annotations

from unittest.mock import patch

from sqlmodel import Session

from app.models import IngestStatus, RawFile, RetrievalChunk, Subject, TaskStatus
from app.schemas.knowledge import KnowledgeBuildPrecheckConflictData, SubjectVectorStatusResponse
from app.services.knowledge.digest_service import trigger_docgen_build


def _seed_subject(session: Session, *, subject_slug: str) -> Subject:
    subject = Subject(user_id="local", slug=subject_slug, name="测试学科")
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def _seed_ready_raw_file(session: Session, *, subject_slug: str, uid: str) -> RawFile:
    raw_file = RawFile(
        uid=uid,
        subject=subject_slug,
        filename=f"{uid}.md",
        filetype="md",
        file_path=f"/tmp/{uid}.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
        markdown_content=f"# {uid}\n\nsample content",
    )
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def test_trigger_docgen_build_force_full_rebuild_clears_chunk_vector_metadata(
    session: Session,
) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_rebuild")
    first_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_a")
    second_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_b")

    chunk = RetrievalChunk(
        subject=subject.slug,
        document_id=int(first_file.id or 0),
        title="sample",
        level=1,
        header_path="sample",
        chunk_index=0,
        digest_chunk_uid="chunk-subj-digest-rebuild",
        build_session_id="build-1",
        content="sample content",
        embedding_model="text-embedding-v3",
        vector_ref="chunk_embeddings",
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)

    conflict = KnowledgeBuildPrecheckConflictData(
        reason="legacy_vector_table",
        subject_model=None,
        subject_dim=None,
        runtime_model="text-embedding-v4",
        runtime_dim=1024,
        requires_full_rebuild=True,
        vector_enabled_after_continue=False,
    )
    vector_status = SubjectVectorStatusResponse(
        mode="enabled",
        embedding_model="text-embedding-v4",
        vector_table="chunk_embeddings_subj_digest_rebuild",
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=conflict,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=vector_status,
    ), patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ), patch(
        "app.services.knowledge.digest_service.clear_docgen_staging",
    ), patch(
        "app.services.knowledge.digest_service.update_knowledge_build_status",
    ):
        data, accepted_file_ids = trigger_docgen_build(
            session,
            subject=subject,
            file_uids=[first_file.uid],
            prompt="  review me  ",
            embedding_resolution=None,
        )

    session.refresh(chunk)

    assert accepted_file_ids == [int(first_file.id or 0), int(second_file.id or 0)]
    assert data.accepted_file_uids == [first_file.uid, second_file.uid]
    assert data.prompt == "review me"
    assert data.vector_status.mode == "enabled"
    assert chunk.embedding_model is None
    assert chunk.vector_ref is None


def test_trigger_docgen_build_calls_direct_clear_chunk_vector_metadata(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_direct_import")
    ready_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_direct")

    conflict = KnowledgeBuildPrecheckConflictData(
        reason="legacy_vector_table",
        subject_model=None,
        subject_dim=None,
        runtime_model="text-embedding-v4",
        runtime_dim=1024,
        requires_full_rebuild=True,
        vector_enabled_after_continue=False,
    )
    vector_status = SubjectVectorStatusResponse(
        mode="enabled",
        embedding_model="text-embedding-v4",
        vector_table="chunk_embeddings_subj_digest_direct_import",
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=conflict,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=vector_status,
    ), patch(
        "app.services.knowledge.digest_service.clear_chunk_vector_metadata",
    ) as clear_mock, patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ), patch(
        "app.services.knowledge.digest_service.clear_docgen_staging",
    ), patch(
        "app.services.knowledge.digest_service.update_knowledge_build_status",
    ):
        trigger_docgen_build(
            session,
            subject=subject,
            file_uids=[ready_file.uid],
            prompt=None,
            embedding_resolution=None,
        )

    clear_mock.assert_called_once_with(session, subject=subject.slug)
