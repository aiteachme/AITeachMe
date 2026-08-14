from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from app.api import system as system_api
from app.api.deps import CurrentUserContext
from app.schemas.system import FeedbackRequest
from app.shared.infra.exceptions import AITeachMeError


_USER = CurrentUserContext(
    user_id="feedback-user-1",
    email="learner@example.com",
    is_local=False,
    is_authenticated=True,
)


def _patch_feedback_env(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, str],
) -> None:
    monkeypatch.setattr(
        system_api,
        "get_env",
        lambda name, default=None: values.get(name, default),
    )


def _patch_http_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    original_client = system_api.httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def build_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(system_api.httpx, "AsyncClient", build_client)


def _submit_feedback() -> object:
    return asyncio.run(
        system_api.submit_feedback(
            payload=FeedbackRequest(content="页面上的保存按钮没有反应。"),
            user=_USER,
        )
    )


def _submit_feedback_with_image(image: str) -> object:
    return asyncio.run(
        system_api.submit_feedback(
            payload=FeedbackRequest(
                content="页面上的保存按钮没有反应。",
                images=[image],
            ),
            user=_USER,
        )
    )


def test_feedback_rejects_cloud_guest_before_external_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = CurrentUserContext(
        user_id="feedback-guest-1",
        email=None,
        is_local=False,
        is_authenticated=False,
    )
    _patch_feedback_env(
        monkeypatch,
        {"FEISHU_WEBHOOK_URL": "https://feedback.example.test/webhook"},
    )

    with pytest.raises(AITeachMeError) as exc_info:
        asyncio.run(
            system_api.submit_feedback(
                payload=FeedbackRequest(content="访客反馈"),
                user=guest,
            )
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.error_code == "FEEDBACK_AUTHENTICATION_REQUIRED"


def test_feedback_rejects_missing_webhook_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_feedback_env(monkeypatch, {})

    with pytest.raises(AITeachMeError) as exc_info:
        _submit_feedback()

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "FEEDBACK_DELIVERY_NOT_CONFIGURED"


def test_feedback_returns_success_only_after_webhook_accepts_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_feedback_env(
        monkeypatch,
        {"FEISHU_WEBHOOK_URL": "https://feedback.example.test/webhook"},
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    _patch_http_transport(monkeypatch, handler)

    response = _submit_feedback()

    assert response.data is True
    assert len(requests) == 1
    assert requests[0].url == httpx.URL("https://feedback.example.test/webhook")


@pytest.mark.parametrize(
    ("status_code", "response_payload"),
    [
        (502, {"code": 0}),
        (200, {"code": 19001, "msg": "invalid webhook"}),
    ],
)
def test_feedback_rejects_unsuccessful_webhook_response(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    response_payload: dict[str, object],
) -> None:
    _patch_feedback_env(
        monkeypatch,
        {"FEISHU_WEBHOOK_URL": "https://feedback.example.test/webhook"},
    )
    _patch_http_transport(
        monkeypatch,
        lambda _request: httpx.Response(status_code, json=response_payload),
    )

    with pytest.raises(AITeachMeError) as exc_info:
        _submit_feedback()

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "FEEDBACK_DELIVERY_REJECTED"


def test_feedback_reports_network_failure_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_feedback_env(
        monkeypatch,
        {"FEISHU_WEBHOOK_URL": "https://feedback.example.test/webhook"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_http_transport(monkeypatch, handler)

    with pytest.raises(AITeachMeError) as exc_info:
        _submit_feedback()

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "FEEDBACK_DELIVERY_UNAVAILABLE"


def test_feedback_falls_back_to_text_when_image_cannot_be_uploaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_feedback_env(
        monkeypatch,
        {
            "FEISHU_WEBHOOK_URL": "https://feedback.example.test/webhook",
            "FEISHU_APP_ID": "app-id",
            "FEISHU_APP_SECRET": "app-secret",
        },
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "tenant-token"},
            )
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    _patch_http_transport(monkeypatch, handler)

    response = _submit_feedback_with_image("data:image/png;base64,not-valid-base64")

    assert response.data is True
    assert [request.url.path for request in requests] == [
        "/open-apis/auth/v3/tenant_access_token/internal",
        "/webhook",
    ]
    assert b'"msg_type":"text"' in requests[-1].content
