from __future__ import annotations

import base64
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
from app.api import exams as exams_api
from app.models import (
    ChatMessage,
    ChatSession,
    Course,
    CourseFileLink,
    ExamPaper,
    ExamPaperItem,
    KnowledgeEdge,
    KnowledgeDocument,
    KnowledgeUnit,
    MasteryDrillAttempt,
    MasteryDrillSession,
    QuestionTemplate,
    QuestionTypePackageVersion,
    QuestionTypeRegistry,
    RawFile,
    RetrievalChunk,
)
from app.schemas.export_import import ExportOptions, ImportOptions
from app.shared.infra.exceptions import InvalidImportPackageError
from app.workflows.support import course_shares as course_shares_module
from app.shared.infra.storage import build_course_storage_scope
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib import build_lifecycle as docgen_build_lifecycle
from app.workflows.support.export_import import exports as export_module
from app.workflows.support.export_import import imports as import_module
from app.workflows.support.question_type_packages import build_atqskill_archive, validate_atqskill
from app.workflows.support.question_type_packages.contracts import (
    CompiledQuestionTypeDefinition,
)
from app.workflows.support.question_type_packages.installer import (
    create_pending_import,
    install_pending_import,
)
from app.workflows.examine.question_types.runtime import (
    resolve_course_question_type_runtimes,
    resolve_question_type_version,
)


COURSE_ID = "course_math00000000"
IMPORTED_COURSE_ID = "course_imported1234"
_VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\nverified-image"
EMPTY_DOCS_COURSE_ID = "course_emptydocs000"
LEGACY_DOCS_COURSE_ID = "course_legacydocs00"
PUBLISHED_COVER_FILENAME = "cover.published123.png"
UNPUBLISHED_COVER_FILENAME = "cover.unpublished999.png"
EXAMPLE_QUESTION_TYPE_ROOT = (
    Path(__file__).resolve().parents[2] / "examples" / "question-type-skills"
)


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


def test_share_snapshot_strips_private_data_from_real_export(
    session: Session,
    export_import_store: _FakeStore,
) -> None:
    del export_import_store
    _seed_course_graph(session)
    course = session.get(Course, COURSE_ID)
    assert course is not None
    options = ExportOptions(
        include_raw_files=False,
        include_raw_markdowns=False,
        include_knowledge_docs=True,
        include_chat_history=False,
        include_exam_history=False,
        include_profile=False,
    )
    package_path = export_module.export_course(session, course_id=COURSE_ID, options=options)
    snapshot_path: Path | None = None

    try:
        snapshot_path, _stats = course_shares_module._build_share_snapshot(
            package_path,
            course=course,
            options=options,
        )
        with zipfile.ZipFile(snapshot_path, "r") as archive:
            names = set(archive.namelist())
            unpacked = b"\n".join(archive.read(name) for name in names)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

        assert names == {
            "manifest.json",
            "db/course.json",
            "db/knowledge_document.json",
            "db/knowledge_unit.json",
            "db/knowledge_edge.json",
        }
        assert manifest["extensions"]["share_snapshot_schema"] == "aiteachme.course-share.v1"
        for private_marker in (
            b"Review fundamentals",
            b"embedding",
            b"file-old",
            b"session-1",
            b"user-1",
        ):
            assert private_marker not in unpacked
    finally:
        package_path.unlink(missing_ok=True)
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)


def test_mastery_drill_history_is_excluded_from_course_packages(
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_course_graph(session)
    template = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="single_choice",
        difficulty="medium",
        stem="Which matrix is invertible?",
        stem_hash="mastery-drill-export-template",
        options_json='["A", "B"]',
        answer="A",
        explanation="A has a non-zero determinant.",
    )
    session.add(template)
    session.flush()
    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id="user-1",
        exam_mode="mastery_drill",
        status="graded",
        total_items=1,
        total_score=1.0,
        score_obtained=1.0,
    )
    session.add(paper)
    session.flush()
    item = ExamPaperItem(
        exam_paper_id=int(paper.id or 0),
        question_template_id=int(template.id or 0),
        item_order=1,
        stem_snapshot=template.stem,
        options_snapshot_json=template.options_json,
        answer_snapshot=template.answer,
        explanation_snapshot=template.explanation,
        difficulty=template.difficulty,
        question_type=template.question_type,
        answer_content="A",
        is_correct=True,
        score=1.0,
        score_obtained=1.0,
        score_max=1.0,
    )
    session.add(item)
    session.flush()
    drill = MasteryDrillSession(
        exam_paper_id=int(paper.id or 0),
        course_id=COURSE_ID,
        user_id="user-1",
        session_key="mastery-drill-export-session",
        status="completed",
        total_attempts=2,
        wrong_attempts=1,
        completion_key="mastery-drill-export-complete",
        completed_at=utcnow(),
    )
    session.add(drill)
    session.flush()
    session.add_all(
        [
            MasteryDrillAttempt(
                mastery_drill_session_id=int(drill.id or 0),
                exam_paper_item_id=int(item.id or 0),
                question_template_id=int(template.id or 0),
                attempt_no=1,
                attempt_key="mastery-drill-export-attempt-1",
                request_hash="request-hash-1",
                status="graded",
                answer_content="B",
                is_correct=False,
                score_obtained=0.0,
                score_max=1.0,
                answered_at=utcnow(),
            ),
            MasteryDrillAttempt(
                mastery_drill_session_id=int(drill.id or 0),
                exam_paper_item_id=int(item.id or 0),
                question_template_id=int(template.id or 0),
                attempt_no=2,
                attempt_key="mastery-drill-export-attempt-2",
                request_hash="request-hash-2",
                status="graded",
                answer_content="A",
                is_correct=True,
                score_obtained=1.0,
                score_max=1.0,
                answered_at=utcnow(),
            ),
        ]
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=False,
            include_chat_history=False,
            include_exam_history=True,
            include_profile=False,
        ),
    )
    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda _session: IMPORTED_COURSE_ID)

    try:
        with zipfile.ZipFile(package_path, "r") as exported:
            names = set(exported.namelist())
            assert "db/mastery_drill_session.json" not in names
            assert "db/mastery_drill_attempt.json" not in names
            exported_papers = json.loads(exported.read("db/exam_paper.json"))
            assert exported_papers["count"] == 0

        with Session(target_engine, expire_on_commit=False) as target_session:
            result = import_module.import_course(
                target_session,
                file_path=package_path,
                options=ImportOptions(new_course_name="Imported Algebra", rebuild_embeddings=False),
                user_id="user-2",
            )
            imported_templates = target_session.exec(
                select(QuestionTemplate).where(QuestionTemplate.course_id == IMPORTED_COURSE_ID)
            ).all()
            imported_papers = target_session.exec(
                select(ExamPaper).where(ExamPaper.course_id == IMPORTED_COURSE_ID)
            ).all()
            imported_drills = target_session.exec(
                select(MasteryDrillSession).where(MasteryDrillSession.course_id == IMPORTED_COURSE_ID)
            ).all()
            imported_attempts = target_session.exec(select(MasteryDrillAttempt)).all()

        assert len(imported_templates) == 1
        assert imported_papers == []
        assert imported_drills == []
        assert imported_attempts == []
        assert result.imported_counts.get("exam_paper", 0) == 0
        assert "mastery_drill_session" not in result.imported_counts
        assert "mastery_drill_attempt" not in result.imported_counts
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
    with zipfile.ZipFile(package_path, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("share_assets/docgen/figure.png", _VALID_PNG_BYTES)
        zf.writestr("share_assets/docgen/active.html", "<script>alert(1)</script>")
        zf.writestr("share_assets/docgen/vector.svg", "<svg><script>alert(1)</script></svg>")
        zf.writestr("share_assets/docgen/fake.png", b"<html>not an image</html>")

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
        shared_asset_key = f"users/user-2/courses/{IMPORTED_COURSE_ID}/assets/docgen/figure.png"
        assert export_import_store.writes[shared_asset_key] == _VALID_PNG_BYTES
        assert not any(key.endswith(("active.html", "vector.svg", "fake.png")) for key in export_import_store.writes)
    finally:
        package_path.unlink(missing_ok=True)
        if reexport_path is not None:
            reexport_path.unlink(missing_ok=True)


def test_import_course_can_defer_commit_and_cleanup_storage(
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
    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda session: IMPORTED_COURSE_ID)

    try:
        with Session(target_engine, expire_on_commit=False) as target_session:
            result = import_module.import_course(
                target_session,
                file_path=package_path,
                options=ImportOptions(new_course_name="Deferred Algebra", rebuild_embeddings=False),
                user_id="user-2",
                commit=False,
            )
            assert result.course_id == IMPORTED_COURSE_ID
            assert target_session.get(Course, IMPORTED_COURSE_ID) is not None

            target_session.rollback()
            assert target_session.get(Course, IMPORTED_COURSE_ID) is None

        import_module.cleanup_imported_course_artifacts(
            IMPORTED_COURSE_ID,
            user_id="user-2",
        )
        imported_prefix = f"users/user-2/courses/{IMPORTED_COURSE_ID}/"
        assert not any(key.startswith(imported_prefix) for key in export_import_store.writes)
    finally:
        target_engine.dispose()
        package_path.unlink(missing_ok=True)


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
            "planner_session_id": "old-session",
            "selected_file_ids": ["old-file", "missing"],
            "latest_plan": {
                "course_id": "old-course",
                "course": "old-course",
                "planner_session_id": "old-session",
                "selected_file_ids": ["old-file"],
                "planner_context": {"planner_session_id": "old-session"},
            },
            "confirmed_plan_id": "old-plan",
            "confirmed_plan": {
                "id": "old-plan",
                "course_id": "old-course",
                "selected_file_ids": ["old-file"],
                "plan_json": {
                    "course_id": "old-course",
                    "selected_file_ids": ["old-file"],
                    "planner_context": {"planner_session_id": "old-session"},
                },
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
    assert meta["planner_session_id"] == "new-session"
    assert meta["selected_file_ids"] == ["new-file"]
    assert meta["latest_plan"]["course_id"] == IMPORTED_COURSE_ID
    assert meta["latest_plan"]["course"] == IMPORTED_COURSE_ID
    assert meta["latest_plan"]["planner_session_id"] == "new-session"
    assert meta["latest_plan"]["selected_file_ids"] == ["new-file"]
    assert meta["latest_plan"]["planner_context"]["planner_session_id"] == "new-session"
    assert meta["confirmed_plan"]["course_id"] == IMPORTED_COURSE_ID
    assert meta["confirmed_plan"]["user_id"] == "user-2"
    assert meta["confirmed_plan"]["selected_file_ids"] == ["new-file"]
    assert meta["confirmed_plan"]["plan_json"]["confirmed_plan_id"] == meta["confirmed_plan"]["id"]
    assert meta["confirmed_plan"]["plan_json"]["planner_context"]["planner_session_id"] == "new-session"
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


def test_course_import_rejects_tampered_question_type_semantics(tmp_path: Path) -> None:
    package = build_atqskill_archive(
        EXAMPLE_QUESTION_TYPE_ROOT / "feynman_explanation",
        tmp_path / "feynman-semantics.atqskill",
    )
    result = validate_atqskill(package)
    assert result.compiled_definition is not None
    payload = result.compiled_definition.model_dump(mode="json")
    payload["rubric"][0]["weight"] = 0.3
    payload["manifest"]["grading"]["rubric"][0]["weight"] = 0.3
    tampered = CompiledQuestionTypeDefinition.model_validate(payload)
    record = {
        "id": 17,
        "package_key": tampered.package_key,
        "type_key": tampered.type_key,
        "version": tampered.version,
        "package_hash": tampered.package_sha256,
        "compiled_definition_json": tampered.model_dump_json(),
        "public_preview_json": json.dumps(
            import_module.build_public_definition(tampered),
            ensure_ascii=False,
        ),
    }

    with pytest.raises(InvalidImportPackageError, match="语义校验"):
        import_module._validate_imported_question_type_versions([record])


def test_course_import_rejects_non_image_question_type_asset() -> None:
    content = b"<script>document.body.dataset.compromised='true'</script>"
    record = {
        "id": 19,
        "path": "assets/payload.html",
        "role": "illustration",
        "media_type": "text/html",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "width": 1,
        "height": 1,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }

    with pytest.raises(InvalidImportPackageError, match="安全校验"):
        import_module._validate_imported_question_type_assets([record])


def test_public_share_asset_extraction_accepts_docgen_relative_prefix() -> None:
    documents = [
        {
            "markdown_content": (
                "![](../assets/docgen/cover.png)\n"
                "![](../../assets/private.png)\n"
                "![](../assets/docgen/../private.png)"
            )
        }
    ]

    assert export_module.extract_referenced_asset_paths(
        documents,
        local_only=True,
    ) == ["docgen/cover.png"]


def test_unpack_files_restores_share_assets_without_cover(
    session: Session,
    tmp_path: Path,
    export_import_store: _FakeStore,
) -> None:
    share_asset = tmp_path / "share_assets" / "docgen" / "figure.png"
    share_asset.parent.mkdir(parents=True)
    share_asset.write_bytes(_VALID_PNG_BYTES)

    import_module._unpack_files(
        session,
        tmp_path,
        IMPORTED_COURSE_ID,
        user_id="user-2",
        file_id_map={},
    )

    expected_key = (
        f"users/user-2/courses/{IMPORTED_COURSE_ID}/assets/docgen/figure.png"
    )
    assert export_import_store.writes[expected_key] == _VALID_PNG_BYTES


def test_restore_share_assets_requires_safe_type_magic_and_size(
    tmp_path: Path,
    export_import_store: _FakeStore,
) -> None:
    share_root = tmp_path / "share_assets" / "nested"
    share_root.mkdir(parents=True)
    valid_assets = {
        "image.png": _VALID_PNG_BYTES,
        "photo.jpg": b"\xff\xd8\xff\xe0jpeg",
        "photo.jpeg": b"\xff\xd8\xff\xe1jpeg",
        "animation.gif": b"GIF89aimage",
        "diagram.webp": b"RIFF\x04\x00\x00\x00WEBPimage",
    }
    for filename, data in valid_assets.items():
        (share_root / filename).write_bytes(data)
    (share_root / "active.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    (share_root / "vector.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
    (share_root / "fake.png").write_bytes(b"<html>not an image</html>")

    course_scope = import_module.build_course_storage_scope(
        user_id="user-2",
        course_id=IMPORTED_COURSE_ID,
    )
    import_module._restore_share_assets(
        tmp_path,
        course_scope=course_scope,
        content_store=export_import_store,
    )

    expected_keys = {
        f"{course_scope.namespace}/assets/nested/{filename}"
        for filename in valid_assets
    }
    assert set(export_import_store.writes) == expected_keys
    assert all(export_import_store.writes[key] == valid_assets[key.rsplit("/", 1)[-1]] for key in expected_keys)

    large_root = tmp_path / "large" / "share_assets"
    large_root.mkdir(parents=True)
    large_image = large_root / "too-large.png"
    with large_image.open("wb") as file:
        file.write(_VALID_PNG_BYTES)
        file.truncate(import_module.MAX_IMPORTED_SHARE_ASSET_BYTES + 1)

    with pytest.raises(InvalidImportPackageError, match="16 MiB"):
        import_module._restore_share_assets(
            tmp_path / "large",
            course_scope=course_scope,
            content_store=export_import_store,
        )


def test_import_lookup_and_background_rebuild_scheduling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_module, "_import_embedding_rebuild_route_unavailable_reason", lambda: None)

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


def test_import_embedding_rebuild_not_scheduled_when_model_route_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        import_module,
        "_import_embedding_rebuild_route_unavailable_reason",
        lambda: "embedding route unavailable",
    )

    class Registry:
        def spawn(self, coroutine, **_kwargs) -> None:  # pragma: no cover - must not be called
            coroutine.close()
            raise AssertionError("background rebuild should not be scheduled")

    assert import_module.spawn_imported_embedding_rebuild_background(
        Registry(),
        course_id=IMPORTED_COURSE_ID,
        imported_counts={"retrieval_chunk": 2},
    ) is False


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


def test_course_package_preserves_installed_question_type_without_exam_history(
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del export_import_store
    _seed_course_graph(session)
    source_package = build_atqskill_archive(
        EXAMPLE_QUESTION_TYPE_ROOT / "feynman_explanation",
        tmp_path / "feynman.atqskill",
    )
    validation = validate_atqskill(source_package)
    import_record, _preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id="user-1",
        original_filename=source_package.name,
        archive_bytes=source_package.read_bytes(),
        result=validation,
    )
    assert import_record is not None
    install_pending_import(
        session,
        course_id=COURSE_ID,
        user_id="user-1",
        import_id=import_record.id,
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=False,
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
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda _session: IMPORTED_COURSE_ID)

    try:
        with zipfile.ZipFile(package_path, "r") as exported:
            names = set(exported.namelist())
            assert "db/question_type_registry.json" in names
            assert "db/question_type_package_version.json" in names
            assert "db/question_type_package_asset.json" in names
            assert "db/question_template.json" not in names

        with Session(target_engine, expire_on_commit=False) as target_session:
            result = import_module.import_course(
                target_session,
                file_path=package_path,
                options=ImportOptions(
                    new_course_name="Imported with question type",
                    rebuild_embeddings=False,
                ),
                user_id="user-2",
            )
            registry = target_session.exec(
                select(QuestionTypeRegistry).where(
                    QuestionTypeRegistry.course_id == IMPORTED_COURSE_ID,
                    QuestionTypeRegistry.type_key == "custom_feynman_explanation",
                )
            ).one()
            version = target_session.exec(
                select(QuestionTypePackageVersion).where(
                    QuestionTypePackageVersion.course_id == IMPORTED_COURSE_ID,
                    QuestionTypePackageVersion.registry_id == registry.id,
                )
            ).one()

        assert registry.is_active is True
        assert version.version == "2.0.0"
        assert version.user_id == "user-2"
        assert result.imported_counts["question_type_package_version"] == 1
    finally:
        package_path.unlink(missing_ok=True)


@pytest.mark.parametrize("example_name", ["legacy_feynman_explanation", "feynman_explanation", "oral_defense", "scenario_interview", "argument_debate", "experiment_design", "case_analysis"])
def test_course_package_remaps_custom_question_runtime_snapshots(
    example_name: str,
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del export_import_store
    _seed_course_graph(session)
    source = (
        Path(__file__).parent / "fixtures/question_type_packages/v1/feynman_explanation"
        if example_name == "legacy_feynman_explanation"
        else EXAMPLE_QUESTION_TYPE_ROOT / example_name
    )
    source_package = build_atqskill_archive(
        source,
        tmp_path / "feynman-runtime.atqskill",
    )
    validation = validate_atqskill(source_package)
    import_record, _preview = create_pending_import(
        session,
        course_id=COURSE_ID,
        user_id="user-1",
        original_filename=source_package.name,
        archive_bytes=source_package.read_bytes(),
        result=validation,
    )
    assert import_record is not None
    installed = install_pending_import(
        session,
        course_id=COURSE_ID,
        user_id="user-1",
        import_id=import_record.id,
    )
    session.commit()
    runtime = resolve_course_question_type_runtimes(
        session,
        course_id=COURSE_ID,
        registry_ids=[installed.registry_id],
        mode="web_practice",
    )[0]
    unit = session.exec(
        select(KnowledgeUnit).where(KnowledgeUnit.course_id == COURSE_ID)
    ).first()
    assert unit is not None
    reference = runtime.definition.reference_cases[0].question["reference_answer"]
    custom_reference = reference if isinstance(reference, dict) else None
    template = exams_api._upsert_generated_template(
        session,
        course_id=COURSE_ID,
        unit=unit,
        question_type=runtime.type_key,
        difficulty="medium",
        stem="请向初学者解释矩阵，并给出一个具体例子和适用边界。",
        answer="矩阵是按行列排列的数表，可表示线性变换；矩阵乘法需要维度匹配。",
        explanation="应说明矩阵含义、例子以及运算维度限制。",
        options=None,
        custom_runtime=runtime.workflow_payload(),
        answer_payload=custom_reference,
    )
    if custom_reference and len(custom_reference) == 1:
        assert template.answer == next(iter(custom_reference.values()))
    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id="user-1",
        exam_mode="web_practice",
        status="graded",
        total_items=1,
        config_snapshot_json=json.dumps(
            {"question_type_runtimes": [runtime.snapshot_payload()]},
            ensure_ascii=False,
        ),
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    session.add(
        ExamPaperItem(
            exam_paper_id=int(paper.id or 0),
            question_template_id=int(template.id or 0),
            question_type_registry_id=template.question_type_registry_id,
            question_type_version_id=template.question_type_version_id,
            item_order=1,
            stem_snapshot=template.stem,
            options_snapshot_json=template.options_json,
            answer_snapshot=template.answer,
            explanation_snapshot=template.explanation,
            public_payload_snapshot_json=template.public_payload_json,
            answer_schema_snapshot_json=template.answer_schema_json,
            reference_answer_snapshot_json=template.reference_answer_json,
            grading_spec_snapshot_json=template.grading_spec_json,
            runtime_snapshot_json=template.runtime_snapshot_json,
            profile_eligible=template.profile_eligible,
            difficulty=template.difficulty,
            question_type=template.question_type,
            answer_content="矩阵是数表，也能表示线性变换。",
            answer_payload_json=json.dumps(
                custom_reference or {"explanation": "矩阵是数表，也能表示线性变换。"},
                ensure_ascii=False,
            ),
            grading_status="graded",
        )
    )
    session.commit()

    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=False,
            include_chat_history=False,
            include_exam_history=True,
            include_profile=False,
        ),
    )
    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda _session: IMPORTED_COURSE_ID)

    try:
        with Session(target_engine, expire_on_commit=False) as target_session:
            import_module.import_course(
                target_session,
                file_path=package_path,
                options=ImportOptions(
                    new_course_name="Imported custom runtime",
                    rebuild_embeddings=False,
                ),
                user_id="user-2",
            )
            imported_registry = target_session.exec(
                select(QuestionTypeRegistry).where(
                    QuestionTypeRegistry.course_id == IMPORTED_COURSE_ID,
                    QuestionTypeRegistry.type_key == runtime.type_key,
                )
            ).one()
            imported_version = target_session.exec(
                select(QuestionTypePackageVersion).where(
                    QuestionTypePackageVersion.course_id == IMPORTED_COURSE_ID,
                    QuestionTypePackageVersion.registry_id == imported_registry.id,
                )
            ).one()
            imported_template = target_session.exec(
                select(QuestionTemplate).where(
                    QuestionTemplate.course_id == IMPORTED_COURSE_ID,
                    QuestionTemplate.question_type == runtime.type_key,
                )
            ).one()
            imported_item = target_session.exec(
                select(ExamPaperItem).where(
                    ExamPaperItem.question_template_id == imported_template.id
                )
            ).one()

        assert imported_template.question_type_registry_id == imported_registry.id
        assert imported_template.question_type_version_id == imported_version.id
        assert imported_item.question_type_registry_id == imported_registry.id
        assert imported_item.question_type_version_id == imported_version.id
        template_runtime = json.loads(imported_template.runtime_snapshot_json)
        item_runtime = json.loads(imported_item.runtime_snapshot_json)
        assert template_runtime["registry_id"] == imported_registry.id
        assert template_runtime["version_id"] == imported_version.id
        assert item_runtime == template_runtime
        assert imported_template.reference_answer_json == template.reference_answer_json
        assert imported_item.answer_schema_snapshot_json == template.answer_schema_json
        if custom_reference:
            assert json.loads(imported_item.answer_payload_json) == custom_reference
    finally:
        package_path.unlink(missing_ok=True)


@pytest.mark.parametrize("reserved_version_id", [1, 10])
def test_imported_custom_questions_reuse_their_own_version_after_regeneration(
    reserved_version_id: int,
    session: Session,
    export_import_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Remapped IDs must neither duplicate questions nor overwrite another version."""
    _seed_course_graph(session)
    package_source = tmp_path / "case_analysis"
    shutil.copytree(EXAMPLE_QUESTION_TYPE_ROOT / "case_analysis", package_source)
    skill = package_source / "SKILL.md"
    original_skill = skill.read_text(encoding="utf-8")
    stem = "Compare the evidence for the two explanations and justify your conclusion."
    source_version_ids: list[int] = []
    for version_label in ["2.0.0", "2.0.1"]:
        skill.write_text(original_skill.replace("version: 2.0.0", f"version: {version_label}"), encoding="utf-8")
        archive = build_atqskill_archive(package_source, tmp_path / f"case-{version_label}.atqskill")
        validation = validate_atqskill(archive)
        assert validation.valid, validation.errors
        pending, _preview = create_pending_import(
            session,
            course_id=COURSE_ID,
            user_id="user-1",
            original_filename=archive.name,
            archive_bytes=archive.read_bytes(),
            result=validation,
        )
        assert pending is not None
        installed = install_pending_import(
            session, course_id=COURSE_ID, user_id="user-1", import_id=pending.id,
        )
        session.commit()
        runtime = resolve_course_question_type_runtimes(
            session, course_id=COURSE_ID, registry_ids=[installed.registry_id], mode="web_practice",
        )[0]
        source_version_ids.append(runtime.version_id)
        exams_api._upsert_generated_template(
            session,
            course_id=COURSE_ID,
            unit=None,
            question_type=runtime.type_key,
            difficulty="medium",
            stem=stem,
            answer="Reference answer",
            answer_payload=runtime.definition.reference_cases[0].question["reference_answer"],
            explanation=f"Frozen explanation for {version_label}",
            options=None,
            custom_runtime=runtime.workflow_payload(),
        )

    # Occupy a target ID so imports receive 2/3 (overlap) or 11/12 (no overlap)
    # instead of their original IDs 1/2.
    target_engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(target_engine)
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda _session: IMPORTED_COURSE_ID)
    package_path = export_module.export_course(
        session,
        course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False,
            include_knowledge_docs=False,
            include_chat_history=False,
            include_exam_history=True,
            include_profile=False,
        ),
    )
    try:
        with Session(target_engine, expire_on_commit=False) as target:
            target.add(Course(id="reserved-course", user_id="user-2", name="Existing course"))
            registry = QuestionTypeRegistry(
                id=1, course_id="reserved-course", scope="course", source="upload",
                is_system=False, type_key=runtime.type_key, display_name="Existing type",
            )
            target.add(registry)
            source_version = session.get(QuestionTypePackageVersion, source_version_ids[0])
            assert source_version is not None
            target.add(QuestionTypePackageVersion.model_validate({
                **source_version.model_dump(),
                "id": reserved_version_id,
                "registry_id": registry.id,
                "course_id": "reserved-course",
                "user_id": "user-2",
            }))
            target.commit()
            result = import_module.import_course(
                target,
                file_path=package_path,
                options=ImportOptions(new_course_name="Imported versions", rebuild_embeddings=False),
                user_id="user-2",
            )
            assert result.imported_counts["question_template"] == 2
            imported = target.exec(select(QuestionTemplate).where(
                QuestionTemplate.course_id == IMPORTED_COURSE_ID,
            ).order_by(QuestionTemplate.question_type_version_id)).all()
            assert [item.question_type_version_id for item in imported] == [
                reserved_version_id + 1, reserved_version_id + 2,
            ]
            frozen_contracts = {
                item.id: (
                    item.question_type_version_id,
                    json.loads(item.runtime_snapshot_json),
                    json.loads(item.grading_spec_json),
                )
                for item in imported
            }
            for item in imported:
                imported_runtime = resolve_question_type_version(
                    target, course_id=IMPORTED_COURSE_ID,
                    version_id=item.question_type_version_id, mode="web_practice",
                )
                regenerated = exams_api._upsert_generated_template(
                    target,
                    course_id=IMPORTED_COURSE_ID,
                    unit=None,
                    question_type=imported_runtime.type_key,
                    difficulty="medium",
                    stem=stem,
                    answer="Reference answer",
                    answer_payload=imported_runtime.definition.reference_cases[0].question["reference_answer"],
                    explanation=item.explanation,
                    options=None,
                    custom_runtime=imported_runtime.workflow_payload(),
                )
                assert regenerated.id == item.id
            target.expire_all()
            remaining = target.exec(select(QuestionTemplate).where(
                QuestionTemplate.course_id == IMPORTED_COURSE_ID,
            )).all()
            assert len(remaining) == 2
            assert {
                item.id: (
                    item.question_type_version_id,
                    json.loads(item.runtime_snapshot_json),
                    json.loads(item.grading_spec_json),
                )
                for item in remaining
            } == frozen_contracts
    finally:
        package_path.unlink(missing_ok=True)
        target_engine.dispose()


@pytest.fixture
def custom_question_course_archive(
    session: Session,
    export_import_store: _FakeStore,
    tmp_path: Path,
):
    _seed_course_graph(session)
    skill_archive = build_atqskill_archive(
        EXAMPLE_QUESTION_TYPE_ROOT / "case_analysis", tmp_path / "case.atqskill",
    )
    pending, _preview = create_pending_import(
        session, course_id=COURSE_ID, user_id="user-1",
        original_filename=skill_archive.name,
        archive_bytes=skill_archive.read_bytes(),
        result=validate_atqskill(skill_archive),
    )
    assert pending is not None
    installed = install_pending_import(
        session, course_id=COURSE_ID, user_id="user-1", import_id=pending.id,
    )
    session.commit()
    runtime = resolve_course_question_type_runtimes(
        session, course_id=COURSE_ID, registry_ids=[installed.registry_id], mode="web_practice",
    )[0]
    template = exams_api._upsert_generated_template(
        session, course_id=COURSE_ID, unit=None, question_type=runtime.type_key,
        difficulty="medium", stem="Compare the two cases and justify your conclusion.",
        answer="Reference answer", explanation="Explain the supporting evidence.", options=None,
        answer_payload=runtime.definition.reference_cases[0].question["reference_answer"],
        custom_runtime=runtime.workflow_payload(),
    )
    paper = ExamPaper(course_id=COURSE_ID, user_id="user-1", exam_mode="web_practice", status="ready", total_items=1)
    session.add(paper)
    session.flush()
    session.add(ExamPaperItem(
        exam_paper_id=paper.id, question_template_id=template.id, item_order=1,
        question_type=template.question_type, difficulty=template.difficulty,
        question_type_registry_id=template.question_type_registry_id,
        question_type_version_id=template.question_type_version_id,
        stem_snapshot=template.stem, answer_snapshot=template.answer,
        explanation_snapshot=template.explanation,
        public_payload_snapshot_json=template.public_payload_json,
        answer_schema_snapshot_json=template.answer_schema_json,
        reference_answer_snapshot_json=template.reference_answer_json,
        grading_spec_snapshot_json=template.grading_spec_json,
        runtime_snapshot_json=template.runtime_snapshot_json,
        profile_eligible=template.profile_eligible,
    ))
    session.commit()
    package_path = export_module.export_course(
        session, course_id=COURSE_ID,
        options=ExportOptions(
            include_raw_markdowns=False, include_knowledge_docs=False,
            include_chat_history=False, include_exam_history=True, include_profile=False,
        ),
    )
    try:
        yield package_path
    finally:
        package_path.unlink(missing_ok=True)


@pytest.mark.parametrize(("table_name", "broken_reference"), [
    ("question_template", "missing"),
    ("exam_paper_item", "missing"),
    ("question_template", "unknown"),
    ("exam_paper_item", "unknown"),
    ("question_template", "missing_packages"),
])
def test_course_import_rejects_unresolved_custom_question_versions(
    table_name: str,
    broken_reference: str,
    custom_question_course_archive: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broken_archive = tmp_path / "broken.atmx"
    with zipfile.ZipFile(custom_question_course_archive) as source, zipfile.ZipFile(broken_archive, "w") as target:
        for member in source.infolist():
            if broken_reference == "missing_packages" and member.filename in {
                "db/question_type_registry.json",
                "db/question_type_package_version.json",
                "db/question_type_package_asset.json",
            }:
                continue
            data = source.read(member.filename)
            if member.filename == f"db/{table_name}.json" and broken_reference != "missing_packages":
                payload = json.loads(data)
                for record in payload["records"]:
                    record["question_type_version_id"] = None if broken_reference == "missing" else 99999
                data = json.dumps(payload).encode("utf-8")
            target.writestr(member, data)
    monkeypatch.setattr(import_module, "_create_unique_course_id", lambda _session: IMPORTED_COURSE_ID)

    with pytest.raises(InvalidImportPackageError, match="题型版本|缺少题型版本"):
        import_module.import_course(
            session, file_path=broken_archive, user_id="user-2",
            options=ImportOptions(new_course_name="Broken custom version", rebuild_embeddings=False),
        )

    # A failed import must leave no partial course, bank or exam behind.
    assert session.get(Course, IMPORTED_COURSE_ID) is None
    assert session.exec(select(QuestionTemplate).where(QuestionTemplate.course_id == IMPORTED_COURSE_ID)).first() is None
    assert session.exec(select(ExamPaper).where(ExamPaper.course_id == IMPORTED_COURSE_ID)).first() is None
    assert session.get(Course, COURSE_ID) is not None


def test_custom_question_relationship_validation_is_scoped_to_course(session: Session) -> None:
    session.add_all([
        Course(id=COURSE_ID, user_id="user-1", name="Valid built-in course"),
        Course(id="unrelated-course", user_id="user-2", name="Unrelated course"),
    ])
    for course_id, question_type, version_id in [
        (COURSE_ID, "short_answer", None),
        ("unrelated-course", "custom_broken", 99999),
    ]:
        template = QuestionTemplate(
            course_id=course_id, question_type=question_type, difficulty="medium",
            stem="Explain this concept.", stem_hash=f"stem-{course_id}",
            answer="Reference answer.", explanation="Reference explanation.",
            question_type_version_id=version_id,
        )
        paper = ExamPaper(course_id=course_id, user_id="user-1", exam_mode="web_practice")
        session.add_all([template, paper])
        session.flush()
        session.add(ExamPaperItem(
            exam_paper_id=paper.id, question_template_id=template.id, item_order=1,
            question_type=question_type, question_type_version_id=version_id, difficulty="medium",
            stem_snapshot=template.stem, answer_snapshot=template.answer,
            explanation_snapshot=template.explanation,
        ))
    session.commit()

    import_module._validate_imported_question_type_package_relationships(session, course_id=COURSE_ID)
