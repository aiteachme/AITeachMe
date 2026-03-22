"""Fan-Out 子节点：为单章提取元数据（summary + tags）。"""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import extract_metadata_rule_based
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_extract_metadata_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """构建单章元数据提取 Fan-Out 子节点。

    返回 ``chapter_metadatas`` 列表（单元素），由 operator.add 汇聚。
    """

    async def extract_metadata_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="extract_metadata")

        reviewed = state["reviewed"]
        ch_index = reviewed["chapter_index"]
        ch_title = reviewed["title"]
        markdown = reviewed["markdown"]
        section_titles = list(reviewed.get("section_titles", []))

        node_logger.info(
            "metadata_start",
            chapter_index=ch_index,
            metadata_fallback_llm=strategy.metadata_fallback_llm,
            max_parallel_chapters=strategy.max_parallel_chapters,
        )

        meta = extract_metadata_rule_based(markdown)
        llm_calls_total = 0
        llm_calls_skipped = 1
        if not meta.get("summary"):
            title_text = "、".join(section_titles[:3]) if section_titles else ch_title
            meta["summary"] = f"本章围绕{title_text}展开，适合复习核心概念、公式与题型。"

        metadata_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "metadata_done", chapter_index=ch_index,
            summary_len=len(meta.get("summary", "")),
            tag_count=len(meta.get("tags", [])),
            metadata_ms=metadata_ms,
            llm_calls_total=llm_calls_total,
            llm_calls_skipped=llm_calls_skipped,
        )
        return {
            "chapter_metadatas": [{
                "chapter_index": ch_index,
                "title": ch_title,
                "markdown": markdown,
                "summary": meta.get("summary", ""),
                "tags": meta.get("tags", []),
                "source_file_ids": reviewed.get("source_file_ids", []),
            }],
            "metadata_ms": metadata_ms,
            "llm_calls_total": llm_calls_total,
            "llm_calls_skipped": llm_calls_skipped,
        }

    return extract_metadata_node
