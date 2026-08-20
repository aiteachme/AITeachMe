from __future__ import annotations

import io
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import chats as chats_api
from app.api import deps
from app.api import export_import as export_import_api
from app.api import user_files as user_files_api
from app.api.deps import CurrentUserContext
from app.models import ChatMessage, ChatSession, IngestStatus, RawFile, TaskStatus
from app.repositories.chats_repo import create_chat_message
from app.schemas.export_import import CoursePackageItem, ImportResultData
from app.utils.course import GLOBAL_COURSE


@pytest.fixture
def chat_api_client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[ChatSession.__table__, ChatMessage.__table__],
    )
    session = Session(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(chats_api.global_router)

    def override_get_db() -> Generator[Session, None, None]:
        yield session

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True)

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context
    with TestClient(app) as client:
        try:
            yield client, session
        finally:
            session.close()


def test_global_chat_session_api_preserves_session_when_clearing_messages(
    chat_api_client: tuple[TestClient, Session],
) -> None:
    client, session = chat_api_client
    create_response = client.post(
        "/api/v1/chats/sessions/create",
        json={"title": "API Session", "source": "quick_chat"},
    )

    assert create_response.status_code == 200
    created_payload = create_response.json()
    assert created_payload["data"]["session"]["title"] == "API Session"
    session_id = created_payload["data"]["session"]["id"]

    create_chat_message(
        session,
        course_id=GLOBAL_COURSE,
        session_id=session_id,
        role="user",
        content="delete me",
        user_id="api-user",
    )
    create_chat_message(
        session,
        course_id=GLOBAL_COURSE,
        session_id=session_id,
        role="assistant",
        content="delete me too",
        user_id="api-user",
    )

    list_before = client.post("/api/v1/chats/list", json={"session_id": session_id})
    clear_response = client.post("/api/v1/chats/clear", json={"session_id": session_id})
    sessions_after = client.post("/api/v1/chats/sessions/list", json={})
    list_after = client.post("/api/v1/chats/list", json={"session_id": session_id})

    assert list_before.status_code == 200
    assert [item["content"] for item in list_before.json()["data"]["items"]] == [
        "delete me too",
        "delete me",
    ]
    assert clear_response.status_code == 200
    assert clear_response.json()["data"] == {"cleared": True, "deleted_count": 2}
    assert sessions_after.status_code == 200
    assert sessions_after.json()["data"]["total"] == 1
    assert sessions_after.json()["data"]["items"][0]["message_count"] == 0
    assert list_after.status_code == 200
    assert list_after.json()["data"]["items"] == []


def test_demo_courses_api_sets_no_store_headers_and_catalog_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(export_import_api.router)

    monkeypatch.setattr(
        export_import_api,
        "list_available_courses",
        lambda: [
            CoursePackageItem(
                filename="course-one",
                course_name="Course One",
                file_size_bytes=10,
                stats={"chapters": 2},
            ),
            CoursePackageItem(
                filename="course-two",
                course_name="Course Two",
                file_size_bytes=20,
                stats={"chapters": 3},
            ),
        ],
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/demo-courses")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert response.headers["X-Demo-Courses-Count"] == "2"
    assert response.headers["X-Demo-Courses-Catalog"].endswith("/catalog/v1/index.json")
    assert response.json()["data"] == [
        {
            "filename": "course-one",
            "course_name": "Course One",
            "file_size_bytes": 10,
            "exported_at": None,
            "stats": {"chapters": 2},
        },
        {
            "filename": "course-two",
            "course_name": "Course Two",
            "file_size_bytes": 20,
            "exported_at": None,
            "stats": {"chapters": 3},
        },
    ]


def test_import_course_upload_accepts_atmx_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(export_import_api.router)

    def override_get_db() -> Generator[object, None, None]:
        yield object()

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True)

    def fake_import_course(
        session: object,
        *,
        file_path: Any,
        options: Any,
        user_id: str,
    ) -> ImportResultData:
        del session
        assert str(file_path).endswith(".atmx")
        assert getattr(options, "new_course_name", None) == "导入测试"
        assert user_id == "api-user"
        return ImportResultData(
            course_id="course_import_api",
            course_name="导入测试",
            imported_counts={"course": 1},
            warnings=[],
        )

    monkeypatch.setattr(export_import_api, "import_course", fake_import_course)
    monkeypatch.setattr(
        export_import_api,
        "spawn_imported_embedding_rebuild_background",
        lambda *args, **kwargs: False,
    )
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/courses/import",
            files={"file": ("课程.atmx", io.BytesIO(b"fake"), "application/octet-stream")},
            data={"new_course_name": "导入测试"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["course_id"] == "course_import_api"


def test_user_file_detail_returns_single_file_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(user_files_api.router)
    raw_file = RawFile(
        id="file_api_detail",
        user_id="api-user",
        filename="线性代数.pdf",
        filetype="pdf",
        file_path="users/api-user/files/file_api_detail/source.pdf",
        markdown_path="users/api-user/files/file_api_detail/markdown.md",
        asset_dir="users/api-user/files/file_api_detail/assets",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
    )

    def override_get_db() -> Generator[object, None, None]:
        yield object()

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True)

    async def resolve_markdown(_raw_file: RawFile) -> str:
        return "# 线性代数\n\n矩阵与向量"

    monkeypatch.setattr(user_files_api, "get_user_file_or_raise", lambda *_args, **_kwargs: raw_file)
    monkeypatch.setattr(user_files_api, "resolve_file_markdown_content", resolve_markdown)
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

    with TestClient(app) as client:
        response = client.get("/api/v1/files/file_api_detail")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == "file_api_detail"
    assert response.json()["data"]["markdown_content"].startswith("# 线性代数")
    assert response.json()["data"]["asset_base_url"] == "/api/v1/files/assets/file_api_detail/"


def test_user_file_asset_falls_back_to_flattened_parser_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(user_files_api.router)
    raw_file = RawFile(
        id="file_api_asset",
        user_id="api-user",
        filename="paper.pdf",
        filetype="pdf",
        file_path="users/api-user/files/file_api_asset/source.pdf",
        asset_dir="users/api-user/files/file_api_asset/assets",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
    )
    requested_keys: list[str] = []

    class FakeContentStore:
        async def read_bytes(self, storage_key: str) -> bytes:
            requested_keys.append(storage_key)
            if storage_key.endswith("/page 1.png") and "/images/" not in storage_key:
                return b"png-data"
            raise FileNotFoundError(storage_key)

    def override_get_db() -> Generator[object, None, None]:
        yield object()

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True)

    monkeypatch.setattr(user_files_api, "get_raw_file_by_id_for_user", lambda *_args, **_kwargs: raw_file)
    monkeypatch.setattr(user_files_api, "get_content_store", lambda: FakeContentStore())
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

    with TestClient(app) as client:
        response = client.get("/api/v1/files/assets/file_api_asset/images/page%201.png")

    assert response.status_code == 200
    assert response.content == b"png-data"
    assert response.headers["content-type"] == "image/png"
    assert requested_keys == [
        "users/api-user/files/file_api_asset/assets/images/page 1.png",
        "users/api-user/files/file_api_asset/assets/page 1.png",
    ]


def test_user_file_detail_can_return_metadata_without_loading_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(user_files_api.router)
    raw_file = RawFile(
        id="file_api_metadata",
        user_id="api-user",
        filename="large.pdf",
        filetype="pdf",
        file_path="users/api-user/files/file_api_metadata/source.pdf",
        markdown_path="users/api-user/files/file_api_metadata/markdown.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
    )
    requested_include_values: list[bool] = []

    def override_get_db() -> Generator[object, None, None]:
        yield object()

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True)

    def get_file(*_args, **kwargs):
        requested_include_values.append(bool(kwargs.get("include_markdown_content")))
        return raw_file

    async def unexpected_resolve(_raw_file: RawFile) -> str:
        pytest.fail("metadata-only detail must not load the full Markdown")

    monkeypatch.setattr(user_files_api, "get_user_file_or_raise", get_file)
    monkeypatch.setattr(user_files_api, "resolve_file_markdown_content", unexpected_resolve)
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

    with TestClient(app) as client:
        response = client.get("/api/v1/files/file_api_metadata?include_markdown=false")

    assert response.status_code == 200
    assert response.json()["data"]["markdown_content"] == ""
    assert response.json()["data"]["markdown_ready"] is True
    assert requested_include_values == [False]


def test_user_file_markdown_is_returned_in_character_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(user_files_api.router)
    markdown = "第一段。\n\n" + ("正文" * 3_000)
    raw_file = RawFile(
        id="file_api_chunk",
        user_id="api-user",
        filename="large.pdf",
        filetype="pdf",
        file_path="users/api-user/files/file_api_chunk/source.pdf",
        markdown_path="users/api-user/files/file_api_chunk/markdown.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
    )

    def override_get_db() -> Generator[object, None, None]:
        yield object()

    def override_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(user_id="api-user", email=None, is_local=True)

    monkeypatch.setattr(user_files_api, "get_user_file_or_raise", lambda *_args, **_kwargs: raw_file)
    monkeypatch.setattr(
        user_files_api,
        "get_raw_file_markdown_chunk_for_user",
        lambda *_args, **kwargs: (
            markdown[kwargs["offset"] : kwargs["offset"] + kwargs["limit"]],
            len(markdown),
        ),
    )
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

    with TestClient(app) as client:
        first = client.get("/api/v1/files/file_api_chunk/markdown?offset=0&limit=4096")
        second = client.get("/api/v1/files/file_api_chunk/markdown?offset=4096&limit=4096")

    assert first.status_code == 200
    assert first.json()["data"]["content"] == markdown[:4096]
    assert first.json()["data"]["next_offset"] == 4096
    assert first.json()["data"]["done"] is False
    assert second.status_code == 200
    assert second.json()["data"]["content"] == markdown[4096:]
    assert second.json()["data"]["done"] is True
