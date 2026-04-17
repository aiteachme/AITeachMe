"""Summarize uploaded material into a light digest reused downstream."""

from __future__ import annotations

import structlog

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.material_digest import (
    FILE_CONTEXT_CHARS,
    build_material_digest,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def build_summarize_material_digest_node(*, context: WorkflowContext):
    async def summarize_material_digest_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        if not material_context.source_documents:
            return {}

        await emit_planner_event(
            state,
            event="planner.digest.started",
            detail="正在快速提炼资料要点...",
        )
        result = await build_material_digest(material_context)
        updated_context = material_context.model_copy(update={"material_digest": result.digest})
        logger.info(
            "planner_material_digest_ready",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject") or "",
            total_chars=result.total_chars,
            source_count=result.source_count,
            llm_used=result.llm_used,
            truncated=result.truncated,
            file_context_chars=FILE_CONTEXT_CHARS,
        )
        detail = (
            f"资料摘要已生成（{result.total_chars} 字，"
            f"{result.source_count} 份资料并行摘要）。"
        )
        await emit_planner_event(
            state,
            event="planner.digest.ready",
            detail=detail,
            payload={
                "total_chars": result.total_chars,
                "source_count": result.source_count,
                "llm_used": result.llm_used,
                "truncated": result.truncated,
            },
        )
        return {
            "material_context": updated_context,
        }

    return summarize_material_digest_node


__all__ = ["build_summarize_material_digest_node"]
