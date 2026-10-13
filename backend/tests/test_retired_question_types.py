"""Removed custom-type requests and course packages cannot be reintroduced."""

import json
import zipfile

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import exams as api
from app.models import Course, User
from app.schemas.exams import (
    ExamGenerateRequest, ExamSubmitAnswerItem,
    MasteryDrillPrepareRequest, QuestionTemplateGradeRequest,
)
from app.schemas.export_import import ImportOptions
from app.shared.infra.exceptions import InvalidImportPackageError
from app.workflows.support.export_import import imports


COURSE_ID = "course_retired00000"
USER_ID = "retired-test-user"


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(User(id=USER_ID, username=USER_ID))
        db.add(Course(id=COURSE_ID, user_id=USER_ID, name="历史课程"))
        db.commit()
        yield db
    engine.dispose()


@pytest.mark.parametrize("schema,payload", [
    (ExamGenerateRequest, {"exam_mode": "web_practice", "question_types": ["custom_test"]}),
    (ExamGenerateRequest, {"exam_mode": "paper_exam", "question_type_registry_ids": [3]}),
    (ExamGenerateRequest, {"exam_mode": "web_practice", "question_type_selections": [{"registry_id": 3}]}),
    (MasteryDrillPrepareRequest, {"num_questions": 1, "question_types": ["custom_test"]}),
    (MasteryDrillPrepareRequest, {"num_questions": 1, "question_type_selections": [{"registry_id": 3}]}),
    (QuestionTemplateGradeRequest, {"answer": "text", "answer_payload": {"answer": "text"}}),
    (ExamSubmitAnswerItem, {"item_order": 1, "answer": "text", "answer_payload": {"answer": "text"}}),
])
def test_removed_request_fields_are_rejected_instead_of_falling_back_to_auto(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_removed_routes_are_absent():
    from app.main import app
    assert not any("/question-types" in path and "/exams/" not in path for path in app.openapi()["paths"])


@pytest.mark.parametrize("table,record", [
    ("question_type_registry", {"type_key": "custom_test", "is_active": False}),
    ("question_template", {"question_type": "short_answer", "question_type_version_id": 1}),
    ("question_type_package_version", {"id": 1}),
    ("question_type_package_asset", {"id": 1}),
    ("question_type_package_import", {"id": "old-upload"}),
    ("exam_paper", {"config_snapshot_json": '{"question_type_runtimes":[{"type_key":"custom_test"}]}'}),
])
def test_course_import_cannot_reinstall_custom_types(table, record):
    with pytest.raises(InvalidImportPackageError, match="自定义题型功能已移除"):
        imports._validate_imported_question_types(table, [record])


def test_custom_course_import_rolls_back_course_rows(session, tmp_path, monkeypatch):
    archive = tmp_path / "retired.atmx"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"course": {"course_id": "old", "name": "旧课程"}}))
        zf.writestr("db/course.json", json.dumps({"records": [{"id": "old", "user_id": "local", "name": "旧课程"}]}))
        zf.writestr("db/question_type_registry.json", json.dumps({"records": [{"id": 1, "type_key": "custom_test", "is_active": True}]}))
    monkeypatch.setattr(imports, "_create_unique_course_id", lambda _: "course_rejected00000")
    with pytest.raises(InvalidImportPackageError, match="自定义题型功能已移除"):
        imports.import_course(session, file_path=archive, options=ImportOptions(rebuild_embeddings=False), user_id=USER_ID)
    assert [course.id for course in session.exec(select(Course)).all()] == [COURSE_ID]


@pytest.mark.parametrize("table", ["question_type_package_version", "question_type_package_asset", "question_type_package_import"])
def test_removed_package_table_alone_is_not_silently_ignored(session, tmp_path, table):
    archive = tmp_path / "old-package.atmx"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"course": {"course_id": "old", "name": "旧课程"}}))
        zf.writestr(f"db/{table}.json", json.dumps({"records": [{"id": 1}]}))
    with pytest.raises(InvalidImportPackageError, match="自定义题型功能已移除"):
        imports.import_course(session, file_path=archive, options=ImportOptions(rebuild_embeddings=False), user_id=USER_ID)
    assert [course.id for course in session.exec(select(Course)).all()] == [COURSE_ID]
