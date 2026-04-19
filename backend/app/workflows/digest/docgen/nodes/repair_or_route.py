"""Apply safe review repairs and record heavier routes."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.repair import repair_or_route_review_actions
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_repair_or_route_node(*, context: WorkflowContext):
    async def repair_or_route_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        reviewed = [
            ReviewedChapterDraft.model_validate(item)
            for item in list(state.get("reviewed_chapter_drafts") or [])
        ]
        if not reviewed:
            return {"error": "没有可回流处理的复核章节。"}
        actions = [
            ReviewAction.model_validate(item)
            for item in list(state.get("review_actions") or [])
        ]
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="repairing_or_routing",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在处理复核回流动作：MVP 只执行安全表层修补，其余记录为 warning。",
        )
        # MVP 不在这里自动重写章节；复杂回流先结构化记录，避免修复阶段引入新的内容污染。
        repaired, updated_actions, unresolved = repair_or_route_review_actions(
            reviewed_chapters=reviewed,
            review_actions=actions,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="repair_routed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"复核回流处理完成，未自动回流项 {len(unresolved)} 条。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "repair_routed",
                "summary": f"复核回流动作已记录，未自动处理 {len(unresolved)} 条。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="repair_routed",
            payload={
                "review_action_count": len(updated_actions),
                "unresolved_warning_count": len(unresolved),
            },
        )
        return {
            "reviewed_chapter_drafts": [item.model_dump(mode="json") for item in repaired],
            "review_actions": [item.model_dump(mode="json") for item in updated_actions],
            "unresolved_warnings": unresolved,
            "repair_ms": elapsed_ms,
        }

    return repair_or_route_node


__all__ = ["build_repair_or_route_node"]
