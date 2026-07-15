from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
from app.models import (
    ChatMessage,
    ChatSession,
    Course,
    CourseFileLink,
    KnowledgeEdge,
    KnowledgeDocument,
    KnowledgeUnit,
    RawFile,
    RetrievalChunk,
)
from app.schemas.export_import import ExportOptions, ImportOptions
from app.shared.infra.exceptions import InvalidImportPackageError
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib import build_lifecycle as docgen_build_lifecycle
from app.workflows.support.export_import import exports as export_module
from app.workflows.support.export_import import imports as import_module


COURSE_ID = "course_math00000000"
IMPORTED_COURSE_ID = "course_imported1234"
EMPTY_DOCS_COURSE_ID = "course_emptydocs000"
LEGACY_DOCS_COURSE_ID = "course_legacydocs00"
PUBLISHED_COVER_FILENAME = "cover.published123.png"
UNPUBLISHED_COVER_FILENAME = "cover.unpublished999.png"


class _FakeStore:
    def __init__(self) -> None:
        self.writes: dict[str, bytes] = {}
        self.read_keys: list[str] = []

    def list_prefix(self, prefix: str) -> list[str]:
        return [
            f"{prefix.rstrip('/')}/cover.png",
            f"{prefix.rstrip('/')}/{PUBLISHED_COVER_FILENAME}",
            f"{prefix.rstrip('/')}/{UNPUBLISHED_COVER_FILENAME}",
        ]

    def read_json_raw(self, key: str) -> dict[str, object] | None:
        if key.endswith("/knowledge_markdowns/manifest.json"):
            namespace = key.split("/knowledge_markdowns/", 1)[0]
            return {
                "docgen_manifest_key": (
                    f"{namespace}/knowledge_markdowns/versions/v0001/stale/docgen_manifest.json"
                )
            }
        if key.endswith("/versions/v0001/receipt/docgen_manifest.json"):
            namespace = key.split("/knowledge_markdowns/", 1)[0]
            return {
                "cover_artifact": {
                    "storage_key": f"{namespace}/assets/docgen/{PUBLISHED_COVER_FILENAME}",
                }
            }
        if key.endswith("/versions/v0001/stale/docgen_manifest.json"):
            namespace = key.split("/knowledge_markdowns/", 1)[0]
            return {
                "cover_artifact": {
                    "storage_key": f"{namespace}/assets/docgen/{UNPUBLISHED_COVER_FILENAME}",
                }
            }
        return None

    def read_text(self, _key: str) -> str:
        return ""

    def read_bytes(self, key: str) -> bytes:
        self.read_keys.append(key)
        if key in self.writes:
            return self.writes[key]
        if key.endswith(PUBLISHED_COVER_FILENAME):
            return b"cover-bytes"
        if key.endswith("/cover.png"):
            return b"stale-cover-bytes"
        raise AssertionError(f"unexpected cover read: {key}")

    def write_bytes(self, key: str, data: bytes) -> None:
        self.writes[key] = data

    def delete_prefix(self, prefix: str) -> int:
        self.writes = {key: value for key, value in self.writes.items() if not key.startswith(prefix)}
        return 1

    def user_file_scope(self, *, user_id: str):
        from app.shared.infra.storage.course_scope import build_user_file_storage_scope

        return build_user_file_storage_scope(user_id=user_id)


def _run_store_sync(func, *args, default=None, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return default


@pytest.fixture
def export_import_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore()
    monkeypatch.setattr(export_module, "get_content_store", lambda: store)
    monkeypatch.setattr(import_module, "get_content_store", lambda: store)
    monkeypatch.setattr(export_module, "run_store_sync", _run_store_sync)
    monkeypatch.setattr(import_module, "run_store_sync", _run_store_sync)
    monkeypatch.setattr(import_module, "ensure_published_knowledge_manifest", lambda *args, **kwargs: None)
    return store


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db


def _seed_course_graph(session: Session) -> None:
    course = Course(
        id=COURSE_ID,
        user_id="user-1",
        name="Linear Algebra",
        description="Matrix course",
        user_intent="Review fundamentals",
        settings_json='{"embedding":{"mode":"enabled"},"course_icon_key":"math"}',
    )
    first = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="Matrices",
        normalized_name="matrices",
        status="active",
    )
    second = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="Determinants",
        normalized_name="determinants",
        status="active",
    )
    planner_session = ChatSession(
        id="session-1",
        course_id=COURSE_ID,
        user_id="user-1",
        title="Planner",
        source="build_planner",
        meta_json={
            "confirmed_plan": {
                "id": "plan-1",
                "course_id": COURSE_ID,
                "selected_file_ids": ["file-old"],
                "plan_json": {"course_id": COURSE_ID, "selected_file_ids": ["file-old"]},
            }
        },
    )
    session.add(course)
    session.add(first)
    session.add(second)
    session.add(planner_session)
    session.add(
        KnowledgeDocument(
            course_id=COURSE_ID,
            chapter_index=1,
            title="Matrices",
            markdown_content="# Matrices",
            markdown_path=(
                f"users/user-1/courses/{COURSE_ID}/knowledge_markdowns/"
                "versions/v0001/receipt/chapter_01_Matrices.md"
            ),
            is_current=True,
            status="published",
        )
    )
    session.commit()
    session.refresh(first)
    session.refresh(second)
    session.add(
        KnowledgeEdge(
            course_id=COURSE_ID,
            source_node_id=int(first.id or 0),
            target_node_id=int(second.id or 0),
            edge_type="prerequisite_for",
            status="active",
            description="Matrices support determinants",
            confidence=0.8,
        )
    )
    session.commit()


def test_export_preview_and_archive_include_selected_course_graph(
    session: Session,
    export_import_store: _FakeStore,
) -> None:
    _seed_course_graph(session)
    options = ExportOptions(
        include_raw_markdowns=False,
        include_knowledge_docs=True,
        include_chat_history=False,
        include_exam_history=False,
        include_profile=False,
    )

    preview = export_module.preview_export(session, course_id=COURSE_ID, options=options)
    package_path = export_module.export_course(session, course_id=COURSE_ID, options=options)

    try:
        assert preview.course_name == "Linear Algebra"
        assert preview.stats.knowledge_unit_count == 2
        assert preview.stats.knowledge_edge_count == 1
        assert preview.stats.confirmed_build_plan_count == 1

        with zipfile.ZipFile(package_path, "r") as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            units = json.loads(zf.read("db/knowledge_unit.json"))
            chat_sessions = json.loads(zf.read("db/chat_session.json"))

        assert "db/course.json" in names
        assert "knowledge/cover.png" in names
        assert manifest["course"]["course_id"] == COURSE_ID
        assert manifest["stats"]["knowledge_unit_count"] == 2
        assert manifest["package"]["capabilities"] == ["course_metadata", "knowledge_graph", "knowledge_docs"]
        assert units["count"] == 2
        assert chat_sessions["count"] == 1
        assert export_import_store.writes == {}
    finally:
        package_path.unlink(missing_ok=True)


def test_export_skips_stale_cover_without_current_published_docs(
    session: Session,
    export_import_store: _FakeStore,
) -> None:
    session.add(
        Course(
            id=EMPTY_DOCS_COURSE_ID,
            user_id="user-1",
            name="Empty Docs",
        )
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=EMPTY_DOCS_COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=True,
            include_chat_history=False,
            include_exam_history=False,
            include_profile=False,
        ),
    )

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            assert "knowledge/cover.png" not in set(zf.namelist())
        assert export_import_store.read_keys == []
    finally:
        package_path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "invalid_path",
    [
        (
            f"users/foreign-user/courses/{COURSE_ID}/knowledge_markdowns/"
            "versions/v0001/receipt/chapter_02_Determinants.md"
        ),
        (
            f"users/user-1/courses/{COURSE_ID}/knowledge_markdowns/"
            "versions/v0001"
        ),
    ],
)
def test_export_skips_cover_when_versioned_current_docs_have_invalid_receipt_path(
    session: Session,
    export_import_store: _FakeStore,
    invalid_path: str,
) -> None:
    _seed_course_graph(session)
    session.add(
        KnowledgeDocument(
            course_id=COURSE_ID,
            chapter_index=2,
            title="Determinants",
            markdown_content="# Determinants",
            markdown_path=invalid_path,
            is_current=True,
            status="published",
        )
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=True,
            include_chat_history=False,
            include_exam_history=False,
            include_profile=False,
        ),
    )

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            assert "knowledge/cover.png" not in set(zf.namelist())
        assert export_import_store.read_keys == []
    finally:
        package_path.unlink(missing_ok=True)


def test_export_skips_legacy_storage_cover_without_current_doc_reference(
    session: Session,
    export_import_store: _FakeStore,
) -> None:
    session.add(
        Course(
            id=LEGACY_DOCS_COURSE_ID,
            user_id="user-1",
            name="Legacy Docs",
        )
    )
    session.add(
        KnowledgeDocument(
            course_id=LEGACY_DOCS_COURSE_ID,
            chapter_index=1,
            title="Legacy Chapter",
            markdown_content="# Legacy Chapter\n\nNo published cover reference.",
            markdown_path=None,
            is_current=True,
            status="published",
        )
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=LEGACY_DOCS_COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=True,
            include_chat_history=False,
            include_exam_history=False,
            include_profile=False,
        ),
    )

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            assert "knowledge/cover.png" not in set(zf.namelist())
        assert export_import_store.read_keys == []
    finally:
        package_path.unlink(missing_ok=True)


def test_import_rewrites_legacy_docgen_cover_reference(
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.add(
        Course(
            id=LEGACY_DOCS_COURSE_ID,
            user_id="user-1",
            name="Legacy Docs",
        )
    )
    session.add(
        KnowledgeDocument(
            course_id=LEGACY_DOCS_COURSE_ID,
            chapter_index=1,
            title="Legacy Chapter",
            markdown_content=(
                f"![](../assets/docgen/{PUBLISHED_COVER_FILENAME})\n\n"
                "# Legacy Chapter"
            ),
            markdown_path=(
                f"users/user-1/courses/{LEGACY_DOCS_COURSE_ID}/"
                "knowledge_markdowns/chapter_01.md"
            ),
            is_current=True,
            status="published",
        )
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=LEGACY_DOCS_COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=True,
            include_chat_history=False,
            include_exam_history=False,
            include_profile=False,
        ),
    )
    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    monkeypatch.setattr(
        import_module,
        "_create_unique_course_id",
        lambda _session: IMPORTED_COURSE_ID,
    )

    try:
        with zipfile.ZipFile(package_path, "r") as exported:
            assert exported.read("knowledge/cover.png") == b"cover-bytes"

        with Session(target_engine, expire_on_commit=False) as target_session:
            import_module.import_course(
                target_session,
                file_path=package_path,
                options=ImportOptions(
                    new_course_name="Imported Legacy Docs",
                    rebuild_embeddings=False,
                ),
                user_id="user-2",
            )
            imported_doc = target_session.exec(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.course_id == IMPORTED_COURSE_ID,
                    KnowledgeDocument.is_current.is_(True),
                    KnowledgeDocument.status == "published",
                )
            ).one()

        assert PUBLISHED_COVER_FILENAME not in imported_doc.markdown_content
        assert imported_doc.markdown_content.count(
            "![](../assets/docgen/cover.png)"
        ) == 1
        assert imported_doc.markdown_content.endswith("# Legacy Chapter")
    finally:
        package_path.unlink(missing_ok=True)


def test_import_course_remaps_ids_and_restores_docgen_assets(
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_course_graph(session)
    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=True,
            include_chat_history=False,
            include_exam_history=False,
            include_profile=False,
        ),
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda session: IMPORTED_COURSE_ID)
    reexport_path: Path | None = None

    try:
        with Session(engine, expire_on_commit=False) as target_session:
            result = import_module.import_course(
                target_session,
                file_path=package_path,
                options=ImportOptions(new_course_name="Imported Algebra", rebuild_embeddings=False),
                user_id="user-2",
            )
            imported_course = target_session.exec(select(Course).where(Course.id == IMPORTED_COURSE_ID)).first()
            imported_units = target_session.exec(select(KnowledgeUnit).where(KnowledgeUnit.course_id == IMPORTED_COURSE_ID)).all()
            imported_edges = target_session.exec(select(KnowledgeEdge).where(KnowledgeEdge.course_id == IMPORTED_COURSE_ID)).all()
            imported_doc = target_session.exec(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.course_id == IMPORTED_COURSE_ID,
                    KnowledgeDocument.is_current.is_(True),
                    KnowledgeDocument.status == "published",
                )
                .order_by(
                    KnowledgeDocument.order_index,
                    KnowledgeDocument.chapter_index,
                    KnowledgeDocument.id,
                )
            ).first()
            published_result = docgen_build_lifecycle.get_docgen_result(
                target_session,
                course_id=IMPORTED_COURSE_ID,
                course_scope=build_course_storage_scope(
                    user_id="user-2",
                    course_id=IMPORTED_COURSE_ID,
                ),
            )
            reexport_path = export_module.export_course(
                target_session,
                course_id=IMPORTED_COURSE_ID,
                options=ExportOptions(
                    include_raw_markdowns=False,
                    include_knowledge_docs=True,
                    include_chat_history=False,
                    include_exam_history=False,
                    include_profile=False,
                ),
            )
            with zipfile.ZipFile(reexport_path, "r") as reexported:
                reexported_cover = reexported.read("knowledge/cover.png")

        assert result.course_id == IMPORTED_COURSE_ID
        assert result.course_name == "Imported Algebra"
        assert result.imported_counts["course"] == 1
        assert result.imported_counts["knowledge_unit"] == 2
        assert result.imported_counts["knowledge_edge"] == 1
        assert imported_course is not None
        assert imported_course.user_id == "user-2"
        assert imported_course.name == "Imported Algebra"
        assert len(imported_units) == 2
        assert len(imported_edges) == 1
        assert imported_doc is not None
        assert imported_doc.markdown_path is None
        assert imported_doc.markdown_content.startswith(
            "![](../assets/docgen/cover.png)\n\n# Matrices"
        )
        assert imported_doc.markdown_content.count(
            "![](../assets/docgen/cover.png)"
        ) == 1
        assert published_result.exists is True
        assert "![](../assets/docgen/cover.png)" in published_result.markdown
        assert "# Matrices" in published_result.markdown
        assert reexported_cover == b"cover-bytes"
        assert any(key.endswith("/assets/docgen/cover.png") for key in export_import_store.writes)
    finally:
        package_path.unlink(missing_ok=True)
        if reexport_path is not None:
            reexport_path.unlink(missing_ok=True)


def test_import_course_remaps_chat_context_citation_ids(
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del export_import_store
    course = Course(id=COURSE_ID, user_id="user-1", name="Citation Course")
    unit = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="Eigenvalues",
        normalized_name="eigenvalues",
        status="active",
    )
    raw_file = RawFile(
        id="file-old",
        user_id="user-1",
        origin_course_id=COURSE_ID,
        origin_course_name="Citation Course",
        filename="lecture.pdf",
        filetype="pdf",
        file_path="users/user-1/files/file-old/raw.pdf",
        markdown_content="# Eigenvalues",
        content_hash="sha256-old-chat-context",
        file_size_bytes=128,
        status="completed",
        ingest_status="completed",
    )
    link = CourseFileLink(user_id="user-1", course_id=COURSE_ID, file_id=raw_file.id)
    chat_session = ChatSession(
        id="chat-1",
        course_id=COURSE_ID,
        user_id="user-1",
        title="Citation Chat",
        source="quick_chat",
    )
    session.add(course)
    session.add(unit)
    session.add(raw_file)
    session.add(link)
    session.add(chat_session)
    session.commit()
    session.refresh(unit)

    chunk = RetrievalChunk(
        course_id=COURSE_ID,
        file_id=raw_file.id,
        title="Eigenvalues section",
        level=1,
        header_path="Eigenvalues",
        chunk_index=1,
        digest_chunk_uid="chunk-old",
        content="Eigenvalues summarize linear transformations.",
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)

    old_chunk_id = int(chunk.id or 0)
    old_unit_id = int(unit.id or 0)
    session.add(
        ChatMessage(
            course_id=COURSE_ID,
            user_id="user-1",
            session_id=chat_session.id,
            turn_id="turn-1",
            role="assistant",
            content="See the cited section.",
            source_chunk_id=old_chunk_id,
            contexts_json=[
                {
                    "chunk_id": old_chunk_id,
                    "file_id": raw_file.id,
                    "title": "Eigenvalues section",
                    "header_path": "Eigenvalues",
                    "score": 0.91,
                    "knowledge_unit_id": old_unit_id,
                    "knowledge_unit_name": "Eigenvalues",
                    "knowledge_unit_type": "concept",
                    "retrieval_source": "vector",
                }
            ],
        )
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=True,
            include_knowledge_docs=False,
            include_chat_history=True,
            include_exam_history=False,
            include_profile=False,
        ),
    )
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda session: IMPORTED_COURSE_ID)

    try:
        import_module.import_course(
            session,
            file_path=package_path,
            options=ImportOptions(new_course_name="Imported Citations", rebuild_embeddings=False),
            user_id="user-2",
        )

        imported_message = session.exec(
            select(ChatMessage).where(
                ChatMessage.course_id == IMPORTED_COURSE_ID,
                ChatMessage.role == "assistant",
            )
        ).first()
        imported_unit = session.exec(
            select(KnowledgeUnit).where(
                KnowledgeUnit.course_id == IMPORTED_COURSE_ID,
                KnowledgeUnit.canonical_name == "Eigenvalues",
            )
        ).first()

        assert imported_message is not None
        assert imported_unit is not None
        assert imported_message.source_chunk_id is not None
        assert imported_message.source_chunk_id != old_chunk_id

        imported_chunk = session.get(RetrievalChunk, imported_message.source_chunk_id)
        contexts = imported_message.contexts_json

        assert imported_chunk is not None
        assert isinstance(contexts, list)
        assert contexts[0]["chunk_id"] == imported_message.source_chunk_id
        assert contexts[0]["file_id"] == imported_chunk.file_id
        assert contexts[0]["knowledge_unit_id"] == imported_unit.id
    finally:
        package_path.unlink(missing_ok=True)


def test_manifest_and_table_helpers_expose_package_contract(tmp_path: Path) -> None:
    manifest = export_module._build_manifest(
        Course(id=COURSE_ID, user_id="user-1", name="Linear Algebra", settings_json='{"course_icon_key":"math"}'),
        {
            "course": [{"id": COURSE_ID}],
            "knowledge_unit": [{"id": 1}],
            "chat_session": [{"meta_json": {"confirmed_plan": {"id": "plan-1"}}}],
        },
        ExportOptions(include_raw_markdowns=True, include_chat_history=True, include_exam_history=False, include_profile=True),
    )

    manifest_dir = tmp_path / "package"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    read_back = export_module._read_manifest(manifest_dir)
    table_contract = export_module._build_manifest_tables({"course": [{}], "unknown": [{}, {}]})

    assert "raw_file_metadata" in manifest.package.capabilities
    assert "profile" in manifest.package.capabilities
    assert manifest.stats.confirmed_build_plan_count == 1
    assert read_back.package.kind == "course_export"
    assert table_contract[0].name == "course"
    assert table_contract[1].id_type == "auto"


def test_settings_and_foreign_key_remap_helpers_normalize_import_records() -> None:
    record = {
        "settings_json": {"embedding": {"mode": "enabled"}},
        "course_id": "old",
        "source_file_ids_json": '["old-file", "missing"]',
        "entity_type": "unit",
        "entity_id": "old-unit",
    }
    disabled_record = {
        "settings_json": {"embedding": {"mode": "disabled"}, "course_icon_key": "math"},
    }
    warnings: list[str] = []
    id_map: dict[str, dict[Any, Any]] = {
        "raw_file": {"old-file": "new-file"},
        "knowledge_unit": {"old-unit": 10},
    }

    export_module._prepare_imported_course_settings(record, "Linear Algebra")
    export_module._prepare_imported_course_settings(disabled_record, "Linear Algebra")
    export_module._remap_json_int_list_text_field(
        record,
        "source_file_ids_json",
        "raw_file",
        id_map,
        "knowledge_graph_source_ref",
        warnings,
    )
    export_module._remap_graph_source_ref_entity(record, id_map, warnings)

    assert "embedding" not in json.loads(record["settings_json"])
    disabled_settings = json.loads(disabled_record["settings_json"])
    assert "embedding" not in disabled_settings
    assert disabled_settings["course_icon_key"] == "math"
    assert json.loads(record["source_file_ids_json"]) == ["new-file"]
    assert record["entity_id"] == 10
    assert warnings == ["knowledge_graph_source_ref.source_file_ids_json: ref missing not found in raw_file"]

    fk_record = {"question_template_id": "1", "source_ids": ["1", "2", "missing"]}
    export_module._remap_fk(fk_record, "question_template_id", "question_template", {"question_template": {1: 100}}, "link", warnings)
    export_module._remap_id_list_field(
        fk_record,
        "source_ids",
        "question_template",
        {"question_template": {"1": 100, 2: 200}},
        "link",
        warnings,
    )

    assert fk_record["question_template_id"] == 100
    assert fk_record["source_ids"] == [100, 200]
    assert warnings[-1] == "link.source_ids: ref missing not found in question_template"


def test_planner_meta_remap_updates_plan_identity_and_selected_files() -> None:
    record = {
        "id": "new-session",
        "meta_json": {
            "selected_file_ids": ["old-file", "missing"],
            "confirmed_plan_id": "old-plan",
            "confirmed_plan": {
                "id": "old-plan",
                "course_id": "old-course",
                "selected_file_ids": ["old-file"],
                "plan_json": {"course_id": "old-course", "selected_file_ids": ["old-file"]},
            },
        },
    }
    warnings: list[str] = []

    export_module._remap_planner_meta(
        record,
        new_course_id=IMPORTED_COURSE_ID,
        user_id="user-2",
        id_map={"raw_file": {"old-file": "new-file"}},
        warnings=warnings,
    )

    meta = record["meta_json"]
    assert meta["selected_file_ids"] == ["new-file"]
    assert meta["confirmed_plan"]["course_id"] == IMPORTED_COURSE_ID
    assert meta["confirmed_plan"]["user_id"] == "user-2"
    assert meta["confirmed_plan"]["selected_file_ids"] == ["new-file"]
    assert meta["confirmed_plan"]["plan_json"]["confirmed_plan_id"] == meta["confirmed_plan"]["id"]
    assert meta["confirmed_plan_history"][0]["id"] == meta["confirmed_plan"]["id"]


def test_import_archive_validation_rejects_bad_shapes_and_paths(tmp_path: Path) -> None:
    traversal_zip = tmp_path / "traversal.atmx"
    with zipfile.ZipFile(traversal_zip, "w") as zf:
        zf.writestr("../evil.txt", "no")

    with zipfile.ZipFile(traversal_zip, "r") as zf:
        with pytest.raises(InvalidImportPackageError):
            import_module._safe_extract_archive(zf, tmp_path / "extract")

    bad_table = tmp_path / "bad.json"
    bad_table.write_text('{"records": "not-a-list"}', encoding="utf-8")
    with pytest.raises(InvalidImportPackageError):
        import_module._read_table_records(bad_table, "course")

    bad_manifest_dir = tmp_path / "bad-manifest"
    bad_manifest_dir.mkdir()
    (bad_manifest_dir / "manifest.json").write_text('{"format_version":"999","course":{"course_id":"x","name":"x"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported format version"):
        export_module._read_manifest(bad_manifest_dir)


def test_import_lookup_and_background_rebuild_scheduling() -> None:
    assert import_module._lookup_imported_id("1", {1: "one"}) == "one"
    assert import_module._lookup_imported_id(2, {"2": "two"}) == "two"
    assert import_module._lookup_imported_or_existing_id("existing", {"old": "existing"}) == "existing"
    assert import_module._import_embedding_rebuild_concurrency_limit(global_limit=10) == 1
    assert import_module._import_embedding_rebuild_concurrency_limit(global_limit=3) == 1
    assert import_module._import_embedding_rebuild_concurrency_limit(global_limit=1) == 1
    assert import_module.spawn_imported_embedding_rebuild_background(
        None,
        course_id=IMPORTED_COURSE_ID,
        imported_counts={"retrieval_chunk": 0},
    ) is False
    assert import_module.spawn_imported_embedding_rebuild_background(
        None,
        course_id=IMPORTED_COURSE_ID,
        imported_counts={"retrieval_chunk": 2},
    ) is False

    class Registry:
        def __init__(self) -> None:
            self.names: list[str] = []

        def spawn(self, coroutine, **kwargs) -> None:
            coroutine.close()
            self.names.append(kwargs["name"])

    registry = Registry()
    assert import_module.spawn_imported_embedding_rebuild_background(
        registry,
        course_id=IMPORTED_COURSE_ID,
        imported_counts={"retrieval_chunk": 2},
    ) is True
    assert registry.names == [f"course.import.embeddings:{IMPORTED_COURSE_ID}"]


def test_imported_embedding_rebuild_reserves_foreground_llm_slots(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    session.add(
        Course(
            id=IMPORTED_COURSE_ID,
            user_id="user-2",
            name="Imported Algebra",
            settings_json='{"embedding":{"mode":"enabled"}}',
        )
    )
    session.add(
        RawFile(
            id="imported-file-1",
            user_id="user-2",
            filename="algebra.md",
            filetype="markdown",
            file_path="algebra.md",
        )
    )
    for index in range(5):
        session.add(
            RetrievalChunk(
                course_id=IMPORTED_COURSE_ID,
                file_id="imported-file-1",
                title=f"Chunk {index}",
                level=1,
                header_path=f"Chunk {index}",
                chunk_index=index,
                digest_chunk_uid=f"chunk-{index}",
                content=f"content {index}",
            )
        )
    session.commit()

    async def fake_aembed_texts(texts, *, batch_size=None, soft_fail=False, model=None, max_concurrent=None, **_kwargs):
        captured["text_count"] = len(texts)
        captured["batch_size"] = batch_size
        captured["soft_fail"] = soft_fail
        captured["model"] = model
        captured["max_concurrent"] = max_concurrent
        return [[0.1, 0.2] for _ in texts]

    def fake_bulk_insert_embeddings(_session, *, course_id, chunk_ids, embeddings, embedding_model=None):
        captured["course_id"] = course_id
        captured["chunk_ids"] = list(chunk_ids)
        captured["embedding_count"] = len(embeddings)
        captured["embedding_model"] = embedding_model

    monkeypatch.setattr(import_module, "should_generate_course_embeddings", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        import_module,
        "get_runtime_embedding_config",
        lambda: SimpleNamespace(embedding_model="text-embedding-v4"),
    )
    monkeypatch.setattr(import_module, "get_llm_concurrency_limit", lambda: 10)
    monkeypatch.setattr(import_module, "aembed_texts", fake_aembed_texts)
    monkeypatch.setattr(import_module.knowledge_repo, "bulk_insert_embeddings", fake_bulk_insert_embeddings)

    warnings: list[str] = []
    import_module._rebuild_imported_embeddings(
        session,
        course_id=IMPORTED_COURSE_ID,
        imported_counts={"retrieval_chunk": 5},
        warnings=warnings,
    )

    assert warnings == []
    assert captured["text_count"] == 5
    assert captured["batch_size"] == 1
    assert captured["soft_fail"] is True
    assert captured["model"] == "text-embedding-v4"
    assert captured["max_concurrent"] == 1
    assert captured["course_id"] == IMPORTED_COURSE_ID
    assert captured["embedding_count"] == 5
    assert captured["embedding_model"] == "text-embedding-v4"


def test_run_async_handles_plain_coroutines() -> None:
    async def compute() -> str:
        return "done"

    assert import_module._run_async(compute()) == "done"
