"""Prepare cacheable visual evidence before file semantic routing."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.time import utcnow
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen_multimodal.lib.visual_evidence import generate_visual_evidence
from app.workflows.digest.docgen_multimodal.state import MultimodalDocGenState

logger = structlog.get_logger(__name__)


def build_prepare_visual_evidence_node(*, context: WorkflowContext):
    """Build the non-blocking visual-understanding node for the new lane."""

    async def prepare_visual_evidence_node(state: MultimodalDocGenState) -> dict:
        started_at = perf_counter()
        raw_shared_inputs = state.get("shared_inputs")
        if raw_shared_inputs is None:
            return {
                "visual_evidence_items": [],
                "visual_evidence_failures": [],
                "visual_evidence_metrics": {"skip_reason": "missing_shared_inputs"},
                "visual_evidence_ms": 0,
                "visual_evidence_llm_calls": 0,
                "llm_calls_total": 0,
            }

        material_context = (
            raw_shared_inputs
            if isinstance(raw_shared_inputs, DigestMaterialContext)
            else DigestMaterialContext.model_validate(raw_shared_inputs)
        )
        def write_progress(stage: str, description: str) -> None:
            update_knowledge_build_status(
                state["course_id"],
                requested_at=state["requested_at"],
                build_group_id=state.get("build_group_id") or None,
                status="running",
                stage=stage,
                image_understanding_enabled=True,
                current_stage_description=description,
            )

        async def report_progress(completed: int, total: int) -> None:
            write_progress("visual_evidence_progress", f"正在理解资料图片 · {completed}/{total}")
            await publish_docgen_progress(
                context,
                state=state,
                stage="visual_evidence_progress",
                payload={"completed_image_count": completed, "total_image_count": total},
            )

        write_progress("visual_evidence_started", "正在查找并准备资料图片。")
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={"stage": "visual_evidence_started", "summary": "开始理解资料图片，已有的理解结果会直接复用。", "created_at": utcnow()},
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="visual_evidence_started",
            payload={
                "source_count": len(material_context.source_packets),
                "section_count": len(material_context.section_packets),
                "model_slot": "light",
                "model_name": str(state.get("visual_model_name") or ""),
                "image_detail": "high",
            },
        )

        try:
            visual_result = await generate_visual_evidence(
                course_id=state["course_id"],
                material_context=material_context,
                visual_model_name=str(state.get("visual_model_name") or ""),
                on_progress=report_progress,
                extra_metadata={
                    "build_session_id": state.get("build_session_id") or "",
                    "planner_session_id": state.get("planner_session_id") or "",
                    "confirmed_plan_id": state.get("confirmed_plan_id") or "",
                    "digest_mode": state.get("digest_mode") or "",
                },
            )
        except Exception as exc:
            # Visual understanding is an enhancement. A total visual-stage
            # failure must preserve the original text-only generation path.
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            logger.exception(
                "docgen_multimodal_visual_evidence_failed",
                course_id=state.get("course_id"),
                error=str(exc),
            )
            metrics = {
                "failure": type(exc).__name__,
                "meaningful_image_count": 0,
                "meaningless_image_count": 0,
                "visual_evidence_llm_call_count": 0,
            }
            write_progress("visual_evidence_degraded", "图片理解暂不可用，继续分析文本。")
            await publish_docgen_progress(
                context,
                state=state,
                stage="visual_evidence_degraded",
                payload=metrics,
            )
            return {
                "visual_evidence_items": [],
                "visual_evidence_failures": [
                    {
                        "image_id": "",
                        "file_id": "",
                        "section_ref": "",
                        "reason": f"visual_stage_failed:{type(exc).__name__}",
                    }
                ],
                "visual_evidence_metrics": metrics,
                "visual_evidence_ms": elapsed_ms,
                "visual_evidence_llm_calls": 0,
                "llm_calls_total": 0,
            }

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        metrics = visual_result.metrics()
        description = (
            f"图片理解完成，保留 {visual_result.meaningful_count} 张教学相关图片，正在继续分析资料。"
            if visual_result.discovered_count
            else "资料中未发现可用图片，继续分析文本。"
        )
        write_progress("visual_evidence_ready", description)
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={"stage": "visual_evidence_ready", "summary": description, "created_at": utcnow()},
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="visual_evidence_ready",
            payload=metrics,
        )
        return {
            "visual_evidence_items": [item.model_dump(mode="json") for item in visual_result.evidence],
            "visual_evidence_failures": [item.to_dict() for item in visual_result.failures],
            "visual_evidence_metrics": metrics,
            "visual_evidence_ms": elapsed_ms,
            "visual_evidence_llm_calls": visual_result.llm_call_count,
            "llm_calls_total": visual_result.llm_call_count,
        }

    return prepare_visual_evidence_node


__all__ = ["build_prepare_visual_evidence_node"]
