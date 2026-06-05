from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timezone

import httpx

from app.shared.infra.analytics import posthog


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


def test_capture_posthog_event_retries_once_and_ignores_proxy_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("POSTHOG_ENABLED", "true")
    monkeypatch.setenv("POSTHOG_TOKEN", "phc_test")
    monkeypatch.setenv("POSTHOG_HOST", "https://posthog.test")
    monkeypatch.setenv("POSTHOG_TIMEOUT_S", "0.5")
    monkeypatch.setenv("POSTHOG_RETRY_COUNT", "1")
    monkeypatch.setattr(posthog.time, "sleep", lambda _seconds: None)

    def fake_post(url, *, json, timeout, trust_env):
        calls.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
                "trust_env": trust_env,
            }
        )
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow handshake")
        return _Response()

    monkeypatch.setattr(posthog.httpx, "post", fake_post)

    assert posthog.capture_posthog_event(
        "knowledge_build_started",
        distinct_id="user_a",
        properties={"analytics_source": "backend"},
    )

    assert len(calls) == 2
    assert calls[0]["trust_env"] is False
    assert calls[1]["trust_env"] is False
    assert calls[0]["timeout"] == 0.5
    assert calls[0]["url"] == "https://posthog.test/capture/"


def test_capture_posthog_event_sends_top_level_timestamp(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    event_time = datetime(2026, 6, 5, 9, 30, tzinfo=timezone.utc)
    monkeypatch.setenv("POSTHOG_ENABLED", "true")
    monkeypatch.setenv("POSTHOG_TOKEN", "phc_test")

    def fake_post(_url, *, json, timeout, trust_env):
        calls.append(json)
        return _Response()

    monkeypatch.setattr(posthog.httpx, "post", fake_post)

    assert posthog.capture_posthog_event(
        "course_build_plan_confirmed",
        distinct_id="user_a",
        properties={"analytics_source": "backend"},
        timestamp=event_time,
    )

    assert calls[0]["timestamp"] == "2026-06-05T09:30:00+00:00"


def test_capture_course_build_event_later_queues_without_inline_capture(monkeypatch) -> None:
    submitted: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    inline_calls: list[str] = []
    monkeypatch.setenv("POSTHOG_ENABLED", "true")
    monkeypatch.setenv("POSTHOG_TOKEN", "phc_test")

    class _Executor:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            future: Future[bool] = Future()
            future.set_result(True)
            return future

    monkeypatch.setattr(posthog, "_POSTHOG_EXECUTOR", _Executor())
    monkeypatch.setattr(
        posthog,
        "capture_course_build_event",
        lambda event, **_kwargs: inline_calls.append(event) or True,
    )

    future = posthog.capture_course_build_event_later(
        "knowledge_build_started",
        course_id="course_a",
        user_id="user_a",
        insert_id_parts=["request-a"],
    )

    assert future is not None
    assert future.done()
    assert inline_calls == []

    fn, args, kwargs = submitted[0]
    assert kwargs["timestamp"] is not None
    fn(*args, **kwargs)
    assert inline_calls == ["knowledge_build_started"]
