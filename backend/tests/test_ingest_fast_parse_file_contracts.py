from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.fast_parse.lib import file as file_nodes
from app.workflows.ingest.parsing.strategy import ParsePlan
from app.workflows.ingest.parsing.types import ParserRunOptions


def _context() -> WorkflowContext:
    return WorkflowContext(workflow_name="test.ingest", course_id="course_test")


def _decision(**overrides: object) -> SimpleNamespace:
    values = {
        "uses_mineru": False,
        "uses_paddle_ocr": False,
        "uses_ocr": False,
        "uses_markitdown": False,
        "metadata": {},
        "primary_reason": "requested",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_parse_request_resolution_sanitizes_tokens_and_normalizes_options() -> None:
    payload = {
        "requested_parser_provider": "Paddle-OCR",
        "mineru": {
            "api_token": " mineru-secret ",
            "model_version": "VLM",
            "enable_formula": "off",
            "enable_table": "yes",
            "is_ocr": "0",
        },
        "paddle_ocr": {"api_token": " paddle-secret ", "language": "ch"},
    }

    (
        sanitized,
        requested_provider,
        mineru_token,
        paddle_ocr_token,
        mineru_model_version,
        mineru_enable_formula,
        mineru_enable_table,
        mineru_is_ocr,
    ) = file_nodes._resolve_parse_request(raw_payload=payload)

    assert requested_provider == "paddle_ocr"
    assert mineru_token == "mineru-secret"
    assert paddle_ocr_token == "paddle-secret"
    assert mineru_model_version == "vlm"
    assert mineru_enable_formula is False
    assert mineru_enable_table is True
    assert mineru_is_ocr is False
    assert "api_token" not in sanitized["mineru"]
    assert "api_token" not in sanitized["paddle_ocr"]
    assert file_nodes._decode_json_object("not-json") == {}
    assert file_nodes._normalize_parser_provider("local") is None
    assert file_nodes._relative_asset_link_prefix(
        markdown_key="users/u/raw/file.md",
        asset_dir="users/u/raw/assets/file",
    ) == "assets/file"


def test_load_raw_file_state_materializes_file_and_persists_sanitized_metadata(monkeypatch, tmp_path) -> None:
    materialized_dir = tmp_path / "materialized"
    updates: list[dict[str, object]] = []
    raw_file = SimpleNamespace(
        id="file-1",
        user_id="user-1",
        original_filename="lesson.pdf",
        file_ext=".pdf",
        file_path="stored/lesson.pdf",
        storage_key="stored/lesson.pdf",
        markdown_path=None,
        asset_dir=None,
        storage_backend="local",
        parse_error_message="previous failure",
        parse_metadata_json=json.dumps(
            {
                "requested_parser_provider": "mineru",
                "mineru": {"api_token": "request-token", "enable_table": "false"},
            }
        ),
    )

    class Scope:
        def raw_markdown_key(self, *, file_id: str, filename: str) -> str:
            return f"users/user-1/raw/{file_id}/{filename}.md"

        def asset_prefix(self, *, file_id: str, filename: str) -> str:
            return f"users/user-1/raw/{file_id}/assets/{filename}/"

    class Store:
        def user_file_scope(self, *, user_id: str) -> Scope:
            assert user_id == "user-1"
            return Scope()

        async def materialize(self, storage_key: str, temp_dir):
            assert storage_key == "stored/lesson.pdf"
            temp_dir.mkdir(parents=True, exist_ok=True)
            path = temp_dir / "lesson.pdf"
            path.write_bytes(b"pdf")
            return path

    @contextmanager
    def fake_managed_session():
        yield object()

    def fake_update_raw_file(_session, file_obj, **kwargs):
        updates.append(kwargs)
        for key, value in kwargs.items():
            setattr(file_obj, key, value)
        return file_obj

    decision = _decision(uses_mineru=True, primary_reason="mineru requested")
    parse_decision_calls: list[dict[str, object]] = []

    def fake_build_parse_decision(**kwargs):
        parse_decision_calls.append(kwargs)
        return decision

    monkeypatch.setattr(file_nodes.tempfile, "mkdtemp", lambda prefix: str(materialized_dir))
    monkeypatch.setattr(file_nodes, "get_content_store", lambda: Store())
    monkeypatch.setattr(file_nodes, "managed_session", fake_managed_session)
    monkeypatch.setattr(file_nodes, "get_raw_file_by_id", lambda _session, file_id: raw_file if file_id == "file-1" else None)
    monkeypatch.setattr(file_nodes, "update_raw_file", fake_update_raw_file)
    monkeypatch.setattr(file_nodes, "build_parse_decision", fake_build_parse_decision)
    monkeypatch.setattr(file_nodes, "_is_ocr_provider_available", lambda: True)
    monkeypatch.setattr(file_nodes, "_is_paddle_ocr_provider_available", lambda token=None: False)
    monkeypatch.setattr(file_nodes, "is_markitdown_available_for_extension", lambda extension: True)

    state = asyncio.run(file_nodes._load_raw_file_state({"file_id": "file-1", "user_id": "user-1"}))

    assert state["error"] is None
    assert state["file_path"].endswith("lesson.pdf")
    assert state["local_markdown_path"].endswith("file-1.md")
    assert state["asset_link_prefix"].endswith("assets/lesson.pdf")
    assert state["asset_upload_prefix"].endswith("/assets/lesson.pdf/")
    assert state["requested_parser_provider"] == "mineru"
    assert state["mineru_token"] == "request-token"
    assert state["mineru_token_source"] == "request"
    assert state["mineru_enable_table"] is False
    assert state["parse_decision"] is decision
    assert parse_decision_calls[0]["mineru_available"] is True
    assert any(update.get("parse_error_message") is None for update in updates)
    assert "api_token" not in raw_file.parse_metadata_json


def test_compute_fingerprint_node_reports_success_and_missing_file(tmp_path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_bytes(b"stable content")
    node = file_nodes.build_compute_fingerprint_node(context=_context())

    success = asyncio.run(node({"file_id": "file-1", "file_path": str(file_path)}))
    failure = asyncio.run(node({"file_id": "file-1", "file_path": str(tmp_path / "missing.txt")}))

    assert success["content_hash"] == hashlib.sha256(b"stable content").hexdigest()
    assert success["file_size_bytes"] == len(b"stable content")
    assert success["error"] is None
    assert failure["error"].startswith("compute_fingerprint_failed:")


def test_plan_parse_node_routes_external_and_local_fast_paths(monkeypatch) -> None:
    node = file_nodes.build_plan_parse_node(context=_context())
    monkeypatch.setattr(
        file_nodes,
        "build_parse_plan",
        lambda **kwargs: ParsePlan(
            mode="local_pdf",
            parser_chain=["pymupdf", "ocr_vision"],
            decision_reason="local",
            options=ParserRunOptions(ocr_page_limit=12),
        ),
    )
    monkeypatch.setattr(file_nodes, "resolve_markitdown_parser_name", lambda filetype: "markitdown_pdf")

    mineru = asyncio.run(
        node(
                {
                    "file_id": "file-1",
                    "filetype": ".pdf",
                    "file_path": "lesson.pdf",
                "asset_name_prefix": "asset-",
                "parse_decision": _decision(uses_mineru=True, primary_reason="mineru requested"),
            }
        )
    )
    unavailable_image = asyncio.run(
        node(
                {
                    "file_id": "file-1",
                    "filetype": ".png",
                    "file_path": "image.png",
                "parse_decision": _decision(metadata={"image_external_required": True}),
            }
        )
    )
    ocr_pdf = asyncio.run(
        node(
                {
                    "file_id": "file-1",
                    "filetype": ".pdf",
                    "file_path": "lesson.pdf",
                "estimated_pages": 35,
                "asset_name_prefix": "ocr-",
                "parse_decision": _decision(uses_ocr=True, primary_reason="ocr requested"),
            }
        )
    )
    markitdown = asyncio.run(
        node(
                {
                    "file_id": "file-1",
                    "filetype": ".pdf",
                    "file_path": "lesson.pdf",
                "asset_name_prefix": "md-",
                "parse_decision": _decision(uses_markitdown=True, primary_reason="markitdown requested"),
            }
        )
    )

    assert mineru["parse_plan"].mode == "external_mineru"
    assert mineru["parse_plan"].parser_chain == ["mineru"]
    assert mineru["parse_plan"].options.asset_name_prefix == "asset-"
    assert unavailable_image["error"].startswith("image_external_parser_unavailable:")
    assert ocr_pdf["parse_plan"].mode == "external_ocr"
    assert ocr_pdf["parse_plan"].parser_chain[0] == "ocr_vision"
    assert ocr_pdf["parse_plan"].options.enable_page_vision_ocr is True
    assert ocr_pdf["parse_plan"].options.ocr_page_limit == 120
    assert ocr_pdf["parse_plan"].options.asset_name_prefix == "ocr-"
    assert markitdown["parse_plan"].mode == "local_markitdown"
    assert markitdown["parse_plan"].parser_chain == ["markitdown_pdf"]
    assert markitdown["parse_plan"].options.enable_page_vision_ocr is False
    assert markitdown["parse_plan"].options.asset_name_prefix == "md-"
