from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app import main as app_main
from app.shared.infra.exceptions import AITeachMeError


def test_project_settings_file_inspection_redacts_nested_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "project-settings.yaml"
    settings_file.write_text(
        "\n".join(
            [
                "models:",
                "  primary: gpt-test",
                "credentials:",
                "  api_key: should-not-leak",
                "  nested:",
                "    refresh_token: hidden",
                "plain_list:",
                "  - safe",
                "  - password: hidden-too",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(app_main.PROJECT_SETTINGS_ENV_NAME, str(settings_file))

    info = app_main._inspect_project_settings_file()

    assert info["status"] == "loaded"
    assert info["exists"] is True
    assert info["is_file"] is True
    assert info["readable"] is True
    assert info["loaded_keys"] == ["credentials", "models", "plain_list"]
    assert info["override_payload"]["models"]["primary"] == "gpt-test"
    assert info["override_payload"]["credentials"] == "<redacted>"
    assert info["override_payload"]["plain_list"][0] == "safe"
    assert info["override_payload"]["plain_list"][1]["password"] == "<redacted>"


def test_project_settings_file_inspection_reports_missing_and_parse_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv(app_main.PROJECT_SETTINGS_ENV_NAME, str(missing))

    missing_info = app_main._inspect_project_settings_file()

    assert missing_info["status"] == "missing"
    assert missing_info["exists"] is False
    assert missing_info["readable"] is False

    broken = tmp_path / "broken.yaml"
    broken.write_text("models: [unterminated", encoding="utf-8")
    monkeypatch.setenv(app_main.PROJECT_SETTINGS_ENV_NAME, str(broken))

    broken_info = app_main._inspect_project_settings_file()

    assert broken_info["status"] == "read_or_parse_failed"
    assert broken_info["exists"] is True
    assert broken_info["readable"] is True
    assert "error" in broken_info


def test_openapi_export_on_startup_is_disabled_by_default(monkeypatch) -> None:
    scheduled: list[dict[str, object]] = []

    def fake_thread(**kwargs: object) -> SimpleNamespace:
        scheduled.append(kwargs)
        return SimpleNamespace(start=lambda: None)

    monkeypatch.delenv("EXPORT_OPENAPI_ON_STARTUP", raising=False)
    monkeypatch.setattr(app_main, "_OPENAPI_EXPORT_STARTED", False, raising=False)
    monkeypatch.setattr(app_main.threading, "Thread", fake_thread)

    app_main._maybe_export_openapi_schema(FastAPI())

    assert scheduled == []


def test_openapi_export_on_startup_schedules_once(monkeypatch) -> None:
    scheduled: list[dict[str, object]] = []

    def fake_thread(**kwargs: object) -> SimpleNamespace:
        scheduled.append(kwargs)
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setenv("EXPORT_OPENAPI_ON_STARTUP", "true")
    monkeypatch.setattr(app_main, "_OPENAPI_EXPORT_STARTED", False, raising=False)
    monkeypatch.setattr(app_main.threading, "Thread", fake_thread)

    app_main._maybe_export_openapi_schema(FastAPI())
    app_main._maybe_export_openapi_schema(FastAPI())

    assert len(scheduled) == 1
    thread_kwargs = scheduled[0]
    assert thread_kwargs["name"] == "openapi-export"
    assert thread_kwargs["daemon"] is True
    assert callable(thread_kwargs["target"])


def test_create_app_registers_core_routes_and_cors(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.test, http://localhost:5173")

    app = app_main.create_app()
    route_paths = {route.path for route in app.routes}

    assert "/api/health" in route_paths
    assert "/api/v1/courses/list" in route_paths
    assert "/api/v1/courses/{course_id}/knowledge/docs" in route_paths
    assert "/api/v1/courses/{course_id}/exams/history" in route_paths
    assert CORSMiddleware in {middleware.cls for middleware in app.user_middleware}


def test_request_middleware_sets_request_id_and_converts_unhandled_errors() -> None:
    app = FastAPI()
    app_main._register_middlewares(app)

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("explode")

    with TestClient(app, raise_server_exceptions=False) as client:
        ok_response = client.get("/ok", headers={"x-request-id": "fixed-id"})
        boom_response = client.get("/boom")

    assert ok_response.status_code == 200
    assert ok_response.headers["x-request-id"] == "fixed-id"
    assert boom_response.status_code == 500
    assert boom_response.headers["x-request-id"]
    assert boom_response.json()["error_code"] == "INTERNAL_SERVER_ERROR"


def test_exception_handlers_return_structured_kernel_payload() -> None:
    app = FastAPI()
    app_main._register_exception_handlers(app)

    @app.get("/known")
    async def known() -> None:
        raise AITeachMeError(
            detail="known failure",
            error_code="KNOWN_FAILURE",
            status_code=409,
            data={"reason": "covered"},
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/known")

    assert response.status_code == 409
    assert response.json() == {
        "code": 409,
        "error_code": "KNOWN_FAILURE",
        "message": "known failure",
        "data": {"reason": "covered"},
    }


def test_redact_for_logs_preserves_non_sensitive_values() -> None:
    payload: dict[str, Any] = {
        "apiToken": "secret",
        "public": {"name": "course", "count": 2},
        "items": [{"access_key": "secret"}, "visible"],
    }

    assert app_main._redact_for_logs(payload) == {
        "apiToken": "<redacted>",
        "public": {"name": "course", "count": 2},
        "items": [{"access_key": "<redacted>"}, "visible"],
    }
