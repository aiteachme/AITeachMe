"""Collect materials node for the DocGen lane."""

from __future__ import annotations

from app.utils.docgen_store import update_knowledge_build_status
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_collect_materials_node(*, context: WorkflowContext):
    async def collect_materials_node(state: DocGenState) -> dict:
        materials = sorted(
            list(state.get("chapter_materials", [])),
            key=lambda item: item.get("chapter_index", 0),
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="drafting",
            digest_mode=state.get("digest_mode") or None,
            processed_chunks=len(materials),
            total_chunks=len(materials),
            current_chunk=len(materials),
            current_stage_description=f"已完成 {len(materials)} 章资料研究，开始生成章节讲义。",
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="research_collection_completed",
            payload={
                "chapter_count": len(materials),
                "total_sources": sum(len(item.get("sources", []) or []) for item in materials),
                "local_hits": sum(int(item.get("local_hits", 0) or 0) for item in materials),
                "web_hits": sum(int(item.get("web_hits", 0) or 0) for item in materials),
            },
        )
        context.get_logger().bind(node="collect_materials").info(
            "docgen_material_collection_completed",
            chapter_count=len(materials),
        )
        return {}

    return collect_materials_node


__all__ = ["build_collect_materials_node"]
