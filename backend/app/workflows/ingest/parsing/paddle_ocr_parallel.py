"""Parallel PaddleOCR Cloud adapter for large PDFs.

This adapter keeps the existing single-job PaddleOCR integration as a fallback
and provides the default path for large local PDFs:
- split the PDF into page chunks
- submit chunk jobs concurrently
- materialize chunk markdown/assets
- merge markdown back in page order

All functions are synchronous so ingest workflows should call them via
``asyncio.to_thread(...)``.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.workflows.ingest.parsing.paddle_ocr_cloud import (
    DEFAULT_PADDLE_OCR_DOWNLOAD_DEADLINE_EXTENSION_S,
    DEFAULT_PADDLE_OCR_JOB_URL,
    DEFAULT_PADDLE_OCR_OPTIONAL_PAYLOAD,
    PaddleOCRExtractedResult,
    PaddleOCRRequestOptions,
    _build_deadline,
    _download_and_materialize_jsonl,
    _extend_deadline,
    _extended_timeout_budget_s,
    _get_session,
    _poll_until_done,
    _raise_timeout_if_deadline_exceeded,
    _remaining_timeout_s,
    parse_file_to_dir as parse_file_to_dir_single,
)
from app.workflows.ingest.parsing.progress import ParseProgressCallback

try:  # pragma: no cover - exercised through runtime dependency availability
    from pypdf import PdfReader, PdfWriter  # type: ignore
except Exception:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore
    except Exception:
        PdfReader = None
        PdfWriter = None


logger = structlog.get_logger(__name__)

DEFAULT_PADDLE_OCR_MAX_PAGES_PER_CHUNK = 10
DEFAULT_PADDLE_OCR_CHUNK_CONCURRENCY = 4


@dataclass(frozen=True, slots=True)
class _OcrChunk:
    chunk_index: int
    source_path: Path
    start_page: int
    end_page: int

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1

    @property
    def label(self) -> str:
        return f"chunk-{self.chunk_index + 1}({self.start_page}-{self.end_page})"


@dataclass(frozen=True, slots=True)
class _ChunkResult:
    chunk: _OcrChunk
    markdown: str
    job_id: str
    submit_elapsed_s: float


def parse_file_to_dir_parallel(
    *,
    file_path: Path,
    options: PaddleOCRRequestOptions,
    output_dir: Path,
    job_url: str = DEFAULT_PADDLE_OCR_JOB_URL,
    poll_interval_s: float = 1.0,
    poll_timeout_s: float = 600.0,
    total_timeout_s: float | None = None,
    download_deadline_extension_s: float = DEFAULT_PADDLE_OCR_DOWNLOAD_DEADLINE_EXTENSION_S,
    max_pages_per_chunk: int = DEFAULT_PADDLE_OCR_MAX_PAGES_PER_CHUNK,
    max_concurrent_jobs: int = DEFAULT_PADDLE_OCR_CHUNK_CONCURRENCY,
    progress_callback: ParseProgressCallback | None = None,
) -> PaddleOCRExtractedResult:
    """Split large PDFs and run PaddleOCR chunk jobs concurrently."""

    if not options.api_token.strip():
        raise RuntimeError(
            "PaddleOCR API Token 为空：请在前端设置中填写 Token，或在后端环境变量 PADDLE_OCR_API_TOKEN 中配置 Token。"
        )
    if not file_path.exists():
        raise RuntimeError(f"PaddleOCR 输入文件不存在：{file_path}")

    normalized_chunk_pages = max(1, int(max_pages_per_chunk))
    normalized_concurrency = max(1, int(max_concurrent_jobs))
    deadline = _build_deadline(total_timeout_s)

    if file_path.suffix.lower() != ".pdf":
        logger.info(
            "paddle_ocr_parallel_skipped",
            file_name=file_path.name,
            reason="non_pdf",
        )
        return parse_file_to_dir_single(
            file_path=file_path,
            options=options,
            output_dir=output_dir,
            job_url=job_url,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            total_timeout_s=total_timeout_s,
            download_deadline_extension_s=download_deadline_extension_s,
            progress_callback=progress_callback,
        )

    try:
        total_pages = _get_pdf_page_count(file_path)
    except Exception as exc:
        logger.warning(
            "paddle_ocr_parallel_skipped",
            file_name=file_path.name,
            reason="page_count_unavailable",
            error=str(exc),
        )
        return parse_file_to_dir_single(
            file_path=file_path,
            options=options,
            output_dir=output_dir,
            job_url=job_url,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            total_timeout_s=total_timeout_s,
            download_deadline_extension_s=download_deadline_extension_s,
            progress_callback=progress_callback,
        )
    if total_pages <= normalized_chunk_pages:
        logger.info(
            "paddle_ocr_parallel_skipped",
            file_name=file_path.name,
            reason="within_chunk_size",
            total_pages=total_pages,
            max_pages_per_chunk=normalized_chunk_pages,
        )
        return parse_file_to_dir_single(
            file_path=file_path,
            options=options,
            output_dir=output_dir,
            job_url=job_url,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            total_timeout_s=total_timeout_s,
            download_deadline_extension_s=download_deadline_extension_s,
            progress_callback=progress_callback,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir = output_dir / "_pdf_chunks"
    try:
        chunks = _split_pdf_to_chunks(
            pdf_path=file_path,
            chunk_output_dir=chunk_dir,
            max_pages=normalized_chunk_pages,
        )
    except Exception as exc:
        logger.warning(
            "paddle_ocr_parallel_skipped",
            file_name=file_path.name,
            reason="split_failed",
            error=str(exc),
        )
        return parse_file_to_dir_single(
            file_path=file_path,
            options=options,
            output_dir=output_dir,
            job_url=job_url,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            total_timeout_s=total_timeout_s,
            download_deadline_extension_s=download_deadline_extension_s,
            progress_callback=progress_callback,
        )
    _raise_timeout_if_deadline_exceeded(
        deadline=deadline,
        provider_name="PaddleOCR",
        total_timeout_s=total_timeout_s,
    )
    worker_count = min(normalized_concurrency, len(chunks))

    logger.info(
        "paddle_ocr_parallel_parse_requested",
        file_name=file_path.name,
        model=options.model,
        total_pages=total_pages,
        chunk_count=len(chunks),
        max_pages_per_chunk=normalized_chunk_pages,
        max_concurrent_jobs=worker_count,
        timeout_budget_s=total_timeout_s,
    )

    started_at = time.monotonic()
    results: list[_ChunkResult] = []
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="paddle-ocr") as executor:
        futures = {
            executor.submit(
                _process_chunk,
                chunk=chunk,
                options=options,
                job_url=job_url,
                poll_interval_s=poll_interval_s,
                poll_timeout_s=poll_timeout_s,
                deadline=deadline,
                total_timeout_s=total_timeout_s,
                download_deadline_extension_s=download_deadline_extension_s,
                images_dir=images_dir,
                progress_callback=progress_callback,
                overall_total_pages=total_pages,
            ): chunk
            for chunk in chunks
        }

        for future in as_completed(futures):
            chunk = futures[future]
            try:
                results.append(future.result())
                logger.info("paddle_ocr_parallel_chunk_completed", chunk=chunk.label)
            except Exception as exc:
                raise RuntimeError(f"PaddleOCR 分块解析失败: {chunk.label}: {exc}") from exc

    results.sort(key=lambda item: item.chunk.start_page)
    merged_markdown = _merge_chunk_markdown([result.markdown for result in results])
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "processing_result",
                "provider": "paddle_ocr",
                "current_pages": total_pages,
                "total_pages": total_pages,
                "detail": "整理正文与图片",
            }
        )
    markdown_path = output_dir / "full.md"
    markdown_path.write_text(merged_markdown, encoding="utf-8")

    job_ids = tuple(result.job_id for result in results)
    chunk_page_counts = tuple(result.chunk.page_count for result in results)
    total_submit_elapsed_s = round(sum(result.submit_elapsed_s for result in results), 2)
    elapsed_s = round(time.monotonic() - started_at, 2)
    logger.info(
        "paddle_ocr_parallel_result_materialized",
        job_ids=list(job_ids),
        total_pages=total_pages,
        chunk_count=len(chunks),
        chunk_page_counts=list(chunk_page_counts),
        chars=len(merged_markdown),
        elapsed_s=elapsed_s,
    )

    return PaddleOCRExtractedResult(
        markdown_path=markdown_path,
        images_dir=images_dir if any(images_dir.iterdir()) else None,
        job_id=",".join(job_ids),
        model=options.model,
        job_ids=job_ids,
        metadata={
            "strategy": "parallel",
            "job_count": len(job_ids),
            "total_pages": total_pages,
            "chunk_count": len(chunks),
            "chunk_page_counts": list(chunk_page_counts),
            "max_pages_per_chunk": normalized_chunk_pages,
            "max_concurrent_jobs": worker_count,
            "download_deadline_extension_s": download_deadline_extension_s,
            "submit_elapsed_s_sum": total_submit_elapsed_s,
            "elapsed_s": elapsed_s,
        },
    )


def _get_pdf_page_count(pdf_path: Path) -> int:
    if PdfReader is None:
        raise RuntimeError(
            "PaddleOCR 分块并发解析 PDF 需要 pypdf/PyPDF2 依赖；请先在后端环境安装 pypdf，或把 PADDLE_OCR_PARSE_MODE 改回 single。"
        )

    with pdf_path.open("rb") as file_obj:
        return len(PdfReader(file_obj).pages)


def _split_pdf_to_chunks(*, pdf_path: Path, chunk_output_dir: Path, max_pages: int) -> list[_OcrChunk]:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError(
            "PaddleOCR 分块并发解析 PDF 需要 pypdf/PyPDF2 依赖；请先在后端环境安装 pypdf，或把 PADDLE_OCR_PARSE_MODE 改回 single。"
        )

    chunk_output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    chunks: list[_OcrChunk] = []

    for chunk_index, start in enumerate(range(0, total_pages, max_pages)):
        end = min(start + max_pages, total_pages)
        writer = PdfWriter()
        for page_index in range(start, end):
            writer.add_page(reader.pages[page_index])

        chunk_path = chunk_output_dir / f"{pdf_path.stem}_pages_{start + 1:04d}_{end:04d}.pdf"
        with chunk_path.open("wb") as file_obj:
            writer.write(file_obj)

        chunks.append(
            _OcrChunk(
                chunk_index=chunk_index,
                source_path=chunk_path,
                start_page=start + 1,
                end_page=end,
            )
        )

    return chunks


def _process_chunk(
    *,
    chunk: _OcrChunk,
    options: PaddleOCRRequestOptions,
    job_url: str,
    poll_interval_s: float,
    poll_timeout_s: float,
    deadline: float | None,
    total_timeout_s: float | None,
    download_deadline_extension_s: float,
    images_dir: Path,
    progress_callback: ParseProgressCallback | None,
    overall_total_pages: int,
) -> _ChunkResult:
    session = _get_session()
    headers = {
        "Authorization": f"bearer {options.api_token}",
    }
    data = {
        "model": options.model,
        "optionalPayload": json.dumps(DEFAULT_PADDLE_OCR_OPTIONAL_PAYLOAD),
    }

    try:
        logger.info(
            "paddle_ocr_parallel_chunk_submit_requested",
            chunk=chunk.label,
            file_name=chunk.source_path.name,
            model=options.model,
        )
        submit_started_at = time.monotonic()
        with chunk.source_path.open("rb") as file_obj:
            response = session.post(
                job_url,
                headers=headers,
                data=data,
                files={"file": file_obj},
                timeout=_remaining_timeout_s(
                    deadline=deadline,
                    fallback_timeout_s=120,
                    provider_name="PaddleOCR",
                    total_timeout_s=total_timeout_s,
                ),
            )
    except Exception as exc:
        _raise_timeout_if_deadline_exceeded(
            deadline=deadline,
            provider_name="PaddleOCR",
            total_timeout_s=total_timeout_s,
        )
        try:
            session.close()
        except Exception:
            pass
        raise RuntimeError(f"PaddleOCR 提交分块任务失败: {exc}") from exc

    try:
        submit_elapsed_s = round(time.monotonic() - submit_started_at, 2)
        if response.status_code != 200:
            snippet = (response.text or "").strip().replace("\r", " ").replace("\n", " ")[:600]
            raise RuntimeError(f"PaddleOCR 提交分块任务失败: HTTP {response.status_code}; resp={snippet}")

        try:
            job_payload = response.json()
            job_id = str(job_payload["data"]["jobId"])
        except Exception as exc:
            snippet = (response.text or "")[:240]
            raise RuntimeError(f"PaddleOCR 分块任务返回数据异常: {snippet}") from exc

        logger.info(
            "paddle_ocr_parallel_chunk_submitted",
            chunk=chunk.label,
            job_id=job_id,
            submit_elapsed_s=submit_elapsed_s,
        )

        def report_chunk_progress(event):
            if progress_callback is None:
                return
            normalized_event = dict(event)
            if normalized_event.get("stage") in {"uploading", "queued"}:
                normalized_event.update(
                    stage="parsing",
                    current_pages=0,
                    total_pages=chunk.page_count,
                    detail="解析正文",
                )
            elif normalized_event.get("stage") in {"downloading", "processing_result"}:
                normalized_event.update(
                    stage="parsing",
                    current_pages=chunk.page_count,
                    total_pages=chunk.page_count,
                    detail="解析正文",
                )
            else:
                try:
                    current_pages = int(normalized_event.get("current_pages"))
                except (TypeError, ValueError):
                    current_pages = None
                if current_pages is not None:
                    normalized_event["current_pages"] = min(
                        max(current_pages, 0),
                        chunk.page_count,
                    )
                normalized_event["total_pages"] = chunk.page_count
            progress_callback(
                {
                    **normalized_event,
                    "chunk_id": str(chunk.chunk_index),
                    "overall_total_pages": overall_total_pages,
                }
            )

        jsonl_url = _poll_until_done(
            session=session,
            job_url=job_url,
            headers=headers,
            job_id=job_id,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            deadline=deadline,
            total_timeout_s=total_timeout_s,
            progress_callback=report_chunk_progress,
        )
        download_deadline = _extend_deadline(deadline, download_deadline_extension_s)
        download_timeout_budget_s = _extended_timeout_budget_s(
            total_timeout_s,
            download_deadline_extension_s,
        )
        logger.info(
            "paddle_ocr_parallel_chunk_download_started",
            chunk=chunk.label,
            job_id=job_id,
            download_deadline_extension_s=download_deadline_extension_s,
            download_timeout_budget_s=download_timeout_budget_s,
        )
        markdown = _download_and_materialize_jsonl(
            session=session,
            jsonl_url=jsonl_url,
            images_dir=images_dir,
            deadline=download_deadline,
            total_timeout_s=download_timeout_budget_s,
            image_name_prefix=f"chunk_{chunk.chunk_index + 1:04d}_",
        )
        report_chunk_progress(
            {
                "stage": "processing_result",
                "provider": "paddle_ocr",
                "current_pages": chunk.page_count,
                "total_pages": chunk.page_count,
                "detail": "解析正文",
            }
        )
    finally:
        try:
            session.close()
        except Exception:
            pass

    return _ChunkResult(
        chunk=chunk,
        markdown=markdown,
        job_id=job_id,
        submit_elapsed_s=submit_elapsed_s,
    )


def _merge_chunk_markdown(markdown_blocks: list[str]) -> str:
    merged = "\n\n".join(block.strip() for block in markdown_blocks if block and block.strip()).strip()
    if not merged:
        raise RuntimeError("PaddleOCR 分块解析返回空 Markdown")
    if not merged.endswith("\n"):
        merged += "\n"
    return merged


__all__ = [
    "DEFAULT_PADDLE_OCR_CHUNK_CONCURRENCY",
    "DEFAULT_PADDLE_OCR_MAX_PAGES_PER_CHUNK",
    "parse_file_to_dir_parallel",
]
