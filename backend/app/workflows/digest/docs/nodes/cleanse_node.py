"""Clean and normalize markdown inputs for knowledge docs generation."""

from __future__ import annotations

import asyncio
import json
from time import perf_counter

import structlog

from app.utils.path_helpers import build_docgen_intermediate_latest_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.cleanse_service import (
    llm_heal_full,
    stitch_sentences,
)
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_cleanse_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the cleanse node (simplified - shared layer already normalized)."""

    async def cleanse_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="cleanse")
        raw_chunks = state.get("raw_chunks", [])
        node_logger.info(
            "docgen_cleaning_inputs",
            raw_chunk_count=len(raw_chunks),
            skip_llm_cleanse_for_clean_markdown=strategy.skip_llm_cleanse_for_clean_markdown,
        )

        subject = state["subject"]
        # 共享层已经做了基础规范化，这里只做教学性增强
        pre_healed = []
        for chunk in raw_chunks:
            # 只做句子拼接（教学性增强）
            cleaned = stitch_sentences(chunk["content"])
            pre_healed.append({**chunk, "content": cleaned})

        async def _heal(chunk: dict) -> dict:
            decision = strategy.decide_cleanse(
                source_filename=chunk["source_filename"],
                content=chunk["content"],
            )
            if not decision.use_llm:
                return {
                    **chunk,
                    "cleanse_reason": decision.reason,
                    "llm_calls_total": 0,
                    "llm_calls_skipped": 1,
                }

            healed, call_count = await llm_heal_full(chunk["content"])
            return {
                **chunk,
                "content": healed,
                "cleanse_reason": decision.reason,
                "llm_calls_total": call_count,
                "llm_calls_skipped": 0,
            }

        clean_chunks = list(await asyncio.gather(*(_heal(chunk) for chunk in pre_healed)))
        llm_calls_total = sum(int(chunk.get("llm_calls_total", 0)) for chunk in clean_chunks)
        llm_calls_skipped = sum(int(chunk.get("llm_calls_skipped", 0)) for chunk in clean_chunks)

        intermediate_dir = build_docgen_intermediate_latest_dir(subject)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for index, chunk in enumerate(clean_chunks):
            path = intermediate_dir / f"clean_{index:02d}_{chunk['source_filename']}.md"
            path.write_text(chunk["content"], encoding="utf-8")

        summary_path = intermediate_dir / "cleanse_summary.json"
        summary_path.write_text(
            json.dumps(
                [
                    {
                        "index": index,
                        "file_id": chunk["file_id"],
                        "filename": chunk["source_filename"],
                        "chars": len(chunk["content"]),
                    }
                    for index, chunk in enumerate(clean_chunks)
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        cleanse_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_cleaning_inputs_completed",
            chunk_count=len(clean_chunks),
            cleanse_ms=cleanse_ms,
            llm_calls_total=llm_calls_total,
            llm_calls_skipped=llm_calls_skipped,
        )
        return {
            "clean_chunks": clean_chunks,
            "cleanse_ms": cleanse_ms,
            "llm_calls_total": llm_calls_total,
            "llm_calls_skipped": llm_calls_skipped,
        }

    return cleanse_node
