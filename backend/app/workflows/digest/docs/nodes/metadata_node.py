"""Fan-Out 子节点：为单章提取元数据（summary + tags）。"""

from __future__ import annotations

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import extract_metadata

logger = structlog.get_logger()


def build_extract_metadata_node(*, context: WorkflowContext):
    """构建单章元数据提取 Fan-Out 子节点。

    返回 ``chapter_metadatas`` 列表（单元素），由 operator.add 汇聚。
    """

    async def extract_metadata_node(state: dict) -> dict:
        node_logger = context.get_logger().bind(node="extract_metadata")

        reviewed = state["reviewed"]
        ch_index = reviewed["chapter_index"]
        ch_title = reviewed["title"]
        markdown = reviewed["markdown"]

        node_logger.info("metadata_start", chapter_index=ch_index)

        meta = await extract_metadata(markdown)

        node_logger.info(
            "metadata_done", chapter_index=ch_index,
            summary_len=len(meta.get("summary", "")),
            tag_count=len(meta.get("tags", [])),
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
        }

    return extract_metadata_node
