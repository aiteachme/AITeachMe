"""Apply safe review repairs and record heavier routes."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.repair import repair_or_route_review_actions
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_repair_or_route_node(*, context: WorkflowContext):
    """构建复核回流处理节点。

    当前自动执行安全的 surface/section/evidence patch；整章重写和
    重派发动作会进入 unresolved_warnings，等待更重的有限回流阶段继续实现。
    """

    async def repair_or_route_node(state: DocGenState) -> dict:
        """根据 ReviewAction 修补或记录章节问题。"""

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
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="repairing_or_routing",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在处理复核回流动作：执行安全局部修补，其余重动作记录为 warning。",
        )
        # 不在这里自动重写整章；复杂回流先结构化记录，避免修复阶段引入新的内容污染。
        repaired, updated_actions, unresolved, repair_trace = await repair_or_route_review_actions(
            reviewed_chapters=reviewed,
            review_actions=actions,
        )
        changed_count = sum(1 for item in repair_trace if item.changed)
        next_review_decision = str(state.get("review_decision") or "")
        if unresolved:
            next_review_decision = "publish_with_warnings"
        elif changed_count:
            next_review_decision = "repaired"
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="repair_routed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"复核回流处理完成，已应用 {changed_count} 项修补，待后续闭环处理 {len(unresolved)} 条。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            event={
                "stage": "repair_routed",
                "summary": f"复核回流动作已处理，实际修补 {changed_count} 项，保留 warning {len(unresolved)} 条。",
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
                "repair_trace_count": len(repair_trace),
            },
        )
        return {
            "reviewed_chapter_drafts": [item.model_dump(mode="json") for item in repaired],
            "review_actions": [item.model_dump(mode="json") for item in updated_actions],
            "review_decision": next_review_decision,
            "unresolved_warnings": unresolved,
            "repair_trace": [item.model_dump(mode="json") for item in repair_trace],
            "repair_ms": elapsed_ms,
            "llm_calls_total": sum(1 for item in actions if item.action_type in {"surface_patch", "section_patch", "evidence_patch"}),
        }

    return repair_or_route_node


__all__ = ["build_repair_or_route_node"]
