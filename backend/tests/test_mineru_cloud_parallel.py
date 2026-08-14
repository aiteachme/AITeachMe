from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.workflows.ingest.parsing import mineru_cloud_parallel
from app.workflows.ingest.parsing.mineru_cloud import (
    MinerUExtractedResult,
    MinerURequestOptions,
)


def test_pdf_over_200_pages_is_split_into_199_page_chunks_and_merged(
    monkeypatch, tmp_path
) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    captured_timeouts: list[float | None] = []

    monkeypatch.setattr(mineru_cloud_parallel, "_get_pdf_page_count", lambda path: 401)

    def fake_split_pdf_to_chunks(*, pdf_path, chunk_output_dir, max_pages):
        assert pdf_path == source_path
        assert max_pages == 199
        chunk_output_dir.mkdir(parents=True, exist_ok=True)
        page_ranges = [(1, 199), (200, 398), (399, 401)]
        chunks = []
        for index, (start_page, end_page) in enumerate(page_ranges):
            chunk_path = chunk_output_dir / f"chunk_{index + 1}.pdf"
            chunk_path.write_bytes(b"chunk")
            chunks.append(
                mineru_cloud_parallel._MinerUChunk(
                    chunk_index=index,
                    source_path=chunk_path,
                    start_page=start_page,
                    end_page=end_page,
                )
            )
        return chunks

    def fake_parse_single(**kwargs):
        chunk_number = int(Path(kwargs["file_path"]).stem.rsplit("_", 1)[1])
        captured_timeouts.append(kwargs["total_timeout_s"])
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "full.md"
        markdown_path.write_text(
            f"# chunk {chunk_number}\n\n![page](images/page.png)\n",
            encoding="utf-8",
        )
        images_dir = output_dir / "images"
        images_dir.mkdir()
        (images_dir / "page.png").write_bytes(f"image-{chunk_number}".encode())
        return MinerUExtractedResult(
            markdown_path=markdown_path,
            images_dir=images_dir,
            batch_id=f"batch_{chunk_number}",
            file_name=Path(kwargs["file_path"]).name,
        )

    monkeypatch.setattr(mineru_cloud_parallel, "_split_pdf_to_chunks", fake_split_pdf_to_chunks)
    monkeypatch.setattr(mineru_cloud_parallel, "_parse_single", fake_parse_single)

    result = mineru_cloud_parallel.parse_file_to_dir_parallel(
        file_path=source_path,
        options=MinerURequestOptions(api_token="token"),
        output_dir=tmp_path / "out",
        total_timeout_s=60,
        max_concurrent_jobs=3,
    )

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert markdown.index("# chunk 1") < markdown.index("# chunk 2") < markdown.index("# chunk 3")
    assert "images/chunk_0001_page.png" in markdown
    assert "images/chunk_0002_page.png" in markdown
    assert "images/chunk_0003_page.png" in markdown
    assert result.images_dir is not None
    assert sorted(path.name for path in result.images_dir.iterdir()) == [
        "chunk_0001_page.png",
        "chunk_0002_page.png",
        "chunk_0003_page.png",
    ]
    assert result.batch_ids == ("batch_1", "batch_2", "batch_3")
    assert result.metadata["strategy"] == "chunked"
    assert result.metadata["total_pages"] == 401
    assert result.metadata["chunk_page_counts"] == [199, 199, 3]
    assert len(captured_timeouts) == 3
    assert all(timeout is not None and 0 < timeout <= 60 for timeout in captured_timeouts)


def test_pdf_with_exactly_200_pages_keeps_single_mineru_job(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"fake-pdf")
    output_dir = tmp_path / "out"
    markdown_path = output_dir / "full.md"
    output_dir.mkdir()
    markdown_path.write_text("# single\n", encoding="utf-8")
    expected = MinerUExtractedResult(
        markdown_path=markdown_path,
        images_dir=None,
        batch_id="batch_single",
        file_name=source_path.name,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(mineru_cloud_parallel, "_get_pdf_page_count", lambda path: 200)

    def fake_parse_single(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(mineru_cloud_parallel, "_parse_single", fake_parse_single)
    monkeypatch.setattr(
        mineru_cloud_parallel,
        "_split_pdf_to_chunks",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("200 pages must not be split")),
    )

    result = mineru_cloud_parallel.parse_file_to_dir_parallel(
        file_path=source_path,
        options=MinerURequestOptions(api_token="token"),
        output_dir=output_dir,
        total_timeout_s=60,
    )

    assert result is expected
    assert captured["file_path"] == source_path
    assert captured["total_timeout_s"] == 60


def test_pdf_splitter_never_creates_a_chunk_over_199_pages(tmp_path) -> None:
    source_path = tmp_path / "source.pdf"
    writer = PdfWriter()
    for _ in range(401):
        writer.add_blank_page(width=100, height=100)
    with source_path.open("wb") as file_obj:
        writer.write(file_obj)

    chunks = mineru_cloud_parallel._split_pdf_to_chunks(
        pdf_path=source_path,
        chunk_output_dir=tmp_path / "chunks",
        max_pages=199,
    )

    assert [chunk.page_count for chunk in chunks] == [199, 199, 3]
    assert [len(PdfReader(str(chunk.source_path)).pages) for chunk in chunks] == [199, 199, 3]
