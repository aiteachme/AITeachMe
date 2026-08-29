from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.parsing.lib.defaults import (
    DEFAULT_EXTERNAL_PARSE_TIMEOUT_S,
    DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S,
)
from app.workflows.ingest.parsing import paddle_ocr_cloud, paddle_ocr_parallel
from app.workflows.ingest.parsing.nodes import parse_file as parse_lib
from app.workflows.ingest.parsing.orchestrator import FastParseResult
from app.workflows.ingest.parsing.lib.provider_contracts import ExternalProviderTimeoutError, ParseDecision
from app.workflows.ingest.parsing.strategy import ParsePlan
from app.workflows.ingest.parsing.lib.types import ParserRunOptions


def test_external_parse_timeout_defaults_are_90_seconds() -> None:
    assert DEFAULT_EXTERNAL_PARSE_TIMEOUT_S == 90
    assert DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S == 90
    assert paddle_ocr_cloud.DEFAULT_PADDLE_OCR_DOWNLOAD_DEADLINE_EXTENSION_S == 40.0


def test_paddle_ocr_parallel_preserves_timeout_error(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    chunk = paddle_ocr_parallel._OcrChunk(
        chunk_index=0,
        source_path=source_path,
        start_page=1,
        end_page=10,
    )

    monkeypatch.setattr(paddle_ocr_parallel, "_get_pdf_page_count", lambda path: 20)
    monkeypatch.setattr(
        paddle_ocr_parallel,
        "_split_pdf_to_chunks",
        lambda **kwargs: [chunk],
    )

    def fail_chunk(**kwargs):
        del kwargs
        raise ExternalProviderTimeoutError("PaddleOCR", 42)

    monkeypatch.setattr(paddle_ocr_parallel, "_process_chunk", fail_chunk)

    with pytest.raises(ExternalProviderTimeoutError):
        paddle_ocr_parallel.parse_file_to_dir_parallel(
            file_path=source_path,
            options=paddle_ocr_cloud.PaddleOCRRequestOptions(api_token="token"),
            output_dir=tmp_path / "out",
            total_timeout_s=42,
        )


@pytest.mark.anyio
async def test_paddle_timeout_falls_back_directly_to_local_parse(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")

    local_markdown_path = tmp_path / "out" / "markdown.md"
    local_asset_dir = tmp_path / "out" / "assets"

    async def fake_paddle_external_parse(**kwargs):
        del kwargs
        raise ExternalProviderTimeoutError("PaddleOCR", DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S)

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

    def fake_build_parse_plan(**kwargs):
        del kwargs
        return ParsePlan(
            mode="local_markitdown",
            parser_chain=["markitdown"],
            decision_reason="test local fallback",
            options=ParserRunOptions(),
        )

    monkeypatch.setattr(parse_lib, "_run_paddle_ocr_external_parse", fake_paddle_external_parse)
    monkeypatch.setattr(parse_lib, "_run_mineru_external_parse", fake_mineru_external_parse)
    monkeypatch.setattr(
        parse_lib,
        "_paddle_ocr_parse_timeout_s",
        lambda: float(DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S),
    )
    monkeypatch.setattr(parse_lib, "build_parse_plan", fake_build_parse_plan)
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
    assert provider_metadata["timeout_budget_s"] == DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S
    assert "PaddleOCR 解析超时" in provider_metadata["provider_failures"]["paddle_ocr"]


@pytest.mark.anyio
async def test_image_paddle_timeout_falls_back_to_mineru_without_local_parse(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"fake-image")

    local_markdown_path = tmp_path / "out" / "markdown.md"
    local_asset_dir = tmp_path / "out" / "assets"

    async def fake_paddle_external_parse(**kwargs):
        del kwargs
        raise ExternalProviderTimeoutError("PaddleOCR", DEFAULT_PADDLE_OCR_PARSE_TIMEOUT_S)

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


@pytest.mark.anyio
async def test_paddle_ocr_single_mode_routes_to_cloud_adapter(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    local_asset_dir = tmp_path / "assets"
    captured: dict[str, object] = {}

    def fake_parse_file_to_dir_with_paddle_ocr(**kwargs):
        captured.update(kwargs)
        output_dir = kwargs["output_dir"]
        markdown_path = output_dir / "full.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# paddle", encoding="utf-8")
        return SimpleNamespace(
            markdown_path=markdown_path,
            images_dir=None,
            job_id="job_test",
            model=kwargs["options"].model,
        )

    monkeypatch.setenv("PADDLE_OCR_PARSE_TIMEOUT_S", "42")
    monkeypatch.setenv("PADDLE_OCR_MODEL", "PaddleOCR-VL-1.5")
    monkeypatch.setenv("PADDLE_OCR_PARSE_MODE", "single")
    monkeypatch.setattr(
        parse_lib,
        "parse_file_to_dir_with_paddle_ocr",
        fake_parse_file_to_dir_with_paddle_ocr,
    )

    result, metadata = await parse_lib._run_paddle_ocr_external_parse(
        state={
            "file_path": str(source_path),
            "temp_dir": str(tmp_path / "temp"),
            "asset_name_prefix": "file_test_",
            "asset_link_prefix": "assets/file_test",
            "paddle_ocr_token": "token",
            "paddle_ocr_token_source": "request",
        },
        local_asset_dir=local_asset_dir,
        parse_plan=ParsePlan(
            mode="external_paddle_ocr",
            parser_chain=["paddle_ocr"],
            decision_reason="test",
            options=ParserRunOptions(),
        ),
    )

    assert result.markdown == "# paddle\n"
    assert captured["total_timeout_s"] == 42.0
    assert captured["options"].model == "PaddleOCR-VL-1.5"
    assert metadata["timeout_budget_s"] == 42.0
    assert metadata["model"] == "PaddleOCR-VL-1.5"
    assert metadata["strategy"] == "single"


@pytest.mark.anyio
async def test_paddle_ocr_parallel_mode_routes_to_chunk_adapter(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    local_asset_dir = tmp_path / "assets"
    captured: dict[str, object] = {}

    def fake_parse_file_to_dir_with_paddle_ocr(**kwargs):
        del kwargs
        raise AssertionError("parallel mode should not call the single PaddleOCR adapter")

    def fake_parse_file_to_dir_with_paddle_ocr_parallel(**kwargs):
        captured.update(kwargs)
        output_dir = kwargs["output_dir"]
        markdown_path = output_dir / "full.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# paddle parallel", encoding="utf-8")
        return SimpleNamespace(
            markdown_path=markdown_path,
            images_dir=None,
            job_id="job_a,job_b",
            job_ids=("job_a", "job_b"),
            model=kwargs["options"].model,
            metadata={
                "strategy": "parallel",
                "job_count": 2,
                "chunk_count": 2,
                "chunk_page_counts": [10, 8],
            },
        )

    monkeypatch.setenv("PADDLE_OCR_PARSE_MODE", "parallel")
    monkeypatch.setenv("PADDLE_OCR_PARSE_TIMEOUT_S", "42")
    monkeypatch.setenv("PADDLE_OCR_CHUNK_MAX_PAGES", "10")
    monkeypatch.setenv("PADDLE_OCR_CHUNK_CONCURRENCY", "3")
    monkeypatch.setattr(
        parse_lib,
        "parse_file_to_dir_with_paddle_ocr",
        fake_parse_file_to_dir_with_paddle_ocr,
    )
    monkeypatch.setattr(
        parse_lib,
        "parse_file_to_dir_with_paddle_ocr_parallel",
        fake_parse_file_to_dir_with_paddle_ocr_parallel,
    )

    result, metadata = await parse_lib._run_paddle_ocr_external_parse(
        state={
            "file_path": str(source_path),
            "temp_dir": str(tmp_path / "temp"),
            "asset_name_prefix": "file_test_",
            "asset_link_prefix": "assets/file_test",
            "paddle_ocr_token": "token",
            "paddle_ocr_token_source": "request",
        },
        local_asset_dir=local_asset_dir,
        parse_plan=ParsePlan(
            mode="external_paddle_ocr",
            parser_chain=["paddle_ocr"],
            decision_reason="test",
            options=ParserRunOptions(),
        ),
    )

    assert result.markdown == "# paddle parallel\n"
    assert captured["total_timeout_s"] == 42.0
    assert captured["max_pages_per_chunk"] == 10
    assert captured["max_concurrent_jobs"] == 3
    assert metadata["strategy"] == "parallel"
    assert metadata["job_ids"] == ["job_a", "job_b"]
    assert metadata["job_count"] == 2
    assert metadata["chunk_count"] == 2
    assert metadata["chunk_page_counts"] == [10, 8]
    assert metadata["chunk_max_pages"] == 10
    assert metadata["chunk_concurrency"] == 3


@pytest.mark.anyio
async def test_paddle_ocr_defaults_to_parallel_with_ten_page_chunks(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    captured: dict[str, object] = {}

    def fake_parse_file_to_dir_with_paddle_ocr_parallel(**kwargs):
        captured.update(kwargs)
        output_dir = kwargs["output_dir"]
        markdown_path = output_dir / "full.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# paddle parallel", encoding="utf-8")
        return SimpleNamespace(
            markdown_path=markdown_path,
            images_dir=None,
            job_id="job_a",
            job_ids=("job_a",),
            model=kwargs["options"].model,
            metadata={"strategy": "parallel"},
        )

    monkeypatch.delenv("PADDLE_OCR_PARSE_MODE", raising=False)
    monkeypatch.delenv("PADDLE_OCR_CHUNK_MAX_PAGES", raising=False)
    monkeypatch.setattr(
        parse_lib,
        "parse_file_to_dir_with_paddle_ocr_parallel",
        fake_parse_file_to_dir_with_paddle_ocr_parallel,
    )

    await parse_lib._run_paddle_ocr_external_parse(
        state={
            "file_path": str(source_path),
            "temp_dir": str(tmp_path / "temp"),
            "asset_name_prefix": "file_test_",
            "asset_link_prefix": "assets/file_test",
            "paddle_ocr_token": "token",
            "paddle_ocr_token_source": "request",
        },
        local_asset_dir=tmp_path / "assets",
        parse_plan=ParsePlan(
            mode="external_paddle_ocr",
            parser_chain=["paddle_ocr"],
            decision_reason="test",
            options=ParserRunOptions(),
        ),
    )

    assert captured["max_pages_per_chunk"] == 10


def test_paddle_ocr_cloud_uses_one_second_default_poll_interval(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = '{"data": {"jobId": "job_test"}}'

        def json(self):
            return {"data": {"jobId": "job_test"}}

    class FakeSession:
        def post(self, *args, **kwargs):
            return FakeResponse()

    def fake_poll_until_done(**kwargs):
        captured["poll_interval_s"] = kwargs["poll_interval_s"]
        return "https://example.test/result.jsonl"

    def fake_download_and_materialize_jsonl(**kwargs):
        del kwargs
        return "# paddle\n"

    monkeypatch.setattr(paddle_ocr_cloud, "_get_session", lambda: FakeSession())
    monkeypatch.setattr(paddle_ocr_cloud, "_poll_until_done", fake_poll_until_done)
    monkeypatch.setattr(
        paddle_ocr_cloud,
        "_download_and_materialize_jsonl",
        fake_download_and_materialize_jsonl,
    )

    paddle_ocr_cloud.parse_file_to_dir(
        file_path=source_path,
        options=paddle_ocr_cloud.PaddleOCRRequestOptions(api_token="token"),
        output_dir=tmp_path / "out",
        total_timeout_s=20,
    )

    assert captured["poll_interval_s"] == 1.0


def test_paddle_ocr_download_extends_original_deadline_after_poll_done(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = '{"data": {"jobId": "job_test"}}'

        def json(self):
            return {"data": {"jobId": "job_test"}}

    class FakeSession:
        def post(self, *args, **kwargs):
            return FakeResponse()

    def fake_poll_until_done(**kwargs):
        return "https://example.test/result.jsonl"

    initial_deadline = paddle_ocr_cloud.time.monotonic() + 100

    def fake_build_deadline(timeout_s):
        captured.setdefault("deadlines", []).append(timeout_s)
        assert timeout_s == 42
        return initial_deadline

    def fake_download_and_materialize_jsonl(**kwargs):
        captured["download_deadline"] = kwargs["deadline"]
        captured["download_total_timeout_s"] = kwargs["total_timeout_s"]
        return "# paddle\n"

    monkeypatch.setattr(paddle_ocr_cloud, "_get_session", lambda: FakeSession())
    monkeypatch.setattr(paddle_ocr_cloud, "_poll_until_done", fake_poll_until_done)
    monkeypatch.setattr(paddle_ocr_cloud, "_build_deadline", fake_build_deadline)
    monkeypatch.setattr(
        paddle_ocr_cloud,
        "_download_and_materialize_jsonl",
        fake_download_and_materialize_jsonl,
    )

    paddle_ocr_cloud.parse_file_to_dir(
        file_path=source_path,
        options=paddle_ocr_cloud.PaddleOCRRequestOptions(api_token="token"),
        output_dir=tmp_path / "out",
        total_timeout_s=42,
        download_deadline_extension_s=7,
    )

    assert captured["deadlines"] == [42]
    assert captured["download_deadline"] == initial_deadline + 7
    assert captured["download_total_timeout_s"] == 49


@pytest.mark.anyio
async def test_pptx_mineru_timeout_falls_back_to_local_markitdown(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pptx"
    source_path.write_bytes(b"fake-pptx")

    local_markdown_path = tmp_path / "out" / "markdown.md"
    local_asset_dir = tmp_path / "out" / "assets"

    async def fake_mineru_external_parse(**kwargs):
        del kwargs
        raise ExternalProviderTimeoutError("MinerU", DEFAULT_EXTERNAL_PARSE_TIMEOUT_S)

    async def fake_local_parse(**kwargs):
        assert kwargs["parse_plan"].mode == "local_markitdown"
        assert kwargs["parse_plan"].parser_chain == ["markitdown"]
        return FastParseResult(
            markdown="# local pptx fallback",
            parser_used="markitdown",
            attempted_parsers=["markitdown"],
            parser_elapsed_s={"markitdown": 0.08},
            needs_enhance=False,
            needs_quality_reparse=False,
            needs_asset_ocr=False,
        )

    def fake_build_parse_plan(**kwargs):
        assert kwargs["filetype"] == ".pptx"
        return ParsePlan(
            mode="local_markitdown",
            parser_chain=["markitdown"],
            decision_reason="test pptx local fallback",
            options=ParserRunOptions(),
        )

    monkeypatch.setattr(parse_lib, "_run_mineru_external_parse", fake_mineru_external_parse)
    monkeypatch.setattr(parse_lib, "build_parse_plan", fake_build_parse_plan)
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
        "filename": "source.pptx",
        "filetype": ".pptx",
        "file_path": str(source_path),
        "local_markdown_path": str(local_markdown_path),
        "local_asset_dir": str(local_asset_dir),
        "asset_link_prefix": "assets/file_test",
        "asset_name_prefix": "file_test_",
        "is_text_fast_path": False,
        "parse_plan": ParsePlan(
            mode="external_mineru",
            parser_chain=["mineru"],
            decision_reason="test",
            options=ParserRunOptions(),
        ),
        "parse_decision": ParseDecision(
            primary_provider="mineru",
            primary_reason="test",
            fallback_chain=["local"],
            can_preview_before_primary=False,
        ),
    }

    result = await node(state)

    assert result["error"] is None
    assert result["parser_used"] == "markitdown"
    assert result["attempted_parsers"] == ["mineru", "markitdown"]
    assert local_markdown_path.read_text(encoding="utf-8") == "# local pptx fallback"

    metadata = json.loads(result["parse_metadata"])
    provider_metadata = metadata["provider_metadata"]
    assert provider_metadata["fallback_to"] == "local"
    assert provider_metadata["timeout_provider"] == "mineru"
    assert provider_metadata["timeout_budget_s"] == DEFAULT_EXTERNAL_PARSE_TIMEOUT_S
    assert "MinerU 解析超时" in provider_metadata["provider_failures"]["mineru"]
