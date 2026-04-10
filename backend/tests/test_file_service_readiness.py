from __future__ import annotations

from datetime import datetime

from app.models.raw_file import RawFile
from app.services.file_service import build_file_record


def test_build_file_record_marks_cloud_markdown_ready_without_local_file() -> None:
    raw_file = RawFile(
        id=1,
        uid="file_test_ready",
        subject="demo-subject",
        filename="demo.pdf",
        filetype="pdf",
        file_path="demo-subject/raw_files/1.pdf",
        storage_backend="s3",
        markdown_path="demo-subject/raw_markdowns/1.md",
        markdown_content="# Parsed markdown\n\nhello world",
        asset_dir="demo-subject/assets/1",
        status="completed",
        ingest_status="ready_for_digest",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    record = build_file_record(raw_file)

    assert record.markdown_ready is True


def test_build_file_record_keeps_processing_when_markdown_not_persisted() -> None:
    raw_file = RawFile(
        id=2,
        uid="file_test_processing",
        subject="demo-subject",
        filename="demo.pdf",
        filetype="pdf",
        file_path="demo-subject/raw_files/2.pdf",
        storage_backend="s3",
        markdown_path="demo-subject/raw_markdowns/2.md",
        markdown_content="",
        asset_dir="demo-subject/assets/2",
        status="processing",
        ingest_status="classifying",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    record = build_file_record(raw_file)

    assert record.markdown_ready is False
