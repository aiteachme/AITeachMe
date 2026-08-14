from __future__ import annotations

import tempfile
import json
import zipfile
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier, Event, Lock
from time import sleep
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import course_shares as course_shares_api
from app.api import deps
from app.api.deps import CurrentUserContext
from app.models import Course, CourseShare, CourseShareImport, User
from app.schemas.export_import import ExportOptions, ImportResultData
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support import course_shares as course_shares_workflow
from app.workflows.support.courses.lib import deletion as course_deletion_workflow
from app.utils.time import utcnow

TEST_COURSE_ID = "course_123456789abc"
SAFE_PNG = b"\x89PNG\r\n\x1a\npublic-image"
PRIVATE_MARKERS = (
    "private-profile-marker",
    "private-settings-marker",
    "private-learning-intent-marker",
    "private-llm-context-marker",
    "private-source-user-marker",
    "private-retrieval-marker",
)
UNPUBLISHED_KG_MARKER = "unpublished-knowledge-graph-marker"


class _MemoryShareStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.last_export_options: ExportOptions | None = None
        self.read_calls = 0

    async def write_file(self, key: str, local_path: Path) -> None:
        self.files[key] = local_path.read_bytes()

    async def read_bytes(self, key: str) -> bytes:
        self.read_calls += 1
        return self.files[key]

    async def materialize(self, key: str, temp_dir: Path) -> Path:
        target = temp_dir / Path(key).name
        target.write_bytes(self.files[key])
        return target

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)


@pytest.fixture
def course_share_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, Session, _MemoryShareStore], None, None]:
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
            CourseShare.__table__,
            CourseShareImport.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    session.add(User(id="api-user", username="api-user"))
    session.add(Course(id=TEST_COURSE_ID, user_id="api-user", name="Python 入门", description="演示课程"))
    session.commit()

    store = _MemoryShareStore()

    def fake_export_course(*args: Any, **kwargs: Any) -> Path:
        del args
        store.last_export_options = kwargs.get("options")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx")
        path = Path(tmp.name)
        tmp.close()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format_version": "1.0",
                        "course": {
                            "course_id": TEST_COURSE_ID,
                            "name": "Python 入门",
                            "user_intent": PRIVATE_MARKERS[2],
                        },
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/course.json",
                json.dumps(
                    {
                        "table": "course",
                        "count": 1,
                        "records": [
                            {
                                "id": TEST_COURSE_ID,
                                "user_id": PRIVATE_MARKERS[4],
                                "name": "Python 入门",
                                "description": "演示课程",
                                "profile_json": PRIVATE_MARKERS[0],
                                "settings_json": PRIVATE_MARKERS[1],
                                "learning_intent_text": PRIVATE_MARKERS[2],
                                "llm_context_text": PRIVATE_MARKERS[3],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/knowledge_document.json",
                json.dumps(
                    {
                        "table": "knowledge_document",
                        "count": 3,
                        "records": [
                            {
                                "id": 1,
                                "title": "变量与数据类型",
                                "summary": "Python 变量、数字、字符串和布尔值的基础。",
                                "content_markdown": (
                                    "# 变量与数据类型\n\n"
                                    "变量用于保存程序运行中的数据。\n\n"
                                    "![图示](assets/docgen/figure.png)\n\n"
                                    "[交互内容](assets/docgen/figure.html)\n\n"
                                    "![外部图片](https://example.com/assets/docgen/external-only.png)\n\n"
                                    "![自定义协议](custom://example/assets/docgen/scheme-only.png)\n\n"
                                    "![穿越路径](assets/docgen/../traversal-only.png)\n\n"
                                    "[外部查询](https://example.com/view?asset=docgen/query-only.png)"
                                ),
                                "source_file_ids": "[\"private-file-id\"]",
                                "manifest_json": PRIVATE_MARKERS[2],
                                "build_session_id": "private-build-session",
                                "chapter_index": 1,
                                "order_index": 0,
                                "is_current": True,
                                "status": "published",
                            },
                            {
                                "id": 2,
                                "title": "尚未发布的草稿",
                                "content_markdown": "![草稿图](assets/docgen/draft-only.png)",
                                "chapter_index": 2,
                                "order_index": 1,
                                "is_current": True,
                                "status": "draft",
                            },
                            {
                                "id": 3,
                                "title": "已被替换的旧版本",
                                "content_markdown": "![旧版图](assets/docgen/old-only.png)",
                                "chapter_index": 3,
                                "order_index": 2,
                                "is_current": False,
                                "status": "published",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/knowledge_unit.json",
                json.dumps(
                    {
                        "table": "knowledge_unit",
                        "count": 1,
                        "records": [
                            {
                                "id": 10,
                                "course_id": TEST_COURSE_ID,
                                "knowledge_unit_type": "concept",
                                "canonical_name": "变量",
                                "normalized_name": "变量",
                                "summary": f"{UNPUBLISHED_KG_MARKER}-summary",
                                "body": f"{UNPUBLISHED_KG_MARKER}-body",
                                "body_markdown": f"{UNPUBLISHED_KG_MARKER}-body-markdown",
                                "evidence_refs_json": "[{\"file_id\":\"private-file-id\"}]",
                                "status": "active",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/knowledge_edge.json",
                json.dumps(
                    {
                        "table": "knowledge_edge",
                        "count": 1,
                        "records": [
                            {
                                "id": 20,
                                "course_id": TEST_COURSE_ID,
                                "source_node_id": 10,
                                "target_node_id": 10,
                                "edge_type": "explains",
                                "description": f"{UNPUBLISHED_KG_MARKER}-description",
                                "evidence_refs_json": "[{\"file_id\":\"private-file-id\"}]",
                                "status": "active",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/raw_file.json",
                json.dumps(
                    {
                        "table": "raw_file",
                        "count": 1,
                        "records": [{"id": "raw-private", "markdown_content": PRIVATE_MARKERS[2]}],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/retrieval_chunk.json",
                json.dumps(
                    {
                        "table": "retrieval_chunk",
                        "count": 1,
                        "records": [{"id": 99, "content": PRIVATE_MARKERS[5]}],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr(
                "db/chat_session.json",
                json.dumps(
                    {
                        "table": "chat_session",
                        "count": 1,
                        "records": [{"id": "chat-private", "meta_json": PRIVATE_MARKERS[3]}],
                    },
                    ensure_ascii=False,
                ),
            )
            zf.writestr("share_assets/docgen/figure.png", SAFE_PNG)
            zf.writestr("share_assets/docgen/draft-only.png", SAFE_PNG)
            zf.writestr("share_assets/docgen/old-only.png", SAFE_PNG)
            zf.writestr("share_assets/docgen/external-only.png", SAFE_PNG)
            zf.writestr("share_assets/docgen/scheme-only.png", SAFE_PNG)
            zf.writestr("share_assets/traversal-only.png", SAFE_PNG)
            zf.writestr("share_assets/docgen/query-only.png", SAFE_PNG)
            zf.writestr("share_assets/docgen/figure.html", "<script>window.top.pwned = true</script>")
            zf.writestr(
                "share_assets/docgen/figure.svg",
                "<svg xmlns=\"http://www.w3.org/2000/svg\" onload=\"window.top.pwned=true\"/>",
            )
        return path

    monkeypatch.setattr(course_shares_workflow, "export_course", fake_export_course)
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
    monkeypatch: pytest.MonkeyPatch,
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, store = course_share_client

    created = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={
            "expires_in_days": 30,
            "export_options": ExportOptions(
                include_raw_files=True,
                include_chat_history=True,
                include_exam_history=True,
                include_profile=True,
            ).model_dump(),
        },
    )

    assert created.status_code == 200
    payload = created.json()["data"]
    assert payload["token"].startswith("cshr_")
    assert payload["share_path"] == f"/share/courses/{payload['token']}"
    assert payload["status"] == "active"
    assert payload["can_import"] is True
    assert payload["export_options"]["include_raw_files"] is False
    assert payload["export_options"]["include_raw_markdowns"] is False
    assert payload["export_options"]["include_chat_history"] is False
    assert payload["export_options"]["include_exam_history"] is False
    assert payload["export_options"]["include_profile"] is False
    assert payload["stats"]["knowledge_unit_count"] == 0
    assert payload["stats"]["knowledge_edge_count"] == 0
    assert len(store.files) == 1
    assert store.last_export_options is not None
    assert store.last_export_options.include_raw_files is False
    assert store.last_export_options.include_raw_markdowns is False
    assert store.last_export_options.include_chat_history is False
    assert store.last_export_options.include_exam_history is False
    assert store.last_export_options.include_profile is False

    snapshot_bytes = next(iter(store.files.values()))
    with zipfile.ZipFile(BytesIO(snapshot_bytes), "r") as archive:
        names = set(archive.namelist())
        assert "db/raw_file.json" not in names
        assert "db/retrieval_chunk.json" not in names
        assert "db/chat_session.json" not in names
        assert "share_assets/docgen/figure.html" not in names
        assert "share_assets/docgen/figure.svg" not in names
        assert "share_assets/docgen/figure.png" in names
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["extensions"]["share_snapshot_schema"] == "aiteachme.course-share.v1"
        public_course = json.loads(archive.read("db/course.json").decode("utf-8"))["records"][0]
        assert public_course["user_id"] == "shared_owner"
        assert public_course["profile_json"] == "{}"
        assert public_course["learning_intent_text"] == ""
        assert public_course["llm_context_text"] == ""
        public_doc = json.loads(archive.read("db/knowledge_document.json").decode("utf-8"))["records"][0]
        assert public_doc["source_file_ids"] == "[]"
        assert "manifest_json" not in public_doc
        public_units = json.loads(archive.read("db/knowledge_unit.json").decode("utf-8"))
        public_edges = json.loads(archive.read("db/knowledge_edge.json").decode("utf-8"))
        assert public_units["count"] == 0
        assert public_units["records"] == []
        assert public_edges["count"] == 0
        assert public_edges["records"] == []
        unpacked = b"\n".join(archive.read(name) for name in names)
        for marker in PRIVATE_MARKERS:
            assert marker.encode("utf-8") not in unpacked
        assert UNPUBLISHED_KG_MARKER.encode("utf-8") not in unpacked

    preview = client.get(f"/api/v1/course-shares/{payload['token']}")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "private, no-store, max-age=0"
    assert preview.headers["referrer-policy"] == "no-referrer"
    assert preview.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert preview.headers["x-content-type-options"] == "nosniff"
    preview_data = preview.json()["data"]
    assert preview_data["course_name"] == "Python 入门"
    assert preview_data["documents"][0]["title"] == "变量与数据类型"
    assert "变量用于保存" in preview_data["documents"][0]["excerpt"]

    document = client.get(f"/api/v1/course-shares/{payload['token']}/documents/{preview_data['documents'][0]['doc_id']}")
    assert document.status_code == 200
    assert "# 变量与数据类型" in document.json()["data"]["content_markdown"]

    asset = client.get(f"/api/v1/course-shares/{payload['token']}/assets/docgen/figure.png")
    assert asset.status_code == 200
    assert asset.content == SAFE_PNG
    assert asset.headers["content-type"].startswith("image/png")
    assert asset.headers["x-content-type-options"] == "nosniff"
    assert client.get(
        f"/api/v1/course-shares/{payload['token']}/assets/docgen/figure.html"
    ).status_code == 404

    traversal = client.get(f"/api/v1/course-shares/{payload['token']}/assets/..%2Fmanifest.json")
    assert traversal.status_code == 404
    assert store.read_calls == 2

    original_commit = session.commit

    def commit_then_lose_ack() -> None:
        original_commit()
        raise RuntimeError("injected revoke commit acknowledgement loss")

    monkeypatch.setattr(session, "commit", commit_then_lose_ack)
    revoked = client.delete(f"/api/v1/courses/{TEST_COURSE_ID}/shares/{payload['share_id']}")
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "revoked"
    assert revoked.json()["data"]["can_import"] is False
    assert store.files == {}

    assert client.get(f"/api/v1/course-shares/{payload['token']}").status_code == 410
    assert client.get(f"/api/v1/course-shares/{payload['token']}/documents/{preview_data['documents'][0]['doc_id']}").status_code == 410
    assert client.get(f"/api/v1/course-shares/{payload['token']}/assets/docgen/figure.png").status_code == 410
    assert client.post(f"/api/v1/course-shares/{payload['token']}/import", json={}).status_code == 410


def test_course_share_snapshot_only_includes_assets_from_published_current_documents(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, store = course_share_client

    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={})
    assert created.status_code == 200
    token = created.json()["data"]["token"]

    snapshot_bytes = next(iter(store.files.values()))
    with zipfile.ZipFile(BytesIO(snapshot_bytes), "r") as archive:
        names = set(archive.namelist())
        documents = json.loads(archive.read("db/knowledge_document.json").decode("utf-8"))["records"]

    assert [document["id"] for document in documents] == [1]
    assert "share_assets/docgen/figure.png" in names
    assert "share_assets/docgen/draft-only.png" not in names
    assert "share_assets/docgen/old-only.png" not in names
    assert "share_assets/docgen/external-only.png" not in names
    assert "share_assets/docgen/scheme-only.png" not in names
    assert "share_assets/traversal-only.png" not in names
    assert "share_assets/docgen/query-only.png" not in names
    assert client.get(f"/api/v1/course-shares/{token}/assets/docgen/figure.png").status_code == 200
    assert client.get(f"/api/v1/course-shares/{token}/assets/docgen/draft-only.png").status_code == 404
    assert client.get(f"/api/v1/course-shares/{token}/assets/docgen/old-only.png").status_code == 404
    assert client.get(f"/api/v1/course-shares/{token}/assets/docgen/external-only.png").status_code == 404
    assert client.get(f"/api/v1/course-shares/{token}/assets/docgen/scheme-only.png").status_code == 404
    assert client.get(f"/api/v1/course-shares/{token}/assets/traversal-only.png").status_code == 404
    assert client.get(f"/api/v1/course-shares/{token}/assets/docgen/query-only.png").status_code == 404


def test_course_share_empty_options_still_use_safe_policy(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, store = course_share_client

    created = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={"expires_in_days": 30, "export_options": {}},
    )

    assert created.status_code == 200
    assert store.last_export_options is not None
    assert store.last_export_options.include_raw_files is False
    assert store.last_export_options.include_raw_markdowns is False
    assert store.last_export_options.include_chat_history is False
    assert store.last_export_options.include_exam_history is False
    assert store.last_export_options.include_profile is False


def test_course_share_create_updates_the_single_active_link(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, store = course_share_client

    first = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={"expires_in_days": 7},
    )
    second = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={"expires_in_days": 60},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert second_data["share_id"] == first_data["share_id"]
    assert second_data["token"] == first_data["token"]
    assert len(store.files) == 1
    active = session.exec(
        select(CourseShare)
        .where(CourseShare.source_course_id == TEST_COURSE_ID)
        .where(CourseShare.status == "active")
    ).all()
    assert len(active) == 1


def test_course_share_concurrent_create_keeps_one_active_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "concurrent-create.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, CourseShare.__table__],
    )
    with Session(engine) as seed_session:
        seed_session.add(User(id="owner", username="owner"))
        seed_session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="Concurrent course"))
        seed_session.commit()

    store = _MemoryShareStore()
    start_barrier = Barrier(2)
    build_lock = Lock()
    active_builds = 0
    max_active_builds = 0

    def fake_export_course(*args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx", dir=tmp_path)
        handle.close()
        return Path(handle.name)

    def fake_build_share_snapshot(*args: Any, **kwargs: Any) -> tuple[Path, dict[str, int]]:
        nonlocal active_builds, max_active_builds
        del args, kwargs
        with build_lock:
            active_builds += 1
            max_active_builds = max(max_active_builds, active_builds)
        try:
            sleep(0.05)
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx", dir=tmp_path)
            handle.write(b"snapshot")
            handle.close()
            return Path(handle.name), {}
        finally:
            with build_lock:
                active_builds -= 1

    monkeypatch.setattr(course_shares_workflow, "export_course", fake_export_course)
    monkeypatch.setattr(course_shares_workflow, "_build_share_snapshot", fake_build_share_snapshot)
    monkeypatch.setattr(course_shares_workflow, "_validate_snapshot_bytes", lambda *args, **kwargs: None)
    monkeypatch.setattr(course_shares_workflow, "get_content_store", lambda: store)

    def create_share() -> Any:
        with Session(engine, expire_on_commit=False) as session:
            course = session.get(Course, TEST_COURSE_ID)
            assert course is not None
            start_barrier.wait(timeout=5)
            return course_shares_workflow.create_course_share(
                session,
                course=course,
                owner_user_id="owner",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_share) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]

    assert results[0].share_id == results[1].share_id
    assert results[0].token == results[1].token
    assert max_active_builds == 1
    assert len(store.files) == 1
    with Session(engine) as session:
        active = session.exec(
            select(CourseShare)
            .where(CourseShare.source_course_id == TEST_COURSE_ID)
            .where(CourseShare.status == "active")
        ).all()
        assert len(active) == 1


def test_course_share_create_and_delete_cannot_leave_an_active_orphan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "create-delete.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, CourseShare.__table__],
    )
    with Session(engine) as seed_session:
        seed_session.add(User(id="owner", username="owner"))
        seed_session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="Race course"))
        seed_session.commit()

    store = _MemoryShareStore()
    build_started = Event()
    release_build = Event()
    delete_entered = Event()
    delete_mutation_started = Event()

    def fake_export_course(*args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx", dir=tmp_path)
        handle.close()
        return Path(handle.name)

    def fake_build_share_snapshot(*args: Any, **kwargs: Any) -> tuple[Path, dict[str, int]]:
        del args, kwargs
        build_started.set()
        assert release_build.wait(timeout=5)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx", dir=tmp_path)
        handle.write(b"snapshot")
        handle.close()
        return Path(handle.name), {}

    monkeypatch.setattr(course_shares_workflow, "export_course", fake_export_course)
    monkeypatch.setattr(course_shares_workflow, "_build_share_snapshot", fake_build_share_snapshot)
    monkeypatch.setattr(course_shares_workflow, "_validate_snapshot_bytes", lambda *args, **kwargs: None)
    monkeypatch.setattr(course_shares_workflow, "get_content_store", lambda: store)
    monkeypatch.setattr(course_deletion_workflow, "get_content_store", lambda: store)
    for helper_name in (
        "_delete_profiles",
        "_delete_exam_records",
        "_delete_chat_messages",
        "_delete_knowledge_and_curriculum",
        "_delete_documents_and_chunks",
        "_delete_planner_records",
        "_delete_raw_files_and_artifacts",
    ):
        monkeypatch.setattr(course_deletion_workflow, helper_name, lambda *args, **kwargs: None)
    monkeypatch.setattr(course_deletion_workflow, "_schedule_course_external_cleanup", lambda *args, **kwargs: None)

    original_revoke = course_deletion_workflow._revoke_course_shares

    def observed_revoke(session: Session, *, course_id: str) -> list[str]:
        delete_mutation_started.set()
        return original_revoke(session, course_id=course_id)

    monkeypatch.setattr(course_deletion_workflow, "_revoke_course_shares", observed_revoke)

    def create_share() -> Any:
        with Session(engine, expire_on_commit=False) as session:
            course = session.get(Course, TEST_COURSE_ID)
            assert course is not None
            return course_shares_workflow.create_course_share(
                session,
                course=course,
                owner_user_id="owner",
            )

    def delete_course() -> None:
        with Session(engine, expire_on_commit=False) as session:
            course = session.get(Course, TEST_COURSE_ID)
            assert course is not None
            delete_entered.set()
            course_deletion_workflow.delete_course_with_all_content(
                session,
                course=course,
                counts={},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_future = executor.submit(create_share)
        assert build_started.wait(timeout=5)
        delete_future = executor.submit(delete_course)
        assert delete_entered.wait(timeout=5)
        assert not delete_mutation_started.wait(timeout=0.2)
        release_build.set()
        share_data = create_future.result(timeout=15)
        delete_future.result(timeout=15)

    with Session(engine) as session:
        share = session.get(CourseShare, share_data.share_id)
        assert session.get(Course, TEST_COURSE_ID) is None
        assert share is not None
        assert share.status == "revoked"
        assert not session.exec(select(CourseShare).where(CourseShare.status == "active")).all()
        with pytest.raises(course_shares_workflow.CourseShareUnavailableError) as exc_info:
            course_shares_workflow.preview_course_share(session, token=share_data.token)
        assert exc_info.value.status_code == 410
    assert store.files == {}


def test_course_share_create_then_revoke_finishes_revoked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "create-revoke.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, CourseShare.__table__],
    )
    now = utcnow()
    share_id = "share_create_revoke"
    token = "cshr_create_revoke"
    old_storage_key = f"shared/course_snapshots/{share_id}/old.atmx"
    with Session(engine) as seed_session:
        seed_session.add(User(id="owner", username="owner"))
        seed_session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="Race course"))
        seed_session.add(
            CourseShare(
                id=share_id,
                owner_user_id="owner",
                source_course_id=TEST_COURSE_ID,
                token=token,
                token_hash=course_shares_workflow._hash_token(token),
                storage_key=old_storage_key,
                course_name="Race course",
                status="active",
                file_size_bytes=3,
                content_sha256="old",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        seed_session.commit()

    store = _MemoryShareStore()
    store.files[old_storage_key] = b"old"
    build_started = Event()
    release_build = Event()
    revoke_entered = Event()

    def fake_export_course(*args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx", dir=tmp_path)
        handle.close()
        return Path(handle.name)

    def fake_build_share_snapshot(*args: Any, **kwargs: Any) -> tuple[Path, dict[str, int]]:
        del args, kwargs
        build_started.set()
        assert release_build.wait(timeout=5)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx", dir=tmp_path)
        handle.write(b"new snapshot")
        handle.close()
        return Path(handle.name), {}

    monkeypatch.setattr(course_shares_workflow, "export_course", fake_export_course)
    monkeypatch.setattr(course_shares_workflow, "_build_share_snapshot", fake_build_share_snapshot)
    monkeypatch.setattr(course_shares_workflow, "_validate_snapshot_bytes", lambda *args, **kwargs: None)
    monkeypatch.setattr(course_shares_workflow, "get_content_store", lambda: store)

    def update_share() -> Any:
        with Session(engine, expire_on_commit=False) as session:
            course = session.get(Course, TEST_COURSE_ID)
            assert course is not None
            return course_shares_workflow.create_course_share(
                session,
                course=course,
                owner_user_id="owner",
            )

    def revoke_share() -> Any:
        revoke_entered.set()
        with Session(engine, expire_on_commit=False) as session:
            return course_shares_workflow.revoke_course_share(
                session,
                owner_user_id="owner",
                course_id=TEST_COURSE_ID,
                share_id=share_id,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            update_future = executor.submit(update_share)
            assert build_started.wait(timeout=5)
            revoke_future = executor.submit(revoke_share)
            assert revoke_entered.wait(timeout=5)
            assert not revoke_future.done()
            release_build.set()
            updated = update_future.result(timeout=15)
            revoked = revoke_future.result(timeout=15)
    finally:
        release_build.set()

    assert updated.share_id == share_id
    assert updated.token == token
    assert revoked.status == "revoked"
    with Session(engine) as session:
        share = session.get(CourseShare, share_id)
        assert share is not None
        assert share.status == "revoked"
        assert share.revoked_at is not None
        assert not session.exec(select(CourseShare).where(CourseShare.status == "active")).all()
        with pytest.raises(course_shares_workflow.CourseShareUnavailableError) as exc_info:
            course_shares_workflow.preview_course_share(session, token=token)
        assert exc_info.value.status_code == 410
    engine.dispose()
    assert store.files == {}


def test_course_share_create_requires_authenticated_user(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, store = course_share_client
    original_override = client.app.dependency_overrides[deps.get_current_user_context]

    def override_guest_user_context() -> CurrentUserContext:
        return CurrentUserContext(
            user_id="api-user",
            email=None,
            is_local=True,
            is_authenticated=False,
            auth_source="guest_token",
        )

    client.app.dependency_overrides[deps.get_current_user_context] = override_guest_user_context
    try:
        created = client.post(
            f"/api/v1/courses/{TEST_COURSE_ID}/shares",
            json={"expires_in_days": 30},
        )
    finally:
        client.app.dependency_overrides[deps.get_current_user_context] = original_override

    assert created.status_code == 401
    assert created.json()["error_code"] == "AUTH_REQUIRED"
    assert store.files == {}
    assert session.exec(select(CourseShare)).all() == []


def test_course_share_create_commit_failure_removes_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, store = course_share_client

    def fail_commit() -> None:
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        client.post(
            f"/api/v1/courses/{TEST_COURSE_ID}/shares",
            json={"expires_in_days": 30},
        )

    assert store.files == {}
    assert session.exec(select(CourseShare)).all() == []


def test_course_share_commit_ack_loss_keeps_committed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, store = course_share_client
    original_commit = session.commit

    def commit_then_lose_ack() -> None:
        original_commit()
        raise RuntimeError("injected create commit acknowledgement loss")

    monkeypatch.setattr(session, "commit", commit_then_lose_ack)

    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={})

    assert created.status_code == 200
    data = created.json()["data"]
    share = session.get(CourseShare, data["share_id"])
    assert share is not None
    assert share.status == "active"
    assert share.storage_key in store.files
    assert client.get(f"/api/v1/course-shares/{data['token']}").status_code == 200


def test_course_share_snapshot_read_failure_is_unavailable(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, store = course_share_client
    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={"expires_in_days": 30})
    token = created.json()["data"]["token"]
    store.files.clear()

    preview = client.get(f"/api/v1/course-shares/{token}")

    assert preview.status_code == 410
    assert preview.json()["error_code"] == "COURSE_SHARE_UNAVAILABLE"


def test_course_share_snapshot_checksum_mismatch_is_unavailable(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, _session, store = course_share_client
    created = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={"expires_in_days": 30},
    )
    token = created.json()["data"]["token"]
    key = next(iter(store.files))
    tampered = bytearray(store.files[key])
    tampered[-1] ^= 0x01
    store.files[key] = bytes(tampered)

    preview = client.get(f"/api/v1/course-shares/{token}")

    assert preview.status_code == 410
    assert preview.json()["error_code"] == "COURSE_SHARE_UNAVAILABLE"


def test_course_share_snapshot_rejects_extreme_compression_ratio() -> None:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("oversized-ratio.txt", b"0" * (1024 * 1024))

    with pytest.raises(ValueError, match="compression ratio"):
        course_shares_workflow._validate_snapshot_bytes(payload.getvalue())


def test_verified_snapshot_cache_deduplicates_concurrent_loads() -> None:
    cache = course_shares_workflow._VerifiedSnapshotCache(
        ttl_seconds=60,
        max_entries=2,
        max_bytes=1024,
    )
    load_started = Event()
    release_load = Event()
    call_lock = Lock()
    calls = 0

    def loader() -> bytes:
        nonlocal calls
        with call_lock:
            calls += 1
        load_started.set()
        assert release_load.wait(timeout=2)
        return b"verified-snapshot"

    key = ("share-1", "snapshot.atmx", 17, "sha256")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cache.get_or_load, key, loader) for _ in range(8)]
        assert load_started.wait(timeout=2)
        release_load.set()
        results = [future.result(timeout=2) for future in futures]

    assert results == [b"verified-snapshot"] * 8
    assert calls == 1


def test_course_share_expired_asset_and_document_are_unavailable(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, _store = course_share_client
    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={"expires_in_days": 30})
    data = created.json()["data"]
    share = session.get(CourseShare, data["share_id"])
    assert share is not None
    share.expires_at = utcnow() - timedelta(days=1)
    session.add(share)
    session.commit()

    document = client.get(f"/api/v1/course-shares/{data['token']}/documents/1")
    asset = client.get(f"/api/v1/course-shares/{data['token']}/assets/docgen/figure.png")
    preview = client.get(f"/api/v1/course-shares/{data['token']}")

    assert document.status_code == 410
    assert asset.status_code == 410
    assert preview.status_code == 410


def test_course_share_recreate_after_expiry_issues_a_new_link(
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, store = course_share_client
    first = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={})
    assert first.status_code == 200
    first_data = first.json()["data"]
    expired_share = session.get(CourseShare, first_data["share_id"])
    assert expired_share is not None
    expired_share.expires_at = utcnow() - timedelta(days=1)
    session.add(expired_share)
    session.commit()

    assert client.get(f"/api/v1/course-shares/{first_data['token']}").status_code == 410
    session.refresh(expired_share)
    assert expired_share.status == "expired"

    second = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={})
    assert second.status_code == 200
    second_data = second.json()["data"]

    assert second_data["share_id"] != first_data["share_id"]
    assert second_data["token"] != first_data["token"]
    session.refresh(expired_share)
    replacement = session.get(CourseShare, second_data["share_id"])
    assert expired_share.status == "expired"
    assert replacement is not None
    assert replacement.status == "active"
    assert len(
        session.exec(
            select(CourseShare)
            .where(CourseShare.source_course_id == TEST_COURSE_ID)
            .where(CourseShare.status == "active")
        ).all()
    ) == 1
    assert len(store.files) == 1

    assert client.get(f"/api/v1/course-shares/{first_data['token']}").status_code == 410
    assert client.get(
        f"/api/v1/course-shares/{first_data['token']}/documents/1"
    ).status_code == 410
    assert client.get(
        f"/api/v1/course-shares/{first_data['token']}/assets/docgen/figure.png"
    ).status_code == 410
    assert client.post(f"/api/v1/course-shares/{first_data['token']}/import", json={}).status_code == 410
    assert client.get(f"/api/v1/course-shares/{second_data['token']}").status_code == 200


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
        commit: bool = True,
    ) -> ImportResultData:
        del session
        assert file_path.exists()
        assert options.new_course_name == "我的 Python 课"
        assert user_id == "api-user"
        assert commit is False
        return ImportResultData(course_id="course_imported", course_name="我的 Python 课", imported_counts={"course": 1})

    monkeypatch.setattr(course_shares_workflow, "import_course", fake_import_course)

    imported = client.post(
        f"/api/v1/course-shares/{token}/import",
        json={"new_course_name": "我的 Python 课"},
    )

    assert imported.status_code == 200
    assert imported.json()["data"]["course_id"] == "course_imported"


def test_course_share_import_commit_ack_loss_keeps_committed_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, _store = course_share_client
    created = client.post(f"/api/v1/courses/{TEST_COURSE_ID}/shares", json={})
    data = created.json()["data"]
    imported_course_id = "course_import_ack_lost"
    cleanup_calls: list[tuple[str, str]] = []

    def fake_import_course(
        session: Session,
        *,
        file_path: Path,
        options: Any,
        user_id: str,
        commit: bool = True,
    ) -> ImportResultData:
        assert file_path.exists()
        assert commit is False
        session.add(
            Course(
                id=imported_course_id,
                user_id=user_id,
                name=options.new_course_name or "课程副本",
            )
        )
        session.flush()
        return ImportResultData(
            course_id=imported_course_id,
            course_name=options.new_course_name or "课程副本",
            imported_counts={"course": 1},
        )

    monkeypatch.setattr(course_shares_workflow, "import_course", fake_import_course)
    monkeypatch.setattr(
        course_shares_workflow,
        "cleanup_imported_course_artifacts",
        lambda course_id, *, user_id: cleanup_calls.append((course_id, user_id)),
    )
    original_commit = session.commit

    def commit_then_lose_ack() -> None:
        original_commit()
        raise RuntimeError("injected import commit acknowledgement loss")

    monkeypatch.setattr(session, "commit", commit_then_lose_ack)

    imported = client.post(
        f"/api/v1/course-shares/{data['token']}/import",
        json={"new_course_name": "课程副本"},
    )
    retried = client.post(
        f"/api/v1/course-shares/{data['token']}/import",
        json={"new_course_name": "不会覆盖已导入课程"},
    )

    assert imported.status_code == 200
    assert retried.status_code == 200
    assert imported.json()["data"]["course_id"] == imported_course_id
    assert retried.json()["data"]["course_id"] == imported_course_id
    assert cleanup_calls == []
    imported_course = session.get(Course, imported_course_id)
    assert imported_course is not None
    assert imported_course.user_id == "api-user"
    receipt = session.exec(
        select(CourseShareImport)
        .where(CourseShareImport.share_id == data["share_id"])
        .where(CourseShareImport.user_id == "api-user")
    ).one()
    assert receipt.imported_course_id == imported_course_id


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


def test_course_share_import_is_idempotent_per_user(
    monkeypatch: pytest.MonkeyPatch,
    course_share_client: tuple[TestClient, Session, _MemoryShareStore],
) -> None:
    client, session, _store = course_share_client
    created = client.post(
        f"/api/v1/courses/{TEST_COURSE_ID}/shares",
        json={"expires_in_days": 30},
    )
    data = created.json()["data"]
    calls = 0

    def fake_import_course(
        session: Session,
        *,
        file_path: Path,
        options: Any,
        user_id: str,
        commit: bool = True,
    ) -> ImportResultData:
        nonlocal calls
        calls += 1
        assert file_path.exists()
        assert commit is False
        course_id = "course_imported_once"
        session.add(
            Course(
                id=course_id,
                user_id=user_id,
                name=options.new_course_name or "课程副本",
            )
        )
        session.flush()
        return ImportResultData(
            course_id=course_id,
            course_name=options.new_course_name or "课程副本",
            imported_counts={"course": 1},
        )

    monkeypatch.setattr(course_shares_workflow, "import_course", fake_import_course)

    first = client.post(
        f"/api/v1/course-shares/{data['token']}/import",
        json={"new_course_name": "课程副本"},
    )
    second = client.post(
        f"/api/v1/course-shares/{data['token']}/import",
        json={"new_course_name": "另一个名称"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["course_id"] == "course_imported_once"
    assert second.json()["data"]["course_id"] == "course_imported_once"
    assert calls == 1
    assert len(session.exec(select(CourseShareImport)).all()) == 1
    share = session.get(CourseShare, data["share_id"])
    assert share is not None
    session.refresh(share)
    assert share.import_count == 1


def test_course_share_concurrent_import_materializes_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "concurrent-import.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Course.__table__,
            CourseShare.__table__,
            CourseShareImport.__table__,
        ],
    )
    token = "cshr_concurrent_import"
    now = utcnow()
    with Session(engine) as seed_session:
        seed_session.add(User(id="owner", username="owner"))
        seed_session.add(User(id="learner", username="learner"))
        seed_session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="Shared course"))
        seed_session.add(
            CourseShare(
                id="share_concurrent_import",
                owner_user_id="owner",
                source_course_id=TEST_COURSE_ID,
                token=token,
                token_hash=course_shares_workflow._hash_token(token),
                storage_key="shared/course_snapshots/concurrent.atmx",
                course_name="Shared course",
                status="active",
                file_size_bytes=8,
                content_sha256="unused",
                expires_at=now + timedelta(days=30),
                created_at=now,
                updated_at=now,
            )
        )
        seed_session.commit()

    call_lock = Lock()
    start_barrier = Barrier(2)
    calls = 0

    def fake_import_course(
        session: Session,
        *,
        file_path: Path,
        options: Any,
        user_id: str,
        commit: bool = True,
    ) -> ImportResultData:
        nonlocal calls
        assert file_path.exists()
        assert commit is False
        with call_lock:
            calls += 1
        sleep(0.15)
        course_id = "course_concurrent_copy"
        session.add(Course(id=course_id, user_id=user_id, name=options.new_course_name or "Course copy"))
        session.flush()
        return ImportResultData(
            course_id=course_id,
            course_name=options.new_course_name or "Course copy",
            imported_counts={"course": 1},
        )

    monkeypatch.setattr(course_shares_workflow, "_load_and_verify_snapshot", lambda share: b"snapshot")
    monkeypatch.setattr(course_shares_workflow, "import_course", fake_import_course)

    def import_share() -> ImportResultData:
        with Session(engine, expire_on_commit=False) as session:
            start_barrier.wait(timeout=5)
            return course_shares_workflow.import_course_share(
                session,
                token=token,
                user_id="learner",
                new_course_name="Concurrent copy",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(import_share) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]

    assert results[0].course_id == "course_concurrent_copy"
    assert results[1].course_id == "course_concurrent_copy"
    assert calls == 1
    with Session(engine) as session:
        assert len(session.exec(select(CourseShareImport)).all()) == 1
        assert len(session.exec(select(Course).where(Course.id == "course_concurrent_copy")).all()) == 1
        share = session.get(CourseShare, "share_concurrent_import")
        assert share is not None
        assert share.import_count == 1
