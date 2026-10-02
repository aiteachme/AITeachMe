"""HTTP contracts for the P1 course question-type package flow."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Generator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - register all tables before create_all
from app.api import deps
from app.api.deps import CurrentUserContext
from app.api.question_type_packages import router
from app.api import question_type_packages as question_type_packages_api
from app.models import Course, QuestionTypePackageVersion, QuestionTypeRegistry, User
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.question_type_packages import build_atqskill_archive, validate_atqskill


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "question-type-skills"
COURSE_ID = "course_123456789abc"
USER_ID = "question-type-api-user"


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(User(id=USER_ID, username=USER_ID))
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="题型 API 测试"))
    session.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield session

    def override_user() -> CurrentUserContext:
        return CurrentUserContext(
            user_id=USER_ID,
            email=None,
            is_local=True,
            is_authenticated=True,
        )

    app.dependency_overrides[deps.get_db] = override_db
    app.dependency_overrides[deps.get_current_user_context] = override_user
    with TestClient(app) as client:
        yield client
    session.close()


def test_upload_zip_alias_confirm_and_catalog(api_client: TestClient, tmp_path: Path) -> None:
    package = build_atqskill_archive(
        EXAMPLE_ROOT / "feynman_explanation",
        tmp_path / "feynman.atqskill",
    )

    preview_response = api_client.post(
        f"/api/v1/courses/{COURSE_ID}/question-types/imports",
        files={"file": ("feynman.zip", package.read_bytes(), "application/zip")},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()["data"]
    assert preview["valid"] is True
    assert preview["name"] == "费曼解释题"
    assert "prompts" not in preview
    assert "reference_cases" not in preview

    confirm_response = api_client.post(
        f"/api/v1/courses/{COURSE_ID}/question-types/imports/{preview['import_id']}/confirm",
        json={"set_current": True},
    )
    assert confirm_response.status_code == 200
    installed = confirm_response.json()["data"]
    assert installed["status"] == "active"
    assert installed["runtime_ready"] is True

    catalog_response = api_client.get(
        f"/api/v1/courses/{COURSE_ID}/question-types"
    )
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()["data"]
    custom = next(item for item in catalog if item["type_key"] == "custom_feynman_explanation")
    assert custom["current_version"] == "2.0.0"
    assert custom["runtime_ready"] is True
    assert custom["versions"][0]["is_current"] is True
    assert "compiled_definition" not in custom


def test_invalid_upload_returns_structured_preview(api_client: TestClient) -> None:
    response = api_client.post(
        f"/api/v1/courses/{COURSE_ID}/question-types/imports",
        files={"file": ("broken.atqskill", b"not-a-zip", "application/zip")},
    )

    assert response.status_code == 200
    preview = response.json()["data"]
    assert preview["valid"] is False
    assert preview["import_id"] is None
    assert preview["errors"][0]["code"] == "ARCHIVE_INVALID"


def test_example_package_download_is_a_valid_zip(api_client: TestClient) -> None:
    response = api_client.get(
        f"/api/v1/courses/{COURSE_ID}/question-types/examples/feynman_explanation_v1"
    )

    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert "feynman_explanation-2.0.0.atqskill" in response.headers["content-disposition"]


def test_six_examples_have_distinct_ids_and_download_installable_generic_packages(api_client, tmp_path):
    base = f"/api/v1/courses/{COURSE_ID}/question-types"
    response = api_client.get(f"{base}/examples")
    assert response.status_code == 200
    examples = response.json()["data"]
    assert len(examples) == len({item["example_id"] for item in examples}) == 6
    for example in examples:
        downloaded = api_client.get(f"{base}/examples/{example['example_id']}")
        assert downloaded.status_code == 200
        package = tmp_path / example["filename"]
        package.write_bytes(downloaded.content)
        result = validate_atqskill(package)
        assert result.valid, result.errors
        assert result.compiled_definition.template_key == "generic_text_form_v2"
        assert result.compiled_definition.package_key == example["example_id"]
        assert api_client.get(f"{base}/examples/{example['template_key']}").content == downloaded.content
        legacy_id = next(key for key, value in question_type_packages_api._LEGACY_EXAMPLE_IDS.items() if value == example["example_id"])
        assert api_client.get(f"{base}/examples/{legacy_id}").content == downloaded.content
        preview = api_client.post(f"{base}/imports", files={"file": (package.name, downloaded.content, "application/zip")}).json()["data"]
        assert preview["valid"] and preview["runtime_ready"]
        installed = api_client.post(f"{base}/imports/{preview['import_id']}/confirm", json={"set_current": True})
        assert installed.status_code == 200
        assert installed.json()["data"]["status"] == "active"


def test_question_type_asset_endpoint_rejects_unsafe_stored_mime(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        question_type_packages_api,
        "get_question_type_asset",
        lambda *_args, **_kwargs: (
            SimpleNamespace(media_type="text/html"),
            b"<script>alert(1)</script>",
        ),
    )

    with pytest.raises(AITeachMeError) as error:
        api_client.get(f"/api/v1/courses/{COURSE_ID}/question-types/assets/1")

    assert error.value.status_code == 409
    assert error.value.error_code == "QUESTION_TYPE_ASSET_UNSAFE"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def transactional_api(tmp_path: Path):
    """Use separate connections, real commits, and the production SQLite FK policy."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'question-types.db'}",
        connect_args={"check_same_thread": False, "timeout": 0.1},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=USER_ID, username=USER_ID))
        session.commit()
        session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Concurrent mutations"))
        session.commit()

    app = FastAPI()
    app.include_router(router)

    async def independent_db():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                # Production commits in dependency cleanup, which can yield to
                # another request. Make that transaction boundary deterministic.
                await asyncio.sleep(0)
                session.commit()
            except Exception:
                session.rollback()
                raise

    async def current_user():
        return CurrentUserContext(user_id=USER_ID, email=None, is_local=True, is_authenticated=True)

    @app.exception_handler(AITeachMeError)
    async def expected_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={"error_code": error.error_code})

    app.dependency_overrides[deps.get_db] = independent_db
    app.dependency_overrides[deps.get_current_user_context] = current_user
    try:
        yield SimpleNamespace(app=app, engine=engine)
    finally:
        engine.dispose()


async def _preview_version(client, tmp_path, *, version="2.0.0", unavailable=False):
    source = tmp_path / f"case-{version}"
    shutil.copytree(EXAMPLE_ROOT / "case_analysis", source)
    skill = source / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("version: 2.0.0", f"version: {version}"), encoding="utf-8")
    if unavailable:
        bindings = source / "tools" / "bindings.json"
        payload = json.loads(bindings.read_text(encoding="utf-8"))
        payload["tools"].append({"id": "math_equivalence_v1", "required": True})
        bindings.write_text(json.dumps(payload), encoding="utf-8")
    archive = build_atqskill_archive(source, tmp_path / f"case-{version}.atqskill")
    response = await client.post(
        f"/api/v1/courses/{COURSE_ID}/question-types/imports",
        files={"file": (archive.name, archive.read_bytes(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert preview["valid"], preview
    return preview["import_id"]


async def _confirm_version(client, import_id, *, set_current=True):
    return await client.post(
        f"/api/v1/courses/{COURSE_ID}/question-types/imports/{import_id}/confirm",
        json={"set_current": set_current},
    )


@pytest.mark.anyio
async def test_concurrent_confirm_commits_before_releasing_course_lock(transactional_api, tmp_path):
    transport = httpx.ASGITransport(app=transactional_api.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        import_id = await _preview_version(client, tmp_path)
        responses = await asyncio.gather(*[_confirm_version(client, import_id) for _ in range(2)])
    assert [response.status_code for response in responses] == [200, 200]
    results = [response.json()["data"] for response in responses]
    assert len({result["version_id"] for result in results}) == 1
    assert sorted(result["already_installed"] for result in results) == [False, True]
    with Session(transactional_api.engine) as session:
        versions = session.exec(select(QuestionTypePackageVersion)).all()
        assert len(versions) == 1 and versions[0].is_current
        assert versions[0].id == results[0]["version_id"]


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["status", "version"])
async def test_concurrent_patch_persists_one_current_version(transactional_api, tmp_path, operation):
    transport = httpx.ASGITransport(app=transactional_api.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        installed = []
        for version in ["2.0.0", "2.0.1"]:
            response = await _confirm_version(client, await _preview_version(client, tmp_path, version=version))
            assert response.status_code == 200, response.text
            installed.append(response.json()["data"])
        body = {"status": "inactive"} if operation == "status" else {"current_version_id": installed[0]["version_id"]}
        path = f"/api/v1/courses/{COURSE_ID}/question-types/{installed[0]['registry_id']}"
        responses = await asyncio.gather(*[client.patch(path, json=body) for _ in range(2)])
    assert [response.status_code for response in responses] == [200, 200]
    expected_current = installed[1 if operation == "status" else 0]["version_id"]
    expected_status = "inactive" if operation == "status" else "active"
    assert all(response.json()["data"]["current_version_id"] == expected_current for response in responses)
    with Session(transactional_api.engine) as session:
        versions = session.exec(select(QuestionTypePackageVersion)).all()
        assert [version.id for version in versions if version.is_current] == [expected_current]
        registry = session.get(QuestionTypeRegistry, installed[0]["registry_id"])
        assert registry.status == expected_status
        assert registry.is_active == (expected_status == "active")


@pytest.mark.anyio
async def test_failed_version_activation_rolls_back_before_next_mutation(transactional_api, tmp_path):
    transport = httpx.ASGITransport(app=transactional_api.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        original = await _confirm_version(client, await _preview_version(client, tmp_path))
        assert original.status_code == 200, original.text
        original = original.json()["data"]
        pending = await _preview_version(client, tmp_path, version="2.0.1", unavailable=True)
        unavailable = await _confirm_version(client, pending, set_current=False)
        assert unavailable.status_code == 200, unavailable.text
        unavailable = unavailable.json()["data"]
        path = f"/api/v1/courses/{COURSE_ID}/question-types/{original['registry_id']}"
        failed = await client.patch(path, json={"current_version_id": unavailable["version_id"], "status": "active"})
        assert failed.status_code == 409, failed.text
        assert failed.json()["error_code"] == "QUESTION_TYPE_RUNTIME_UNAVAILABLE"
        with Session(transactional_api.engine) as session:
            versions = session.exec(select(QuestionTypePackageVersion)).all()
            assert [version.id for version in versions if version.is_current] == [original["version_id"]]
            registry = session.get(QuestionTypeRegistry, original["registry_id"])
            assert registry.status == "active" and registry.is_active
        retry = await client.patch(path, json={"current_version_id": unavailable["version_id"], "status": "inactive"})
        assert retry.status_code == 200, retry.text
    with Session(transactional_api.engine) as session:
        versions = session.exec(select(QuestionTypePackageVersion)).all()
        assert [version.id for version in versions if version.is_current] == [unavailable["version_id"]]
        registry = session.get(QuestionTypeRegistry, original["registry_id"])
        assert registry.status == "inactive" and not registry.is_active
