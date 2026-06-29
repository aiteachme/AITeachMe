from __future__ import annotations

import tempfile
import json
import zipfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import course_shares as course_shares_api
from app.api import deps
from app.api.deps import CurrentUserContext
from app.models import Course, CourseShare, User
from app.schemas.export_import import ExportOptions, ExportPreviewData, ExportPreviewStats, ImportResultData
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support import course_shares as course_shares_workflow

TEST_COURSE_ID = "course_123456789abc"


class _MemoryShareStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def write_file(self, key: str, local_path: Path) -> None:
        self.files[key] = local_path.read_bytes()

    async def read_bytes(self, key: str) -> bytes:
        return self.files[key]

    async def materialize(self, key: str, temp_dir: Path) -> Path:
        target = temp_dir / Path(key).name
        target.write_bytes(self.files[key])
        return target


@pytest.fixture
def course_share_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, Session, _MemoryShareStore], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[User.__table__, Course.__table__, CourseShare.__table__])
    session = Session(engine, expire_on_commit=False)
    session.add(User(id="api-user", username="api-user"))
    session.add(Course(id=TEST_COURSE_ID, user_id="api-user", name="Python 入门", description="演示课程"))
    session.commit()

    store = _MemoryShareStore()

    def fake_export_course(*args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx")
        path = Path(tmp.name)
        tmp.close()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "db/knowledge_document.json",
                json.dumps(
                    {
                        "table": "knowledge_document",
                        "count": 1,
                        "records": [
                            {
                                "id": 1,
                                "title": "变量与数据类型",
                                "summary": "Python 变量、数字、字符串和布尔值的基础。",
                                "content_markdown": "# 变量与数据类型\n\n变量用于保存程序运行中的数据。",
                                "chapter_index": 1,
                                "order_index": 0,
                                "is_current": True,
                                "status": "published",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        return path

    def fake_preview_export(*args: Any, **kwargs: Any) -> ExportPreviewData:
        del args, kwargs
        return ExportPreviewData(
            course_id=TEST_COURSE_ID,
            course_name="Python 入门",
            estimated_size_bytes=9,
            stats=ExportPreviewStats(
                knowledge_document_count=8,
                knowledge_unit_count=24,
            ),
        )

    monkeypatch.setattr(course_shares_workflow, "export_course", fake_export_course)
    monkeypatch.setattr(course_shares_workflow, "preview_export", fake_preview_export)
    monkeypatch.setattr(course_shares_workflow, "get_content_store", lambda: store)
    monkeypatch.setattr(course_shares_api, "spawn_imported_embedding_rebuild_background", lambda *args, **kwargs: False)

    app = FastAPI()

    @app.exception_handler(AITeachMeError)
    async def aiteachme_error_handler(_request: Any, exc: AITeachMeError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "error_code": exc.error_code,
                "message": exc.detail,
                "data": exc.data,
            },
        )

    app.include_router(course_shares_api.router)

    def override_get_db() -> Generator[Session, None, None]:
        yield session

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True, is_authenticated=True, auth_source="token")

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

    with TestClient(app) as client:
        try:
            yield client, session, store
        finally:
            session.close()


def test_course_share_create_preview_and_revoke(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, store = course_share_client

    created = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={
            "expires_in_days": 30,
            "export_options": ExportOptions(include_chat_history=False, include_profile=False).model_dump(),
        },
    )

    assert created.status_code == 200
    payload = created.json()["data"]
    assert payload["token"].startswith("cshr_")
    assert payload["share_path"] == f"/share/courses/{payload['token']}"
    assert payload["status"] == "active"
    assert payload["can_import"] is True
    assert payload["stats"]["knowledge_unit_count"] == 24
    assert len(store.files) == 1

    preview = client.get(f"/api/v1/course-shares/{payload['token']}")
    assert preview.status_code == 200
    preview_data = preview.json()["data"]
    assert preview_data["course_name"] == "Python 入门"
    assert preview_data["documents"][0]["title"] == "变量与数据类型"
    assert "变量用于保存" in preview_data["documents"][0]["excerpt"]

    document = client.get(f"/api/v1/course-shares/{payload['token']}/documents/{preview_data['documents'][0]['doc_id']}")
    assert document.status_code == 200
    assert "# 变量与数据类型" in document.json()["data"]["content_markdown"]

    revoked = client.delete(f"/api/v1/courses/{TEST_COURSE_ID}/shares/{payload['share_id']}")
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "revoked"
    assert revoked.json()["data"]["can_import"] is False


def test_course_share_import_reuses_materialized_package(
    monkeypatch: pytest.MonkeyPatch,
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, _store = course_share_client
    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={"expires_in_days": 30})
    token = created.json()["data"]["token"]

    def fake_import_course(
        session: Session,
        *,
        file_path: Path,
        options: Any,
        user_id: str,
    ) -> ImportResultData:
        del session
        assert file_path.exists()
        assert options.new_course_name == "我的 Python 课"
        assert user_id == "api-user"
        return ImportResultData(course_id="course_imported", course_name="我的 Python 课", imported_counts={"course": 1})

    monkeypatch.setattr(course_shares_workflow, "import_course", fake_import_course)

    imported = client.post(
        f"/api/v1/course-shares/{token}/import",
        json={"new_course_name": "我的 Python 课"},
    )

    assert imported.status_code == 200
    assert imported.json()["data"]["course_id"] == "course_imported"


def test_course_share_import_requires_authenticated_user(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, _store = course_share_client
    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={"expires_in_days": 30})
    token = created.json()["data"]["token"]
    original_override = client.app.dependency_overrides[deps.get_current_user_context]

    def override_guest_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True, is_authenticated=False, auth_source="guest_token")

    client.app.dependency_overrides[deps.get_current_user_context] = override_guest_user_context
    try:
        imported = client.post(f"/api/v1/course-shares/{token}/import", json={})
    finally:
        client.app.dependency_overrides[deps.get_current_user_context] = original_override

    assert imported.status_code == 401
    assert imported.json()["error_code"] == "AUTH_REQUIRED"
