from __future__ import annotations

from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.shared.infra.subject import (
    RuntimeEmbeddingConfig,
    build_subject_vector_status,
    get_legacy_vector_table_name,
    get_subject_embedding_binding,
    inspect_subject_build_precheck,
    resolve_subject_build_vector_status,
)
from app.models import RawFile, RetrievalChunk, Subject, User


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, connection_record) -> None:
        del connection_record
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _seed_subject(session: Session, *, subject_slug: str) -> Subject:
    session.add(User(id="local", username="local"))
    session.commit()

    subject = Subject(user_id="local", slug=subject_slug, name="测试学科")
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def _seed_chunk(session: Session, *, subject_slug: str, vector_ref: str | None) -> RetrievalChunk:
    raw_file = RawFile(
        uid=f"raw-{subject_slug}",
        subject=subject_slug,
        filename="sample.md",
        filetype="md",
        file_path=f"/tmp/{subject_slug}.md",
        status="completed",
        ingest_status="completed",
        markdown_content="# sample",
    )
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)

    chunk = RetrievalChunk(
        subject=subject_slug,
        document_id=raw_file.id or 0,
        title="sample",
        level=1,
        header_path="sample",
        chunk_index=0,
        digest_chunk_uid=f"chunk-{subject_slug}",
        build_session_id="build-1",
        content="sample content",
        vector_ref=vector_ref,
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    return chunk


def test_inspect_subject_build_precheck_returns_legacy_conflict() -> None:
    session = _make_session()
    subject = _seed_subject(session, subject_slug="subj_embed_legacy")
    _seed_chunk(
        session,
        subject_slug=subject.slug,
        vector_ref=get_legacy_vector_table_name(),
    )

    runtime = RuntimeEmbeddingConfig(
        configured=True,
        available=True,
        embedding_model="text-embedding-v4",
        embedding_dim=1024,
    )

    with patch(
        "app.shared.infra.subject.build_precheck.get_runtime_embedding_config",
        return_value=runtime,
    ), patch(
        "app.shared.infra.subject.build_precheck.vector_table_exists",
        return_value=True,
    ):
        conflict = inspect_subject_build_precheck(session, subject=subject)

    assert conflict is not None
    assert conflict.reason == "legacy_vector_table"
    assert conflict.runtime_model == "text-embedding-v4"
    assert conflict.runtime_dim == 1024
    assert conflict.requires_full_rebuild is True


def test_build_subject_vector_status_hides_notice_for_unbound_ready_runtime() -> None:
    runtime = RuntimeEmbeddingConfig(
        configured=True,
        available=True,
        embedding_model="text-embedding-v4",
        embedding_dim=1024,
    )

    status = build_subject_vector_status(None, runtime=runtime)

    assert status.mode == "enabled"
    assert status.notice is None


def test_runtime_embedding_config_reports_missing_cloud_llamaindex_dependency() -> None:
    from app.shared.infra.subject.vectors import get_runtime_embedding_config

    def fake_get_env(name: str, default: str | None = None) -> str | None:
        if name == "LLM_API_KEY":
            return "test-key"
        return default

    with patch("app.shared.infra.subject.vectors.is_cloud_mode", return_value=True), patch(
        "app.shared.infra.subject.vectors.get_env",
        side_effect=fake_get_env,
    ), patch(
        "importlib.util.find_spec",
        side_effect=ModuleNotFoundError("llama_index.vector_stores"),
    ):
        runtime = get_runtime_embedding_config()

    assert runtime.available is False
    assert runtime.reason == "llamaindex_postgres_unavailable"


def test_resolve_subject_build_vector_status_disable_marks_subject_disabled() -> None:
    session = _make_session()
    subject = _seed_subject(session, subject_slug="subj_embed_disable")

    runtime = RuntimeEmbeddingConfig(
        configured=True,
        available=True,
        embedding_model="text-embedding-v4",
        embedding_dim=1024,
    )

    with patch(
        "app.shared.infra.subject.build_precheck.get_runtime_embedding_config",
        return_value=runtime,
    ):
        status = resolve_subject_build_vector_status(
            session,
            subject=subject,
            embedding_resolution="disable",
        )

    binding = get_subject_embedding_binding(subject)
    assert binding is not None
    assert binding.mode.value == "disabled"
    assert status.mode == "disabled"
    assert status.notice is not None


def test_resolve_subject_build_vector_status_rebuild_rebinds_subject() -> None:
    session = _make_session()
    subject = _seed_subject(session, subject_slug="subj_embed_rebuild")

    runtime = RuntimeEmbeddingConfig(
        configured=True,
        available=True,
        embedding_model="text-embedding-v4",
        embedding_dim=1024,
    )

    with patch(
        "app.shared.infra.subject.build_precheck.get_runtime_embedding_config",
        return_value=runtime,
    ), patch(
        "app.shared.infra.search.llamaindex_index.clear_subject_index",
    ) as clear_mock:
        status = resolve_subject_build_vector_status(
            session,
            subject=subject,
            embedding_resolution="rebuild",
        )

    binding = get_subject_embedding_binding(subject)
    assert binding is not None
    assert binding.mode.value == "enabled"
    assert binding.embedding_model == "text-embedding-v4"
    assert binding.embedding_dim == 1024
    assert binding.vector_table == "llamaindex://local/subj_embed_rebuild/rag_index"
    assert status.mode == "enabled"
    assert status.embedding_model == "text-embedding-v4"
    clear_mock.assert_called_once_with(subject.slug)
