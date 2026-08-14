from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.infra import logger as logging_support


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "/api/v1/course-shares/cshr_alpha-123_AB",
            "/api/v1/course-shares/:shareToken",
        ),
        (
            "/api/v1/course-shares/cshr_alpha-123_AB/documents/doc-1",
            "/api/v1/course-shares/:shareToken/documents/doc-1",
        ),
        (
            "/api/v1/course-shares/cshr_alpha-123_AB/assets/figures/demo.svg?download=1",
            "/api/v1/course-shares/:shareToken/assets/figures/demo.svg?download=1",
        ),
        (
            "/api/v1/course-shares/cshr_path-token/import?source=cshr_query-token&next=/share/courses/cshr_page-token",
            "/api/v1/course-shares/:shareToken/import?source=:shareToken&next=/share/courses/:shareToken",
        ),
    ],
)
def test_redact_course_share_tokens_preserves_route_structure(value: str, expected: str) -> None:
    redacted = logging_support.redact_course_share_tokens(value)

    assert redacted == expected
    assert "cshr_" not in redacted.lower()


def test_structured_log_processor_redacts_share_tokens_in_nested_values() -> None:
    event = {
        "path": "/api/v1/course-shares/cshr_path-secret/assets/demo.html",
        "context": {
            "url": "https://example.test/share/courses/cshr_page-secret?copy=cshr_query-secret",
        },
    }

    redacted = logging_support._redact_event_dict(logging.getLogger("test"), "info", event)

    assert redacted["path"] == "/api/v1/course-shares/:shareToken/assets/demo.html"
    assert redacted["context"]["url"] == (
        "https://example.test/share/courses/:shareToken?copy=:shareToken"
    )
    assert "cshr_" not in str(redacted).lower()


def test_structured_log_processor_redacts_formatted_exception_text() -> None:
    try:
        raise RuntimeError("failed for cshr_exception-secret")
    except RuntimeError:
        event = logging_support.structlog.processors.format_exc_info(
            logging.getLogger("test"),
            "error",
            {"event": "failed", "exc_info": True},
        )

    redacted = logging_support._redact_event_dict(
        logging.getLogger("test"),
        "error",
        event,
    )

    assert "cshr_" not in str(redacted).lower()
    assert ":shareToken" in str(redacted)


def test_request_and_exception_paths_are_redacted_before_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as app_main

    bound_contexts: list[dict[str, object]] = []
    exception_events: list[dict[str, object]] = []
    access_logger = SimpleNamespace(
        debug=lambda *_args, **_kwargs: None,
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        exception=lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(app_main, "bind_logging_context", lambda **values: bound_contexts.append(values))
    monkeypatch.setattr(app_main.structlog, "get_logger", lambda *_args, **_kwargs: access_logger)
    monkeypatch.setattr(
        app_main,
        "logger",
        SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            exception=lambda event, **values: exception_events.append({"event": event, **values}),
        ),
    )

    middleware_app = FastAPI()
    app_main._register_middlewares(middleware_app)

    @middleware_app.get("/api/v1/course-shares/{token}/documents/{doc_id}")
    async def read_share_document(token: str, doc_id: str) -> dict[str, str]:
        del token, doc_id
        return {"status": "ok"}

    with TestClient(middleware_app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/course-shares/cshr_request-secret/documents/doc-1",
            params={"copy": "cshr_query-secret"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert any(
        item.get("path") == "/api/v1/course-shares/:shareToken/documents/doc-1"
        for item in bound_contexts
    )

    exception_app = FastAPI()
    app_main._register_exception_handlers(exception_app)

    @exception_app.get("/api/v1/course-shares/{token}/documents/{doc_id}")
    async def fail_share_request(token: str, doc_id: str) -> None:
        del token, doc_id
        raise RuntimeError("explode")

    with TestClient(exception_app, raise_server_exceptions=False) as client:
        error_response = client.get(
            "/api/v1/course-shares/cshr_exception-secret/documents/doc-1",
        )

    assert error_response.status_code == 500
    assert error_response.headers["cache-control"] == "private, no-store, max-age=0"
    assert error_response.headers["x-content-type-options"] == "nosniff"
    assert exception_events == [
        {
            "event": "unhandled_error",
            "path": "/api/v1/course-shares/:shareToken/documents/doc-1",
        }
    ]
    assert "cshr_" not in str(bound_contexts).lower()
    assert "cshr_" not in str(exception_events).lower()


def test_nginx_access_log_uses_redacted_share_uri_and_referer() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_paths = (
        repo_root / "infra" / "deployment" / "nginx" / "default.conf",
        repo_root / "infra" / "deployment" / "nginx" / "default.conf.template",
    )

    for config_path in config_paths:
        config = config_path.read_text(encoding="utf-8")
        assert "map $uri $aiteachme_safe_request_uri" in config
        assert "~*cshr_[^/?]+.*cshr_ /:redacted;" in config
        assert "/api/v1/course-shares/:shareToken$share_api_suffix" in config
        assert "/share/courses/:shareToken$share_page_suffix" in config
        assert "~*cshr_ /:redacted;" in config
        assert "map $http_referer $aiteachme_safe_referer" in config
        assert '~*cshr_ "-";' in config
        assert "map $http_user_agent $aiteachme_safe_user_agent" in config
        assert "log_format aiteachme_safe" in config
        assert '"$request_method $aiteachme_safe_request_uri $server_protocol"' in config
        assert '"$aiteachme_safe_referer"' in config
        assert '"$aiteachme_safe_user_agent"' in config
        assert "access_log /var/log/nginx/access.log aiteachme_safe;" in config
