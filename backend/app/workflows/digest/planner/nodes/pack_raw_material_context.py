"""Pack parsed source documents into raw planner context."""

from __future__ import annotations

import structlog

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.material_digest import (
    FILE_CONTEXT_TOKENS,
    build_material_digest,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def build_pack_raw_material_context_node(*, context: WorkflowContext):
    async def pack_raw_material_context_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        if not material_context.source_documents:
            return {}

        # No model call here. The planner now gives downstream prompts raw
        # source excerpts, with a per-file token cap handled by build_material_digest.
        await emit_planner_event(
            state,
            event="planner.context.started",
            detail="正在拼接原始资料上下文...",
        )
        result = await build_material_digest(material_context)
        updated_context = material_context.model_copy(update={"material_digest": result.digest})
        logger.info(
            "planner_material_context_ready",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject") or "",
            total_chars=result.total_chars,
            total_tokens=result.total_tokens,
            source_count=result.source_count,
            llm_used=result.llm_used,
            truncated=result.truncated,
            file_context_tokens=FILE_CONTEXT_TOKENS,
        )
        detail = (
            f"资料上下文已拼接（{result.source_count} 份资料，"
            f"每份最多前 {FILE_CONTEXT_TOKENS} tokens）。"
        )
        await emit_planner_event(
            state,
            event="planner.context.ready",
            detail=detail,
            payload={
                "total_chars": result.total_chars,
                "total_tokens": result.total_tokens,
                "source_count": result.source_count,
                "llm_used": result.llm_used,
                "truncated": result.truncated,
                "file_context_tokens": FILE_CONTEXT_TOKENS,
            },
        )
        return {
            "material_context": updated_context,
        }

    return pack_raw_material_context_node


__all__ = ["build_pack_raw_material_context_node"]
