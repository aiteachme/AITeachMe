"""节点：从数据库加载原始 Markdown 文件。

Reads DB: ``docgen_job`` and ``raw_file``.
Writes DB: ``docgen_job`` progress.
Writes FS: reads persisted ingest markdown files.
Idempotency: repeated runs read the same markdown inputs and refresh job progress only.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.core.database import managed_session
from app.models.raw_file import RawFile
from app.repositories.knowledge import docgen_repo
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def build_load_files_node(*, context: WorkflowContext):
    """构建文件加载节点。"""

    async def load_files_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="load_files")
        node_logger.info("load_files_started")

        file_ids = state["file_ids"]
        job_id = state["job_id"]

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="loading", progress=2,
            )

        raw_chunks: list[dict] = []
        with managed_session() as session:
            for file_id in file_ids:
                raw_file = session.get(RawFile, file_id)
                if raw_file is None or not raw_file.markdown_path:
                    node_logger.warning("file_skipped", file_id=file_id, reason="no_markdown")
                    continue

                md_path = Path(raw_file.markdown_path)
                if not md_path.exists():
                    node_logger.warning("file_skipped", file_id=file_id, reason="not_found")
                    continue

                raw_chunks.append({
                    "file_id": file_id,
                    "content": md_path.read_text(encoding="utf-8"),
                    "source_filename": raw_file.filename,
                })

        if not raw_chunks:
            return {"error": "没有可用的 Markdown 文件。"}

        node_logger.info("load_files_done", count=len(raw_chunks))
        return {"raw_chunks": raw_chunks}

    return load_files_node
