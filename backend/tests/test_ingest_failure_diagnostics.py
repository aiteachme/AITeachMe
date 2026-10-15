from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.parsing.decision import build_parse_decision
from app.workflows.ingest.parsing.nodes import parse_file as parse_lib
from app.workflows.ingest.parsing.orchestrator import FastParseResult
from app.workflows.ingest.parsing.strategy import ParsePlan


@pytest.fixture
def isolated_parse(monkeypatch, tmp_path):
    events: list[dict] = []

    def capture(event, **kwargs):
        events.append({"event": event, **kwargs})

    monkeypatch.setattr(parse_lib, "workflow_logger", lambda *_args: SimpleNamespace(
        info=capture, warning=capture, error=capture,
    ))
    monkeypatch.setattr(parse_lib, "ParseProgressTracker", lambda **kwargs: SimpleNamespace(
        stage=lambda *_args, **_kwargs: None,
        report=lambda *_args, **_kwargs: None,
        flush=lambda: None,
    ))
    monkeypatch.setattr(parse_lib, "build_parse_plan", lambda **kwargs: ParsePlan(
        mode="local_markitdown", parser_chain=["markitdown"], decision_reason="isolated test",
    ))
    state = {
        "user_id": "isolated-user", "course_id": "isolated-course", "file_id": "isolated-file",
        "filename": "scan.pdf", "filetype": ".pdf", "file_path": str(tmp_path / "scan.pdf"),
        "local_markdown_path": str(tmp_path / "out" / "markdown.md"),
        "local_asset_dir": str(tmp_path / "out" / "assets"),
        "asset_link_prefix": "assets/isolated-file", "asset_name_prefix": "isolated-file_",
        "mineru_token": "synthetic-mineru-secret", "paddle_ocr_token": "synthetic-paddle-secret",
    }
    node = parse_lib.build_parse_file_node(context=WorkflowContext(
        workflow_name="test.parse.diagnostics", course_id="isolated-course",
    ))
    return node, state, events


def local_result():
    return FastParseResult(
        markdown="# local result", parser_used="markitdown", attempted_parsers=["markitdown"],
        parser_elapsed_s={"markitdown": 0.1}, needs_enhance=False,
        needs_quality_reparse=False, needs_asset_ocr=False,
    )


@pytest.mark.anyio
async def test_result_write_failure_preserves_terminal_error_and_redacts_logs(monkeypatch, isolated_parse):
    node, state, events = isolated_parse
    state["parse_decision"] = build_parse_decision(
        extension=".pdf", requested_provider=None, mineru_available=True, paddle_ocr_available=False,
    )

    async def mineru_failure(**kwargs):
        raise RuntimeError("MinerU unavailable synthetic-mineru-secret")

    async def local_success(**kwargs):
        return local_result()

    output_path = Path(state["local_markdown_path"])
    original_write_text = Path.write_text

    def fail_result_write(path, *args, **kwargs):
        if path == output_path:
            raise PermissionError("result write denied synthetic-paddle-secret")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(parse_lib, "_run_mineru_external_parse", mineru_failure)
    monkeypatch.setattr(parse_lib, "fast_parse_file", local_success)
    monkeypatch.setattr(Path, "write_text", fail_result_write)

    result = await node(state)

    assert "MinerU unavailable" in result["error"]
    assert "result write denied" in result["error"]
    metadata = json.loads(result["parse_metadata"])
    assert metadata["attempted_parsers"] == ["mineru", "markitdown"]
    assert metadata["parser_elapsed_s"]["markitdown"] == 0.1
    assert "result write denied" in metadata["provider_metadata"]["provider_failures"]["result"]
    rendered = json.dumps(events, default=str)
    assert "synthetic-mineru-secret" not in rendered
    assert "synthetic-paddle-secret" not in rendered
    terminal_log = next(item for item in events if item["event"] == "ingest_fast_parse_failed")
    assert "PermissionError" in terminal_log["traceback"]
    assert "result write denied" in terminal_log["traceback"]


@pytest.mark.anyio
@pytest.mark.parametrize("include_null_decision", [False, True])
async def test_missing_provider_decision_keeps_local_parse_route(
    monkeypatch, isolated_parse, include_null_decision,
):
    node, state, events = isolated_parse
    if include_null_decision:
        state["parse_decision"] = None

    async def local_success(**kwargs):
        return local_result()

    async def external_must_not_run(**kwargs):
        raise AssertionError("Missing external decision must stay on the local parse route")

    monkeypatch.setattr(parse_lib, "fast_parse_file", local_success)
    monkeypatch.setattr(parse_lib, "_run_mineru_external_parse", external_must_not_run)
    monkeypatch.setattr(parse_lib, "_run_paddle_ocr_external_parse", external_must_not_run)

    result = await node(state)

    assert result["error"] is None
    assert result["parser_used"] == "markitdown"
    assert json.loads(result["parse_metadata"])["parse_decision"] is None


@pytest.mark.anyio
async def test_local_parse_failure_without_provider_decision_redacts_terminal_log(monkeypatch, isolated_parse):
    node, state, events = isolated_parse

    async def local_failure(**kwargs):
        raise RuntimeError("parse failed synthetic-mineru-secret")

    monkeypatch.setattr(parse_lib, "fast_parse_file", local_failure)
    result = await node(state)

    assert result["error"].startswith("fast_parse_file_failed:")
    assert "synthetic-mineru-secret" not in result["error"]
    assert "synthetic-mineru-secret" not in json.dumps(events, default=str)

