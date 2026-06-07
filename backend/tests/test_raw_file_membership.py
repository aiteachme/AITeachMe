from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import RawFile, RetrievalChunk, Course, CourseFileLink, User
from app.repositories.files_repo import list_raw_files_by_ids
from app.repositories.knowledge import knowledge_repo
from app.workflows.digest.kg_doc_sync.lib.builds import _collect_graph_source_file_ids
from app.workflows.digest.planner.nodes import collect_planner_context


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Course.__table__,
            RawFile.__table__,
            CourseFileLink.__table__,
            RetrievalChunk.__table__,
        ],
    )
    return Session(engine, expire_on_commit=False)


def _add_user_courses(session: Session) -> None:
    session.add(User(id="user_a", username="user_a"))
    session.add(User(id="user_b", username="user_b"))
    session.add(Course(id="course_a", user_id="user_a", name="Course A"))
    session.add(Course(id="course_b", user_id="user_b", name="Course B"))
    session.commit()


def _raw_file(
    file_id: str,
    *,
    user_id: str,
    origin_course_id: str | None = None,
    filename: str | None = None,
) -> RawFile:
    return RawFile(
        id=file_id,
        user_id=user_id,
        origin_course_id=origin_course_id,
        filename=filename or f"{file_id}.pdf",
        filetype="pdf",
        file_path=f"files/{file_id}.pdf",
    )


def test_list_raw_files_by_ids_stays_inside_course_membership() -> None:
    with _session() as session:
        _add_user_courses(session)
        session.add(_raw_file("file_linked", user_id="user_a"))
        session.add(_raw_file("file_other_course", user_id="user_b", origin_course_id="course_b"))
        session.add(_raw_file("file_unlinked", user_id="user_a"))
        session.add(
            CourseFileLink(
                user_id="user_a",
                course_id="course_a",
                file_id="file_linked",
            )
        )
        session.commit()

        rows = list_raw_files_by_ids(
            session,
            "course_a",
            ["file_linked", "file_legacy", "file_other_course", "file_unlinked"],
        )

    assert {row.id for row in rows} == {"file_linked"}


def test_seed_material_context_keeps_string_file_ids(monkeypatch) -> None:
    with _session() as session:
        _add_user_courses(session)
        session.add(_raw_file("file_seed", user_id="user_a", origin_course_id="course_a", filename="seed.pdf"))
        session.add(CourseFileLink(user_id="user_a", course_id="course_a", file_id="file_seed"))
        session.commit()

        @contextmanager
        def fake_managed_session() -> Iterator[Session]:
            yield session

        monkeypatch.setattr(collect_planner_context, "managed_session", fake_managed_session)

        context = collect_planner_context._build_seed_material_context(
            course_id="course_a",
            file_ids=["file_seed"],
            user_prompt=None,
        )

    assert [item.file_id for item in context.source_documents] == ["file_seed"]


def test_delete_chunks_by_file_ids_keeps_other_course_chunks(monkeypatch) -> None:
    deleted_embedding_calls: list[tuple[str, list[int]]] = []

    def fake_delete_embeddings_by_chunk_ids(session: Session, *, course_id: str, chunk_ids: list[int]) -> None:
        del session
        deleted_embedding_calls.append((course_id, chunk_ids))

    monkeypatch.setattr(knowledge_repo, "delete_embeddings_by_chunk_ids", fake_delete_embeddings_by_chunk_ids)

    with _session() as session:
        _add_user_courses(session)
        session.add(_raw_file("file_shared", user_id="user_a", origin_course_id="course_a"))
        session.add(
            RetrievalChunk(
                course_id="course_a",
                file_id="file_shared",
                title="A",
                level=1,
                header_path="A",
                chunk_index=0,
                digest_chunk_uid="course_a:file_shared:0",
                content="A content",
            )
        )
        session.add(
            RetrievalChunk(
                course_id="course_b",
                file_id="file_shared",
                title="B",
                level=1,
                header_path="B",
                chunk_index=0,
                digest_chunk_uid="course_b:file_shared:0",
                content="B content",
            )
        )
        session.commit()

        deleted_count = knowledge_repo.delete_chunks_by_file_ids(
            session,
            course_id="course_a",
            file_ids=["file_shared"],
        )
        remaining = list(session.exec(select(RetrievalChunk)).all())

    assert deleted_count == 1
    assert [(chunk.course_id, chunk.file_id) for chunk in remaining] == [("course_b", "file_shared")]
    assert deleted_embedding_calls == [("course_a", [1])]


def test_graph_source_file_id_fallback_keeps_string_ids() -> None:
    assert _collect_graph_source_file_ids(
        {
            "chapters": [
                {"source_file_ids": ["file_alpha", "file_beta"]},
                {"source_file_ids": ["file_alpha", "", None, 42]},
            ]
        }
    ) == ["file_alpha", "file_beta", "42"]


def test_raw_file_origin_course_is_audit_data_not_membership_fk() -> None:
    course_foreign_key_columns = {
        fk.parent.name
        for fk in RawFile.__table__.foreign_keys
        if fk.column.table.name == "course"
    }

    assert "origin_course_id" not in course_foreign_key_columns
