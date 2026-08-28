from __future__ import annotations

from types import SimpleNamespace

from app.workflows.ingest.parsing import mineru_cloud, paddle_ocr_cloud, paddle_ocr_parallel
from app.workflows.ingest.parsing import progress as progress_lib


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.status_code = 200
        self.text = ""
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def test_parse_progress_tracker_aggregates_parallel_chunk_pages(monkeypatch) -> None:
    writes: list[dict[str, object]] = []

    def fake_persist_parse_progress(**payload: object) -> None:
        writes.append(payload)

    monkeypatch.setattr(progress_lib, "persist_parse_progress", fake_persist_parse_progress)
    tracker = progress_lib.ParseProgressTracker(
        user_id="user_test",
        file_id="file_test",
        min_write_interval_s=0,
    )

    tracker.report(
        {
            "stage": "parsing",
            "provider": "mineru",
            "chunk_id": "chunk_0",
            "current_pages": 4,
            "total_pages": 10,
            "overall_total_pages": 30,
        }
    )
    tracker.report(
        {
            "stage": "parsing",
            "provider": "mineru",
            "chunk_id": "chunk_1",
            "current_pages": 6,
            "total_pages": 10,
            "overall_total_pages": 30,
        }
    )
    tracker.report(
        {
            "stage": "parsing",
            "provider": "mineru",
            "chunk_id": "chunk_2",
            "current_pages": None,
            "total_pages": 10,
            "overall_total_pages": 30,
        }
    )

    assert writes[-1]["current_pages"] == 10
    assert writes[-1]["total_pages"] == 30
    assert writes[-1]["percent"] == 37


def test_parse_progress_tracker_does_not_fall_back_to_chunk_denominator(monkeypatch) -> None:
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        progress_lib,
        "persist_parse_progress",
        lambda **payload: writes.append(payload),
    )
    tracker = progress_lib.ParseProgressTracker(
        user_id="user_test",
        file_id="file_test",
        min_write_interval_s=0,
    )

    tracker.report(
        {
            "stage": "parsing",
            "provider": "paddle_ocr",
            "chunk_id": "chunk_0",
            "current_pages": 10,
            "total_pages": 10,
            "overall_total_pages": 60,
        }
    )
    tracker.report(
        {
            "stage": "parsing",
            "provider": "paddle_ocr",
            "current_pages": None,
            "total_pages": 10,
        }
    )

    assert writes[-1]["current_pages"] == 10
    assert writes[-1]["total_pages"] == 60
    assert writes[-1]["percent"] == 23


def test_parse_progress_tracker_keeps_each_chunk_page_count_monotonic(monkeypatch) -> None:
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        progress_lib,
        "persist_parse_progress",
        lambda **payload: writes.append(payload),
    )
    tracker = progress_lib.ParseProgressTracker(
        user_id="user_test",
        file_id="file_test",
        min_write_interval_s=0,
    )

    for current_pages in (8, 3):
        tracker.report(
            {
                "stage": "parsing",
                "provider": "paddle_ocr",
                "chunk_id": "chunk_0",
                "current_pages": current_pages,
                "total_pages": 10,
                "overall_total_pages": 25,
            }
        )

    assert writes[-1]["current_pages"] == 8
    assert writes[-1]["total_pages"] == 25
    assert writes[-1]["percent"] == 36


def test_parse_progress_tracker_does_not_move_percent_backwards(monkeypatch) -> None:
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        progress_lib,
        "persist_parse_progress",
        lambda **payload: writes.append(payload),
    )
    tracker = progress_lib.ParseProgressTracker(
        user_id="user_test",
        file_id="file_test",
        min_write_interval_s=0,
    )

    tracker.stage("parsing", percent=62)
    tracker.stage("uploading")

    assert writes[-1]["stage"] == "uploading"
    assert writes[-1]["percent"] == 62


def test_paddle_poll_reports_extracted_pages(monkeypatch) -> None:
    responses = iter(
        [
            _Response(
                {
                    "data": {
                        "state": "running",
                        "extractProgress": {"extractedPages": 3, "totalPages": 8},
                    }
                }
            ),
            _Response(
                {
                    "data": {
                        "state": "done",
                        "extractProgress": {"extractedPages": 8, "totalPages": 8},
                        "resultUrl": {"jsonUrl": "https://example.test/result.jsonl"},
                    }
                }
            ),
        ]
    )
    session = SimpleNamespace(get=lambda *args, **kwargs: next(responses))
    events: list[dict[str, object]] = []
    monkeypatch.setattr(paddle_ocr_cloud.time, "sleep", lambda _: None)

    result_url = paddle_ocr_cloud._poll_until_done(
        session=session,
        job_url="https://example.test/jobs",
        headers={},
        job_id="job_test",
        poll_interval_s=0,
        poll_timeout_s=30,
        deadline=None,
        total_timeout_s=None,
        progress_callback=lambda event: events.append(dict(event)),
    )

    assert result_url == "https://example.test/result.jsonl"
    assert [(event["current_pages"], event["total_pages"]) for event in events] == [
        (3, 8),
        (8, 8),
    ]


def test_paddle_parallel_marks_downloaded_chunk_as_fully_parsed(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "pages_0001_0010.pdf"
    source_path.write_bytes(b"fake-pdf")
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    response = SimpleNamespace(
        status_code=200,
        text="",
        json=lambda: {"data": {"jobId": "job_test"}},
    )
    session = SimpleNamespace(
        post=lambda *args, **kwargs: response,
        close=lambda: None,
    )

    def fake_poll_until_done(**kwargs) -> str:
        kwargs["progress_callback"](
            {
                "stage": "parsing",
                "provider": "paddle_ocr",
                "current_pages": 3,
                "total_pages": 10,
            }
        )
        return "https://example.test/result.jsonl"

    events: list[dict[str, object]] = []
    monkeypatch.setattr(paddle_ocr_parallel, "_get_session", lambda: session)
    monkeypatch.setattr(paddle_ocr_parallel, "_poll_until_done", fake_poll_until_done)
    monkeypatch.setattr(
        paddle_ocr_parallel,
        "_download_and_materialize_jsonl",
        lambda **kwargs: "# parsed chunk",
    )

    result = paddle_ocr_parallel._process_chunk(
        chunk=paddle_ocr_parallel._OcrChunk(
            chunk_index=0,
            source_path=source_path,
            start_page=1,
            end_page=10,
        ),
        options=paddle_ocr_cloud.PaddleOCRRequestOptions(api_token="token"),
        job_url="https://example.test/jobs",
        poll_interval_s=0,
        poll_timeout_s=30,
        deadline=None,
        total_timeout_s=None,
        download_deadline_extension_s=30,
        images_dir=images_dir,
        progress_callback=lambda event: events.append(dict(event)),
        overall_total_pages=25,
    )

    assert result.markdown == "# parsed chunk"
    assert [(event["current_pages"], event["total_pages"]) for event in events] == [
        (3, 10),
        (10, 10),
    ]
    assert events[-1]["overall_total_pages"] == 25


def test_mineru_poll_reports_extracted_pages(monkeypatch) -> None:
    responses = iter(
        [
            _Response(
                {
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "source.pdf",
                                "state": "running",
                                "extract_progress": {"extracted_pages": 2, "total_pages": 6},
                            }
                        ]
                    },
                }
            ),
            _Response(
                {
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "source.pdf",
                                "state": "done",
                                "extract_progress": {"extracted_pages": 6, "total_pages": 6},
                                "full_zip_url": "https://example.test/result.zip",
                            }
                        ]
                    },
                }
            ),
        ]
    )
    requests = SimpleNamespace(get=lambda *args, **kwargs: next(responses))
    events: list[dict[str, object]] = []
    monkeypatch.setattr(mineru_cloud, "_get_requests", lambda: requests)
    monkeypatch.setattr(mineru_cloud.time, "sleep", lambda _: None)

    result_url = mineru_cloud._poll_until_done(
        "https://example.test",
        api_token="token",
        batch_id="batch_test",
        file_name="source.pdf",
        poll_interval_s=0,
        poll_timeout_s=30,
        deadline=None,
        total_timeout_s=None,
        progress_callback=lambda event: events.append(dict(event)),
    )

    assert result_url == "https://example.test/result.zip"
    assert [(event["current_pages"], event["total_pages"]) for event in events] == [
        (2, 6),
        (6, 6),
    ]
