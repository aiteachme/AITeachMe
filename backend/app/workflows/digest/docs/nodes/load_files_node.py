"""节点：从数据库加载原始 Markdown 文件。

Reads DB: ``docgen_job`` and ``raw_file``.
Writes DB: ``docgen_job`` progress.
Writes FS: reads persisted ingest markdown files.
Idempotency: repeated runs read the same markdown inputs and refresh job progress only.
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from pathlib import Path

import structlog

from app.core.database import managed_session
from app.repositories.files_repo import list_raw_files_by_ids
from app.repositories.knowledge import docgen_repo
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_load_files_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """构建文件加载节点。"""

    async def load_files_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="load_files")
        file_ids = state["file_ids"]
        job_id = state["job_id"]
        node_logger.info(
            "load_files_started",
            requested_file_count=len(file_ids),
            io_parallelism=strategy.io_parallelism,
        )

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="loading", progress=2,
            )

        raw_chunks: list[dict] = []
        with managed_session() as session:
            raw_files = list_raw_files_by_ids(session, state["subject"], file_ids)
            file_map = {
                raw_file.id: {
                    "markdown_path": raw_file.markdown_path,
                    "filename": raw_file.filename,
                    "filetype": raw_file.filetype,
                }
                for raw_file in raw_files
                if raw_file.id is not None
            }

        async def _load_single(file_id: int) -> dict | None:
            raw_file = file_map.get(file_id)
            if raw_file is None or not raw_file["markdown_path"]:
                node_logger.warning("file_skipped", file_id=file_id, reason="no_markdown")
                return None

            md_path = Path(str(raw_file["markdown_path"]))
            if not md_path.exists():
                node_logger.warning("file_skipped", file_id=file_id, reason="not_found")
                return None

            async with strategy.io_semaphore:
                content = await asyncio.to_thread(md_path.read_text, encoding="utf-8")
            return {
                "file_id": file_id,
                "content": content,
                "source_filename": str(raw_file["filename"]),
                "filetype": str(raw_file["filetype"]),
            }

        loaded_chunks = await asyncio.gather(*(_load_single(file_id) for file_id in file_ids))
        raw_chunks = [chunk for chunk in loaded_chunks if chunk is not None]

        if not raw_chunks:
            return {"error": "没有可用的 Markdown 文件。"}

        load_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info("load_files_done", count=len(raw_chunks), load_ms=load_ms)
        return {"raw_chunks": raw_chunks, "load_ms": load_ms}

    return load_files_node
