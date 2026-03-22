"""节点：数据清洗与标准化。

Reads DB: ``docgen_job``.
Writes DB: ``docgen_job`` progress.
Writes FS: writes intermediate cleaned markdown and cleanse summaries under
``docgen_intermediate/``.
Idempotency: reruns overwrite the same intermediate files for the active docgen job.
"""

from __future__ import annotations

import asyncio
import json

import structlog

from app.core.database import managed_session
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.cleanse_service import (
    llm_heal_full,
    rule_based_cleanse,
    stitch_sentences,
)
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def build_cleanse_node(*, context: WorkflowContext):
    """构建清洗节点（并发 LLM 自愈）。"""

    async def cleanse_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="cleanse")
        node_logger.info("cleanse_started")

        subject = state["subject"]
        job_id = state["job_id"]
        raw_chunks = state.get("raw_chunks", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="cleansing", progress=5,
            )

        # 规则降噪 + 缝合（纯 CPU，立即完成）
        pre_healed = []
        for chunk in raw_chunks:
            cleaned = rule_based_cleanse(chunk["content"])
            cleaned = stitch_sentences(cleaned)
            pre_healed.append({**chunk, "content": cleaned})

        # LLM 语义自愈（文件级并发）
        async def _heal(chunk: dict) -> dict:
            healed = await llm_heal_full(chunk["content"])
            return {**chunk, "content": healed}

        clean_chunks = await asyncio.gather(*(_heal(c) for c in pre_healed))
        clean_chunks = list(clean_chunks)

        # 保存中间产物
        intermediate_dir = build_docgen_intermediate_dir(subject)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(clean_chunks):
            p = intermediate_dir / f"clean_{i:02d}_{chunk['source_filename']}.md"
            p.write_text(chunk["content"], encoding="utf-8")

        summary_path = intermediate_dir / "cleanse_summary.json"
        summary_path.write_text(
            json.dumps(
                [{"i": i, "file_id": c["file_id"], "fn": c["source_filename"], "chars": len(c["content"])}
                 for i, c in enumerate(clean_chunks)],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

        with managed_session() as session:
            docgen_repo.update_docgen_job(session, job_id, progress=20)

        node_logger.info("cleanse_done", count=len(clean_chunks))
        return {"clean_chunks": clean_chunks}

    return cleanse_node
