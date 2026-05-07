from __future__ import annotations

import json

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.fast_parse.lib import parse as parse_lib
from app.workflows.ingest.parsing.orchestrator import FastParseResult
from app.workflows.ingest.parsing.provider_contracts import ExternalProviderTimeoutError, ParseDecision
from app.workflows.ingest.parsing.strategy import ParsePlan
from app.workflows.ingest.parsing.types import ParserRunOptions


@pytest.mark.anyio
async def test_paddle_timeout_falls_back_directly_to_local_parse(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")

    local_markdown_path = tmp_path / "out" / "markdown.md"
    local_asset_dir = tmp_path / "out" / "assets"

    async def fake_paddle_external_parse(**kwargs):
        del kwargs
        raise ExternalProviderTimeoutError("PaddleOCR", 15)

    async def fake_mineru_external_parse(**kwargs):
        del kwargs
        raise AssertionError("timeout fallback should go directly to local parse")

    async def fake_local_parse(**kwargs):
        del kwargs
        return FastParseResult(
            markdown="# local fallback",
            parser_used="markitdown",
            attempted_parsers=["markitdown"],
            parser_elapsed_s={"markitdown": 0.12},
            needs_enhance=False,
            needs_quality_reparse=False,
            needs_asset_ocr=False,
        )

    monkeypatch.setattr(parse_lib, "_run_paddle_ocr_external_parse", fake_paddle_external_parse)
    monkeypatch.setattr(parse_lib, "_run_mineru_external_parse", fake_mineru_external_parse)
    monkeypatch.setattr(parse_lib, "fast_parse_file", fake_local_parse)

    node = parse_lib.build_parse_file_node(
        context=WorkflowContext(
            workflow_name="ingest.fast_parse",
            course_id="course_test",
        )
    )
    state = {
        "user_id": "user_test",
        "course_id": "course_test",
        "file_id": "file_test",
        "filename": "source.pdf",
        "filetype": ".pdf",
        "file_path": str(source_path),
        "local_markdown_path": str(local_markdown_path),
        "local_asset_dir": str(local_asset_dir),
        "asset_link_prefix": "assets/file_test",
        "asset_name_prefix": "file_test_",
        "is_text_fast_path": False,
        "parse_plan": ParsePlan(
            mode="external_paddle_ocr",
            parser_chain=["paddle_ocr"],
            decision_reason="test",
            options=ParserRunOptions(),
        ),
        "parse_decision": ParseDecision(
            primary_provider="paddle_ocr",
            primary_reason="test",
            fallback_chain=["mineru", "local"],
        ),
    }

    result = await node(state)

    assert result["error"] is None
    assert result["parser_used"] == "markitdown"
    assert result["attempted_parsers"] == ["paddle_ocr", "markitdown"]
    assert local_markdown_path.read_text(encoding="utf-8") == "# local fallback"

    metadata = json.loads(result["parse_metadata"])
    provider_metadata = metadata["provider_metadata"]
    assert provider_metadata["fallback_to"] == "local"
    assert provider_metadata["timeout_provider"] == "paddle_ocr"
    assert provider_metadata["timeout_budget_s"] == 15
    assert "PaddleOCR 解析超时" in provider_metadata["provider_failures"]["paddle_ocr"]


@pytest.mark.anyio
async def test_image_paddle_timeout_falls_back_to_mineru_without_local_parse(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"fake-image")

    local_markdown_path = tmp_path / "out" / "markdown.md"
    local_asset_dir = tmp_path / "out" / "assets"

    async def fake_paddle_external_parse(**kwargs):
        del kwargs
        raise ExternalProviderTimeoutError("PaddleOCR", 15)

    async def fake_mineru_external_parse(**kwargs):
        del kwargs
        return (
            parse_lib._ExternalFastParseResult(
                markdown="# mineru fallback",
                parser_used="mineru",
                attempted_parsers=["mineru"],
                parser_elapsed_s={"mineru": 0.2},
                rewritten_image_refs=0,
                extracted_data_images=0,
                appended_asset_images=0,
                needs_enhance=False,
            ),
            {"batch_id": "batch_test"},
        )

    async def fake_local_parse(**kwargs):
        del kwargs
        raise AssertionError("image uploads must not fall back to local parse")

    monkeypatch.setattr(parse_lib, "_run_paddle_ocr_external_parse", fake_paddle_external_parse)
    monkeypatch.setattr(parse_lib, "_run_mineru_external_parse", fake_mineru_external_parse)
    monkeypatch.setattr(parse_lib, "fast_parse_file", fake_local_parse)

    node = parse_lib.build_parse_file_node(
        context=WorkflowContext(
            workflow_name="ingest.fast_parse",
            course_id="course_test",
        )
    )
    state = {
        "user_id": "user_test",
        "course_id": "course_test",
        "file_id": "file_test",
        "filename": "source.png",
        "filetype": ".png",
        "file_path": str(source_path),
        "local_markdown_path": str(local_markdown_path),
        "local_asset_dir": str(local_asset_dir),
        "asset_link_prefix": "assets/file_test",
        "asset_name_prefix": "file_test_",
        "is_text_fast_path": False,
        "parse_plan": ParsePlan(
            mode="external_paddle_ocr",
            parser_chain=["paddle_ocr"],
            decision_reason="test",
            options=ParserRunOptions(),
        ),
        "parse_decision": ParseDecision(
            primary_provider="paddle_ocr",
            primary_reason="test",
            fallback_chain=["mineru"],
            can_preview_before_primary=False,
            metadata={"image_external_required": True},
        ),
    }

    result = await node(state)

    assert result["error"] is None
    assert result["parser_used"] == "mineru"
    assert result["attempted_parsers"] == ["paddle_ocr", "mineru"]
    assert local_markdown_path.read_text(encoding="utf-8") == "# mineru fallback"

    metadata = json.loads(result["parse_metadata"])
    provider_metadata = metadata["provider_metadata"]
    assert provider_metadata["batch_id"] == "batch_test"
    assert "PaddleOCR 解析超时" in provider_metadata["provider_failures"]["paddle_ocr"]
