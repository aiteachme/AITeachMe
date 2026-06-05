from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import knowledge_docs as api
from app.api.deps import CurrentUserContext
from app.models import Course
from app.shared.infra.analytics import posthog as posthog_analytics
from app.schemas.knowledge import (
    BuildPlannerConfirmResponse,
    BuildPlannerCreateRequest,
    BuildPlannerPlanResponse,
    BuildPlannerRuntimeStatsResponse,
    BuildPlannerSessionResponse,
    BuildPlannerStepStatsResponse,
    DocGenBuildData,
    DocGenBuildRequest,
    KnowledgeDocInteractiveSelectionRequest,
    KnowledgeGraphBuildData,
)


COURSE_ID = "course_api000000000"
USER_ID = "user-api"


def _user() -> CurrentUserContext:
    return CurrentUserContext(
        user_id=USER_ID,
        email=None,
        is_local=True,
        is_authenticated=True,
        auth_source="test",
    )


def _course(course_id: str = COURSE_ID) -> Course:
    return Course(id=course_id, user_id=USER_ID, name="API Course")


def _request(*, request_id: str = "request-1", registry=None):
    return SimpleNamespace(
        state=SimpleNamespace(request_id=request_id),
        app=SimpleNamespace(state=SimpleNamespace(background_task_registry=registry)),
    )


def _capture_course_build_event_inline(
    event,
    *,
    course_id,
    user_id,
    insert_id_parts,
    properties=None,
    timestamp=None,
):
    return posthog_analytics.capture_course_build_event(
        event,
        course_id=course_id,
        user_id=user_id,
        insert_id_parts=insert_id_parts,
        properties=properties,
        timestamp=timestamp,
    )


def _planner_session_response() -> BuildPlannerSessionResponse:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    return BuildPlannerSessionResponse(
        session_id="planner-session-12345678",
        course_id=COURSE_ID,
        title="Plan",
        status="draft",
        revision=1,
        latest_plan=BuildPlannerPlanResponse(
            course_id=COURSE_ID,
            selected_file_ids=["file-a"],
            user_prompt="learn",
            digest_mode="sprint",
            chapter_plan=[
                {
                    "chapter_index": 1,
                    "title": "Intro",
                    "objective": "Understand basics",
                }
            ],
            build_constraints={},
            plan_summary="summary",
            plan_steps=["step"],
            adjustment_questions=["question"],
            status="draft",
            planner_session_id="planner-session-12345678",
        ),
        model_override="model-a",
        turns=[],
        runtime_stats=BuildPlannerRuntimeStatsResponse(
            elapsed_ms=1200,
            steps=[BuildPlannerStepStatsResponse(name="draft", elapsed_ms=1200)],
        ),
        created_at=now,
        updated_at=now,
    )


def _confirm_response() -> BuildPlannerConfirmResponse:
    now = datetime(2026, 5, 13, 10, 5, tzinfo=timezone.utc)
    return BuildPlannerConfirmResponse(
        planner_session_id="planner-session-12345678",
        confirmed_plan_id="confirmed-plan-12345678",
        version_no=2,
        course_id=COURSE_ID,
        status="confirmed",
        digest_mode="sprint",
        model_override="model-a",
        selected_file_ids=["file-a"],
        user_prompt="learn",
        plan_summary="summary",
        chapter_plan=[
            {
                "chapter_index": 1,
                "title": "Intro",
                "objective": "Understand basics",
            }
        ],
        build_constraints={},
        plan_json={},
        status_history=["draft", "confirmed"],
        created_at=now,
        updated_at=now,
    )


def test_interactive_overlay_helpers_normalize_cached_response() -> None:
    assert api._interactive_generation_origin("ch2_interactive_card") == "planned_auto"
    assert api._interactive_generation_origin("selection-ref") == "selection"
    assert api._interactive_selection_response_from_overlay(
        {"overlay_id": "overlay-1", "preview_url": "", "asset_path": "asset.html"},
        fallback_version_no=3,
    ) is None

    response = api._interactive_selection_response_from_overlay(
        {
            "overlay_id": "overlay-1",
            "anchor_id": "anchor-1",
            "title": "交互演示",
            "asset_path": "interactive/asset.html",
            "preview_url": "/preview/asset.html",
            "client_reference_id": "selection-ref",
            "selected_text": "selected text",
        },
        fallback_version_no=7,
    )

    assert response is not None
    assert response.overlay_id == "overlay-1"
    assert response.version_no == 7
    assert response.asset_path == "interactive/asset.html"
    assert "selection-ref" in response.preview_url
    assert "/preview/asset.html" in response.link_markdown


def test_knowledge_build_spawns_background_docgen_with_accepted_files(monkeypatch) -> None:
    spawned: list[dict[str, object]] = []
    run_kwargs: dict[str, object] = {}
    captured: list[tuple[str, str, dict[str, object]]] = []

    class Registry:
        def spawn(self, task, **kwargs):
            spawned.append({"task": task, **kwargs})

    request = _request(request_id="req-build", registry=Registry())
    build_data = DocGenBuildData(
        accepted_file_ids=["file-a"],
        prompt="learn matrices",
        ready_file_count=1,
        requested_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        planner_session_id="planner-1",
        confirmed_plan_id="plan-1",
        digest_mode="sprint",
        model_override="model-a",
    )

    def fake_trigger_docgen_build(_session, **kwargs):
        assert kwargs["file_ids"] == ["file-a", "file-b"]
        assert kwargs["confirmed_plan_id"] == "plan-1"
        return build_data, ["file-a"], "group-1"

    def fake_run_docgen_background(**kwargs):
        run_kwargs.update(kwargs)
        return "docgen-task"

    monkeypatch.setattr(api, "get_course_record", lambda _session, course_id, owner_user_id: _course(course_id))
    monkeypatch.setattr(api, "trigger_docgen_build", fake_trigger_docgen_build)
    monkeypatch.setattr(api, "run_docgen_background", fake_run_docgen_background)
    monkeypatch.setattr(api, "capture_course_build_event_later", _capture_course_build_event_inline)
    monkeypatch.setattr(
        posthog_analytics,
        "capture_posthog_event",
        lambda event, *, distinct_id, properties=None, timestamp=None: captured.append(
            (event, distinct_id, properties or {})
        )
        or True,
    )

    response = asyncio.run(
        api.knowledge_build(
            request=request,
            course_id=COURSE_ID,
            body=DocGenBuildRequest(file_ids=["file-a", "file-b"], prompt="draft", confirmed_plan_id="plan-1"),
            user=_user(),
            session=object(),
        )
    )

    assert response.data is build_data
    assert spawned == [
        {
            "task": "docgen-task",
            "kind": "knowledge.build.docs",
            "course_id": COURSE_ID,
            "name": f"knowledge.build.docs:{COURSE_ID}",
        }
    ]
    assert run_kwargs["course_id"] == COURSE_ID
    assert run_kwargs["course_name"] == "API Course"
    assert run_kwargs["file_ids"] == ["file-a"]
    assert run_kwargs["build_group_id"] == "group-1"
    assert run_kwargs["background_task_registry"] is request.app.state.background_task_registry
    assert [event for event, _distinct_id, _properties in captured] == [
        "knowledge_build_submitted",
        "knowledge_build_started",
    ]
    assert {distinct_id for _event, distinct_id, _properties in captured} == {USER_ID}
    assert all(properties["analytics_source"] == "backend" for _event, _distinct_id, properties in captured)
    assert captured[0][2]["has_confirmed_plan"] is True
    assert captured[1][2]["build_group_id_suffix"] == "group-1"


def test_build_planner_create_and_confirm_capture_backend_analytics(monkeypatch) -> None:
    captured: list[tuple[str, str, dict[str, object]]] = []
    planner_response = _planner_session_response()
    confirm_response = _confirm_response()

    async def fake_create_build_planner_session(**kwargs):
        assert kwargs["course"].id == COURSE_ID
        assert kwargs["user_id"] == USER_ID
        return planner_response

    def fake_confirm_build_planner_session(_session, **kwargs):
        assert kwargs["course"].id == COURSE_ID
        assert kwargs["user_id"] == USER_ID
        assert kwargs["session_id"] == "planner-session-12345678"
        return confirm_response

    monkeypatch.setattr(api, "get_course_record", lambda _session, course_id, owner_user_id: _course(course_id))
    monkeypatch.setattr(api, "create_build_planner_session", fake_create_build_planner_session)
    monkeypatch.setattr(api, "confirm_build_planner_session", fake_confirm_build_planner_session)
    monkeypatch.setattr(api, "capture_course_build_event_later", _capture_course_build_event_inline)
    monkeypatch.setattr(
        posthog_analytics,
        "capture_posthog_event",
        lambda event, *, distinct_id, properties=None, timestamp=None: captured.append(
            (event, distinct_id, properties or {})
        )
        or True,
    )

    create_response = asyncio.run(
        api.knowledge_build_plan_create(
            request=_request(request_id="req-plan"),
            course_id=COURSE_ID,
            body=BuildPlannerCreateRequest(file_ids=["file-a"], user_prompt="learn", model="model-a"),
            user=_user(),
            session=object(),
        )
    )
    confirm_api_response = api.knowledge_build_plan_confirm(
        request=_request(request_id="req-confirm"),
        course_id=COURSE_ID,
        session_id="planner-session-12345678",
        user=_user(),
        session=object(),
    )

    assert create_response.data is planner_response
    assert confirm_api_response.data is confirm_response
    assert [event for event, _distinct_id, _properties in captured] == [
        "course_plan_requested",
        "course_plan_generated",
        "course_build_plan_confirmed",
    ]
    assert {distinct_id for _event, distinct_id, _properties in captured} == {USER_ID}
    for event, _distinct_id, properties in captured:
        assert properties["analytics_source"] == "backend"
        assert properties["user_id_suffix"] == USER_ID[-8:]
        assert properties["course_id_suffix"] == COURSE_ID[-8:]
        assert str(properties["$insert_id"]).startswith(f"{event}:")
        assert COURSE_ID not in str(properties["$insert_id"])
    assert captured[1][2]["chapter_count"] == 1
    assert captured[1][2]["runtime_step_count"] == 1
    assert captured[2][2]["confirmed_plan_id_suffix"] == "12345678"


def test_build_planner_create_failure_does_not_capture_generated(monkeypatch) -> None:
    captured: list[tuple[str, str, dict[str, object]]] = []

    async def fake_create_build_planner_session(**_kwargs):
        raise RuntimeError("planner failed")

    monkeypatch.setattr(api, "get_course_record", lambda _session, course_id, owner_user_id: _course(course_id))
    monkeypatch.setattr(api, "create_build_planner_session", fake_create_build_planner_session)
    monkeypatch.setattr(api, "capture_course_build_event_later", _capture_course_build_event_inline)
    monkeypatch.setattr(
        posthog_analytics,
        "capture_posthog_event",
        lambda event, *, distinct_id, properties=None, timestamp=None: captured.append(
            (event, distinct_id, properties or {})
        )
        or True,
    )

    with pytest.raises(RuntimeError):
        asyncio.run(
            api.knowledge_build_plan_create(
                request=_request(request_id="req-plan-fail"),
                course_id=COURSE_ID,
                body=BuildPlannerCreateRequest(file_ids=["file-a"], user_prompt="learn"),
                user=_user(),
                session=object(),
            )
        )

    assert [event for event, _distinct_id, _properties in captured] == ["course_plan_requested"]


def test_knowledge_graph_build_passes_registry_and_course_authorization(monkeypatch) -> None:
    registry = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=registry)))
    graph_data = KnowledgeGraphBuildData(
        course_id=COURSE_ID,
        requested_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        build_group_id="group-graph",
        build_session_id="graph-session",
        source_file_ids=["file-a"],
    )
    calls: list[dict[str, object]] = []

    def fake_trigger_graph_docs_sync_manual_build(_session, **kwargs):
        calls.append(kwargs)
        return graph_data

    monkeypatch.setattr(api, "get_course_record", lambda _session, course_id, owner_user_id: _course(course_id))
    monkeypatch.setattr(api, "trigger_graph_docs_sync_manual_build", fake_trigger_graph_docs_sync_manual_build)

    response = asyncio.run(
        api.knowledge_graph_build(
            request=request,
            course_id=COURSE_ID,
            user=_user(),
            session=object(),
        )
    )

    assert response.data is graph_data
    assert calls[0]["course"].id == COURSE_ID
    assert calls[0]["background_task_registry"] is registry


def test_interactive_selection_generation_persists_overlay_without_handle_leak(monkeypatch) -> None:
    appended: list[dict[str, object]] = []
    generated_assets = [
        {
            "title": "Generated Demo",
            "asset_path": "interactive/demo.html",
            "preview_url": "/preview/demo.html",
        }
    ]

    @asynccontextmanager
    async def guard(_course_scope, *, version_no: int, client_reference_id: str | None):
        assert version_no == 9
        assert client_reference_id == "selection-ref"
        yield

    async def fake_run_llm_tasks(_items, _worker):
        return generated_assets

    async def fake_find_overlay(*_args, **_kwargs):
        return None

    async def fake_append_overlay(_course_scope, *, overlay, replace_overlay_id=None):
        appended.append({"overlay": overlay, "replace_overlay_id": replace_overlay_id})

    monkeypatch.setattr(api, "get_course_record", lambda _session, course_id, owner_user_id: _course(course_id))
    monkeypatch.setattr(api, "_storage_scope_for_course_record", lambda course: SimpleNamespace(course_id=course.id))
    monkeypatch.setattr(api, "ensure_published_knowledge_manifest", lambda *_args, **_kwargs: SimpleNamespace(version_no=9))
    monkeypatch.setattr(api, "interactive_overlay_reference_guard", guard)
    monkeypatch.setattr(api, "find_interactive_overlay_by_client_reference", fake_find_overlay)
    monkeypatch.setattr(api, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(api, "append_interactive_overlay", fake_append_overlay)

    response = asyncio.run(
        api.knowledge_docs_interactive_selection(
            course_id=COURSE_ID,
            body=KnowledgeDocInteractiveSelectionRequest(
                anchor_id="anchor-1",
                selected_text="selected text",
                prompt="make it visual",
                client_reference_id="selection-ref",
            ),
            user=_user(),
            session=object(),
        )
    )

    assert response.data.title == "Generated Demo"
    assert response.data.version_no == 9
    assert response.data.overlay_id.startswith("interactive-")
    assert "selection-ref" in response.data.preview_url
    assert appended[0]["replace_overlay_id"] is None
    assert appended[0]["overlay"]["asset_path"] == "interactive/demo.html"
    assert appended[0]["overlay"]["link_markdown"] == response.data.link_markdown
