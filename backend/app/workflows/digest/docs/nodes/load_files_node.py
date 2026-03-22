"""Load markdown inputs for knowledge docs generation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter

import structlog

from app.core.database import managed_session
from app.repositories.files_repo import list_raw_files_by_ids
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_load_files_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the markdown loading node."""

    async def load_files_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="load_files")
        file_ids = state["file_ids"]
        node_logger.info(
            "docgen_loading_inputs",
            requested_file_count=len(file_ids),
            io_parallelism=strategy.io_parallelism,
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
                node_logger.warning("docgen_input_skipped", file_id=file_id, reason="no_markdown")
                return None

            markdown_path = Path(str(raw_file["markdown_path"]))
            if not markdown_path.exists():
                node_logger.warning("docgen_input_skipped", file_id=file_id, reason="not_found")
                return None

            async with strategy.io_semaphore:
                content = await asyncio.to_thread(markdown_path.read_text, encoding="utf-8")
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
        node_logger.info("docgen_loading_inputs_completed", file_count=len(raw_chunks), load_ms=load_ms)
        return {"raw_chunks": raw_chunks, "load_ms": load_ms}

    return load_files_node
