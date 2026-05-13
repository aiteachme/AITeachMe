from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa

from app.shared.infra import cache as cache_module
from app.shared.infra import events as events_module
from app.shared.infra.execution import sandbox
from app.shared.infra.workflow import live_stream


def test_semantic_cache_respects_enabled_ttl_eviction_and_stats() -> None:
    disabled = cache_module.SemanticCache(enabled=False)

    disabled.put("question", "answer", model="m", task_type="chat")

    assert disabled.get("question", model="m", task_type="chat") is None
    assert disabled.get_stats() == {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0}

    enabled = cache_module.SemanticCache(enabled=True, ttl_s=60, max_entries=2)
    enabled.put("old", "old-answer", model="m", task_type="chat")
    enabled.put("new", "new-answer", model="m", task_type="chat")
    old_key = enabled._hash("m:chat:old")
    enabled._cache[old_key].created_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    assert enabled.get("old", model="m", task_type="chat") is None
    assert enabled.get("new", model="m", task_type="chat") == "new-answer"
    assert enabled.get_stats()["hit_rate"] == 0.5

    enabled.put("first", "1")
    first_key = enabled._hash("::first")
    enabled._cache[first_key].created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    enabled.put("second", "2")
    enabled.put("third", "3")

    assert enabled.get("first") is None
    assert enabled.get("second") == "2"
    assert enabled.invalidate() == 2
    assert enabled.get_stats()["entries"] == 0


def test_teaching_events_round_trip_filters_and_counts(monkeypatch, tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    monkeypatch.setattr("app.shared.infra.database.get_engine", lambda: engine)
    events_module._store = None

    async def scenario() -> None:
        first_id = await events_module.emit_event(
            events_module.EventType.EXAM_COMPLETED,
            user_id="u1",
            course_id="course-1",
            data={"score": 90},
        )
        await events_module.emit_event(
            events_module.EventType.MISTAKE_MADE,
            user_id="u1",
            course_id="course-2",
            data={"unit": "derivative"},
        )
        await events_module.emit_event(
            events_module.EventType.EXAM_COMPLETED,
            user_id="u2",
            course_id="course-1",
            data={"score": 70},
        )

        course_events = await events_module.get_events(
            user_id="u1",
            course_id="course-1",
            limit=5,
        )
        exam_count = await events_module.count_events(
            user_id="u1",
            event_type=events_module.EventType.EXAM_COMPLETED,
        )

        assert len(first_id) == 16
        assert [(event.event_type, event.course_id, event.data) for event in course_events] == [
            (events_module.EventType.EXAM_COMPLETED, "course-1", {"score": 90})
        ]
        assert exam_count == 1

    try:
        asyncio.run(scenario())
    finally:
        events_module._store = None


def test_workflow_live_stream_formats_routes_and_ignores_bad_notifications(monkeypatch) -> None:
    monkeypatch.setattr(live_stream, "_postgres_bridge_enabled", lambda: False)
    live_stream._SUBSCRIBERS.clear()

    payload = live_stream.format_sse_event(
        "progress",
        {"created": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    )
    assert payload.startswith("event: progress\n")
    assert json.loads(payload.split("data: ", 1)[1]) == {"created": "2026-01-01T00:00:00+00:00"}

    async def scenario() -> None:
        with live_stream.subscribe_workflow_stream(" course-1 ") as queue:
            live_stream.publish_workflow_stream_event("course-1", "progress", {"step": 1})
            item = await asyncio.wait_for(queue.get(), timeout=1)
            assert item == live_stream.WorkflowStreamEvent(event="progress", data={"step": 1})

            live_stream._handle_postgres_notification("not-json")
            live_stream._handle_postgres_notification(json.dumps({"origin": live_stream._PROCESS_ID}))
            live_stream._handle_postgres_notification(json.dumps({"origin": "other", "channel": "", "event": "x", "data": {}}))
            assert queue.empty()

            live_stream._handle_postgres_notification(
                json.dumps(
                    {
                        "origin": "other-process",
                        "channel": "course-1",
                        "event": "remote",
                        "data": {"ok": True},
                    }
                )
            )
            remote = await asyncio.wait_for(queue.get(), timeout=1)
            assert remote == live_stream.WorkflowStreamEvent(event="remote", data={"ok": True})

    asyncio.run(scenario())
    assert live_stream._SUBSCRIBERS == {}


def test_workflow_live_stream_postgres_payload_limits(monkeypatch) -> None:
    item = live_stream.WorkflowStreamEvent(event="message", data={"text": "small"})

    payload = live_stream._build_postgres_notify_payload("course", item)
    assert payload is not None
    assert json.loads(payload)["data"] == {"text": "small"}

    monkeypatch.setattr(live_stream, "POSTGRES_NOTIFY_PAYLOAD_LIMIT_BYTES", 40)

    assert live_stream._build_postgres_notify_payload("course", item) is None


def test_simulated_terminal_sandbox_tracks_commands_files_and_git_history() -> None:
    async def scenario() -> None:
        terminal = sandbox.SimulatedTerminalSandbox(
            custom_responses={r"^custom$": {"output": "custom-output", "code": 0}}
        )
        assert terminal.is_alive is False
        await terminal.initialize()

        assert (await terminal.execute("custom")).output == "custom-output"
        assert (await terminal.execute("echo 'hello'")).output == "hello"
        assert (await terminal.execute("touch notes.txt")).success is True
        assert (await terminal.execute("cat notes.txt")).output == ""
        assert (await terminal.execute("cd lessons")).metadata["cwd"].endswith("/lessons")
        assert (await terminal.execute("git init")).success is True
        assert "lesson" in (await terminal.execute("git commit -m 'lesson'")).output
        assert "lesson" in (await terminal.execute("git log --oneline")).output

        missing = await terminal.execute("unknown-command")
        snapshot = await terminal.snapshot()

        assert missing.exit_code == 127
        assert snapshot["alive"] is True
        assert snapshot["command_count"] == len(terminal.get_history())
        assert "$ git init" in terminal.get_history_text()

        await terminal.destroy()
        assert terminal.is_alive is False

    asyncio.run(scenario())


def test_exercise_sandbox_grades_wrong_and_correct_steps() -> None:
    exercise = sandbox.Exercise(
        title="Git exercise",
        description="Practice git basics",
        steps=[
            sandbox.ExerciseStep(
                instruction="Initialize repository",
                expected_commands=["git init"],
                hints=["run git init"],
                points=2,
            ),
            sandbox.ExerciseStep(
                instruction="Commit work",
                expected_commands=[r'git commit -m ["\']Initial["\']'],
                expected_output="committed",
                points=3,
            ),
        ],
    )

    async def scenario() -> None:
        lab = sandbox.ExerciseSandbox(exercise)
        await lab.initialize()

        wrong = await lab.execute("git status")
        first = await lab.execute("git init")
        second = await lab.execute('git commit -m "Initial"')
        grade = lab.grade()

        assert wrong.metadata["step_completed"] is False
        assert wrong.metadata["hint"] == "run git init"
        assert first.metadata["step_completed"] is True
        assert second.output == "committed"
        assert grade.passed is True
        assert grade.score == 5
        assert grade.steps_completed == 2
        assert len(lab.get_history()) == 3

        await lab.destroy()

    asyncio.run(scenario())


def test_sandbox_factories_return_initialized_instances_and_reject_unknown() -> None:
    async def scenario() -> None:
        terminal = await sandbox.create_sandbox(sandbox.SandboxType.SIMULATED_TERMINAL)
        assert terminal.is_alive is True
        await terminal.destroy()

        builtin = await sandbox.create_exercise_sandbox("git_init")
        assert builtin.current_step is not None
        await builtin.destroy()

        try:
            await sandbox.create_exercise_sandbox("missing")
        except ValueError as exc:
            assert "missing" in str(exc)
        else:
            raise AssertionError("missing exercise should be rejected")

        try:
            await sandbox.create_sandbox(sandbox.SandboxType.BROWSER)
        except NotImplementedError as exc:
            assert sandbox.SandboxType.BROWSER.name in str(exc)
        else:
            raise AssertionError("unsupported sandbox should be rejected")

    asyncio.run(scenario())
