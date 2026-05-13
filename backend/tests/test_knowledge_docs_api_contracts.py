from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from app.api import knowledge_docs as api
from app.api.deps import CurrentUserContext
from app.models import Course
from app.schemas.knowledge import (
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

    class Registry:
        def spawn(self, task, **kwargs):
            spawned.append({"task": task, **kwargs})

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=Registry())))
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
