from __future__ import annotations

import json

import pytest

from app.shared.infra.workflow.result import err_result
from app.workflows.interact.chat import graph as chat_graph
from app.workflows.interact.chat.lib.errors import sanitize_interact_error_detail


RAW_PROVIDER_AUTH_ERROR = (
    "上游模型调用失败。litellm.AuthenticationError: AuthenticationError: "
    'OpenAIException - {"error":{"message":"Failed to retrieve token",'
    '"type":"Aihubmix_api_error","param":"sk-test-secret"}}'
)


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _extract_sse_payload(events: list[str], event_name: str) -> dict[str, object]:
    for event in events:
        lines = event.splitlines()
        if f"event: {event_name}" not in lines:
            continue
        data_line = next((line for line in lines if line.startswith("data: ")), "")
        return json.loads(data_line.removeprefix("data: "))
    raise AssertionError(f"SSE event {event_name!r} not emitted: {events!r}")


def test_sanitize_interact_error_detail_hides_provider_auth_details() -> None:
    sanitized = sanitize_interact_error_detail(RAW_PROVIDER_AUTH_ERROR)

    assert sanitized == "模型服务认证失败，当前无法生成回复。请检查模型服务密钥或稍后重试。"
    assert "Aihubmix" not in sanitized
    assert "Failed to retrieve token" not in sanitized
    assert "sk-test-secret" not in sanitized


def test_sanitize_interact_error_detail_preserves_short_user_safe_errors() -> None:
    assert sanitize_interact_error_detail("当前课程不存在。") == "当前课程不存在。"


@pytest.mark.anyio
async def test_stream_chat_workflow_sanitizes_failed_workflow_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_interact_workflow(**_kwargs):
        return err_result("interact_workflow_failed", RAW_PROVIDER_AUTH_ERROR)

    monkeypatch.setattr(chat_graph, "run_interact_workflow", fake_run_interact_workflow)

    events = [
        event
        async for event in chat_graph.stream_chat_workflow(
            request=_ConnectedRequest(),
            session=None,
            course_id="course_chat0000000",
            user_id="user-chat",
            session_id=None,
            question="hello",
        )
    ]

    payload = _extract_sse_payload(events, "error")
    assert payload["detail"] == "模型服务认证失败，当前无法生成回复。请检查模型服务密钥或稍后重试。"
    assert payload["error_code"] == "interact_workflow_failed"
    combined = "".join(events)
    assert "Aihubmix" not in combined
    assert "Failed to retrieve token" not in combined
    assert "sk-test-secret" not in combined


@pytest.mark.anyio
async def test_stream_chat_workflow_sanitizes_unhandled_runtime_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_interact_workflow(**_kwargs):
        raise RuntimeError(RAW_PROVIDER_AUTH_ERROR)

    monkeypatch.setattr(chat_graph, "run_interact_workflow", fake_run_interact_workflow)

    events = [
        event
        async for event in chat_graph.stream_chat_workflow(
            request=_ConnectedRequest(),
            session=None,
            course_id="course_chat0000000",
            user_id="user-chat",
            session_id=None,
            question="hello",
        )
    ]

    payload = _extract_sse_payload(events, "error")
    assert payload["detail"] == "模型服务认证失败，当前无法生成回复。请检查模型服务密钥或稍后重试。"
    assert payload["error_code"] == "interact_runtime_failed"
    combined = "".join(events)
    assert "Aihubmix" not in combined
    assert "Failed to retrieve token" not in combined
    assert "sk-test-secret" not in combined
