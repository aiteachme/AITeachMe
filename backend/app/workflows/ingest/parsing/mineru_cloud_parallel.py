"""Chunked MinerU Cloud adapter for PDFs over the provider page limit.

PDFs with more than 200 pages are split into chunks of at most 199 pages,
parsed concurrently through the existing single-file MinerU adapter, and then
merged back in original page order. Other inputs keep the single-file path.
"""

from __future__ import annotations

import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import structlog

from app.workflows.ingest.parsing.lib.provider_contracts import ExternalProviderTimeoutError
from app.workflows.ingest.parsing.mineru_cloud import (
    DEFAULT_MINERU_BASE_URL,
    MinerUExtractedResult,
    MinerURequestOptions,
    parse_file_to_dir as parse_file_to_dir_single,
)
from app.workflows.ingest.parsing.progress import ParseProgressCallback

try:  # pragma: no cover - runtime dependency availability
    from pypdf import PdfReader, PdfWriter  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None
    PdfWriter = None


logger = structlog.get_logger(__name__)

DEFAULT_MINERU_PAGE_LIMIT = 200
DEFAULT_MINERU_MAX_PAGES_PER_CHUNK = 199
DEFAULT_MINERU_CHUNK_CONCURRENCY = 4

_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
_HTML_IMAGE_RE = re.compile(r'(<img\b[^>]*?\bsrc=["\'])(?P<src>[^"\']+)(["\'])', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _MinerUChunk:
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
    chunk: _MinerUChunk
    extracted: MinerUExtractedResult


def parse_file_to_dir_parallel(
    *,
    file_path: Path,
    options: MinerURequestOptions,
    output_dir: Path,
    base_url: str = DEFAULT_MINERU_BASE_URL,
    poll_interval_s: float = 2.0,
    poll_timeout_s: float = 600.0,
    total_timeout_s: float | None = None,
    max_pages_per_chunk: int = DEFAULT_MINERU_MAX_PAGES_PER_CHUNK,
    max_concurrent_jobs: int = DEFAULT_MINERU_CHUNK_CONCURRENCY,
    progress_callback: ParseProgressCallback | None = None,
) -> MinerUExtractedResult:
    """Parse a file with MinerU, chunking PDFs only when they exceed 200 pages."""

    if file_path.suffix.lower() != ".pdf":
        return _parse_single(
            file_path=file_path,
            options=options,
            output_dir=output_dir,
            base_url=base_url,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            total_timeout_s=total_timeout_s,
            progress_callback=progress_callback,
        )

    total_pages = _get_pdf_page_count(file_path)
    if total_pages <= DEFAULT_MINERU_PAGE_LIMIT:
        logger.info(
            "mineru_cloud_chunking_skipped",
            file_name=file_path.name,
            total_pages=total_pages,
            page_limit=DEFAULT_MINERU_PAGE_LIMIT,
        )
        return _parse_single(
            file_path=file_path,
            options=options,
            output_dir=output_dir,
            base_url=base_url,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            total_timeout_s=total_timeout_s,
            progress_callback=progress_callback,
        )

    normalized_chunk_pages = min(
        max(1, int(max_pages_per_chunk)),
        DEFAULT_MINERU_MAX_PAGES_PER_CHUNK,
    )
    normalized_concurrency = max(1, int(max_concurrent_jobs))
    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = _build_deadline(total_timeout_s)
    chunks = _split_pdf_to_chunks(
        pdf_path=file_path,
        chunk_output_dir=output_dir / "_pdf_chunks",
        max_pages=normalized_chunk_pages,
    )
    _raise_timeout_if_deadline_exceeded(deadline=deadline, total_timeout_s=total_timeout_s)

    worker_count = min(normalized_concurrency, len(chunks))
    logger.info(
        "mineru_cloud_chunked_parse_requested",
        file_name=file_path.name,
        total_pages=total_pages,
        chunk_count=len(chunks),
        chunk_page_counts=[chunk.page_count for chunk in chunks],
        max_pages_per_chunk=normalized_chunk_pages,
        max_concurrent_jobs=worker_count,
        timeout_budget_s=total_timeout_s,
    )

    started_at = time.monotonic()
    results: list[_ChunkResult] = []
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="mineru") as executor:
        futures = {
            executor.submit(
                _process_chunk,
                chunk=chunk,
                options=options,
                output_dir=output_dir / "_mineru_jobs" / f"chunk_{chunk.chunk_index + 1:04d}",
                base_url=base_url,
                poll_interval_s=poll_interval_s,
                poll_timeout_s=poll_timeout_s,
                deadline=deadline,
                total_timeout_s=total_timeout_s,
                progress_callback=progress_callback,
                overall_total_pages=total_pages,
            ): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                results.append(future.result())
            except ExternalProviderTimeoutError:
                raise
            except Exception as exc:
                raise RuntimeError(f"MinerU 分块解析失败: {chunk.label}: {exc}") from exc
            logger.info("mineru_cloud_chunk_completed", chunk=chunk.label)

    results.sort(key=lambda item: item.chunk.start_page)
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "processing_result",
                "provider": "mineru",
                "current_pages": total_pages,
                "total_pages": total_pages,
                "detail": "整理正文与图片",
            }
        )
    markdown_path, images_dir = _merge_chunk_results(results=results, output_dir=output_dir)
    batch_ids = tuple(result.extracted.batch_id for result in results)
    chunk_page_counts = [result.chunk.page_count for result in results]
    elapsed_s = round(time.monotonic() - started_at, 2)
    metadata: dict[str, object] = {
        "strategy": "chunked",
        "batch_count": len(batch_ids),
        "total_pages": total_pages,
        "chunk_count": len(results),
        "chunk_page_counts": chunk_page_counts,
        "max_pages_per_chunk": normalized_chunk_pages,
        "max_concurrent_jobs": worker_count,
        "elapsed_s": elapsed_s,
    }
    logger.info(
        "mineru_cloud_chunked_result_materialized",
        file_name=file_path.name,
        batch_ids=list(batch_ids),
        **metadata,
    )
    return MinerUExtractedResult(
        markdown_path=markdown_path,
        images_dir=images_dir,
        batch_id=",".join(batch_ids),
        file_name=file_path.name,
        batch_ids=batch_ids,
        metadata=metadata,
    )


def _parse_single(**kwargs) -> MinerUExtractedResult:
    return parse_file_to_dir_single(**kwargs)


def _build_deadline(total_timeout_s: float | None) -> float | None:
    if total_timeout_s is None or total_timeout_s <= 0:
        return None
    return time.monotonic() + float(total_timeout_s)


def _remaining_total_timeout_s(
    *, deadline: float | None, total_timeout_s: float | None
) -> float | None:
    if deadline is None:
        return total_timeout_s
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExternalProviderTimeoutError("MinerU", total_timeout_s or 0)
    return remaining


def _raise_timeout_if_deadline_exceeded(
    *, deadline: float | None, total_timeout_s: float | None
) -> None:
    _remaining_total_timeout_s(deadline=deadline, total_timeout_s=total_timeout_s)


def _get_pdf_page_count(pdf_path: Path) -> int:
    if PdfReader is None:
        raise RuntimeError("MinerU 超长 PDF 分块需要 pypdf 依赖，请重新安装后端依赖。")
    with pdf_path.open("rb") as file_obj:
        return len(PdfReader(file_obj).pages)


def _split_pdf_to_chunks(
    *, pdf_path: Path, chunk_output_dir: Path, max_pages: int
) -> list[_MinerUChunk]:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError("MinerU 超长 PDF 分块需要 pypdf 依赖，请重新安装后端依赖。")

    chunk_output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    chunks: list[_MinerUChunk] = []
    for chunk_index, start in enumerate(range(0, total_pages, max_pages)):
        end = min(start + max_pages, total_pages)
        writer = PdfWriter()
        for page_index in range(start, end):
            writer.add_page(reader.pages[page_index])
        chunk_path = chunk_output_dir / f"{pdf_path.stem}_pages_{start + 1:06d}_{end:06d}.pdf"
        with chunk_path.open("wb") as file_obj:
            writer.write(file_obj)
        chunks.append(
            _MinerUChunk(
                chunk_index=chunk_index,
                source_path=chunk_path,
                start_page=start + 1,
                end_page=end,
            )
        )
    return chunks


def _process_chunk(
    *,
    chunk: _MinerUChunk,
    options: MinerURequestOptions,
    output_dir: Path,
    base_url: str,
    poll_interval_s: float,
    poll_timeout_s: float,
    deadline: float | None,
    total_timeout_s: float | None,
    progress_callback: ParseProgressCallback | None,
    overall_total_pages: int,
) -> _ChunkResult:
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
        progress_callback(
            {
                **normalized_event,
                "chunk_id": str(chunk.chunk_index),
                "overall_total_pages": overall_total_pages,
            }
        )

    extracted = _parse_single(
        file_path=chunk.source_path,
        options=options,
        output_dir=output_dir,
        base_url=base_url,
        poll_interval_s=poll_interval_s,
        poll_timeout_s=poll_timeout_s,
        total_timeout_s=_remaining_total_timeout_s(
            deadline=deadline,
            total_timeout_s=total_timeout_s,
        ),
        progress_callback=report_chunk_progress,
    )
    return _ChunkResult(chunk=chunk, extracted=extracted)


def _merge_chunk_results(
    *, results: list[_ChunkResult], output_dir: Path
) -> tuple[Path, Path | None]:
    merged_images_dir = output_dir / "images"
    markdown_blocks: list[str] = []
    copied_image_count = 0

    for result in results:
        markdown = result.extracted.markdown_path.read_text(encoding="utf-8", errors="replace")
        rename_map: dict[str, str] = {}
        source_images_dir = result.extracted.images_dir
        if source_images_dir is not None and source_images_dir.is_dir():
            merged_images_dir.mkdir(parents=True, exist_ok=True)
            for source_path in sorted(source_images_dir.rglob("*")):
                if not source_path.is_file():
                    continue
                preferred_name = f"chunk_{result.chunk.chunk_index + 1:04d}_{source_path.name}"
                target_name = _dedupe_filename(merged_images_dir, preferred_name)
                shutil.copy2(source_path, merged_images_dir / target_name)
                relative_key = source_path.relative_to(source_images_dir).as_posix().lower()
                rename_map[relative_key] = target_name
                rename_map[f"images/{relative_key}"] = target_name
                rename_map.setdefault(source_path.name.lower(), target_name)
                copied_image_count += 1
        markdown_blocks.append(_rewrite_markdown_image_names(markdown, rename_map))

    merged_markdown = "\n\n".join(
        block.strip() for block in markdown_blocks if block and block.strip()
    ).strip()
    if not merged_markdown:
        raise RuntimeError("MinerU 分块解析返回空 Markdown")
    markdown_path = output_dir / "full.md"
    markdown_path.write_text(f"{merged_markdown}\n", encoding="utf-8")
    return markdown_path, merged_images_dir if copied_image_count else None


def _rewrite_markdown_image_names(markdown: str, rename_map: dict[str, str]) -> str:
    if not rename_map:
        return markdown

    def replace_markdown(match: re.Match[str]) -> str:
        target = match.group("target")
        path, suffix = _split_markdown_target(target)
        replaced = _replace_target_basename(path, rename_map)
        return f"![{match.group('alt')}]({replaced}{suffix})"

    rewritten = _MARKDOWN_IMAGE_RE.sub(replace_markdown, markdown)

    def replace_html(match: re.Match[str]) -> str:
        replaced = _replace_target_basename(match.group("src"), rename_map)
        return f"{match.group(1)}{replaced}{match.group(3)}"

    return _HTML_IMAGE_RE.sub(replace_html, rewritten)


def _split_markdown_target(target: str) -> tuple[str, str]:
    trimmed = target.strip()
    if trimmed.startswith("<") and ">" in trimmed:
        end = trimmed.find(">")
        return trimmed[1:end], trimmed[end + 1 :]
    match = re.match(r'(?P<path>\S+)(?P<suffix>\s+["\'][^"\']*["\'])?$', trimmed)
    if match is None:
        return trimmed, ""
    return match.group("path"), match.group("suffix") or ""


def _replace_target_basename(target: str, rename_map: dict[str, str]) -> str:
    trimmed = target.strip()
    if not trimmed:
        return target
    if trimmed.startswith("<") and trimmed.endswith(">"):
        trimmed = trimmed[1:-1].strip()
    normalized = unquote(trimmed).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    replacement = rename_map.get(normalized.lower())
    if replacement is None:
        replacement = rename_map.get(Path(normalized).name.lower())
    if replacement is None:
        return target
    return f"images/{replacement}"


def _dedupe_filename(dest_dir: Path, preferred_name: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", preferred_name).strip("._") or "image"
    if not (dest_dir / candidate).exists():
        return candidate
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    index = 1
    while (dest_dir / f"{stem}_{index}{suffix}").exists():
        index += 1
    return f"{stem}_{index}{suffix}"


__all__ = [
    "DEFAULT_MINERU_CHUNK_CONCURRENCY",
    "DEFAULT_MINERU_MAX_PAGES_PER_CHUNK",
    "DEFAULT_MINERU_PAGE_LIMIT",
    "parse_file_to_dir_parallel",
]
