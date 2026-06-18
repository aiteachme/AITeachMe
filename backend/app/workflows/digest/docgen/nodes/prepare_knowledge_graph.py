"""Prepare DocGen KG prefetch after review/repair and before document publish."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from app.shared.infra.database import managed_session
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.shared.infra.settings import get_settings
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.live_stream import publish_workflow_stream_event
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.pipeline_artifacts import build_docgen_kg_draft
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import persist_docgen_kg_draft_graph_early
from app.workflows.digest.kg_doc_sync.lib.prefetch import (
    await_docgen_kg_prefetch,
    snapshot_docgen_kg_prefetch,
    start_docgen_kg_prefetch,
)

_QUALITY_READY_RECHECK_WAIT_S = 4.0


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    return [dict(item) for item in items if isinstance(item, dict)]


def _kg_manifest(state: DocGenState) -> dict[str, object]:
    return {
        "intent_profile": dict(state.get("intent_profile") or state.get("intent_core") or {}),
        "intent_enhanced": dict(state.get("intent_enhanced") or {}),
        "summary_enhanced": dict(state.get("summary_enhanced") or {}),
        "user_profile": dict(state.get("user_profile") or {}),
        "chapters_enhanced": list(state.get("chapters_enhanced") or []),
        "chapter_task_seeds": list(state.get("chapter_task_seeds") or []),
        "chapter_execution_briefs": list(state.get("chapter_execution_briefs") or []),
        "chapter_generation_plan": dict(state.get("chapter_generation_plan") or {}),
        "chapter_generation_plan_seed": dict(state.get("chapter_generation_plan_seed") or {}),
        "document_backbone_snapshot": dict(state.get("document_backbone") or {}),
        "guideline": dict(state.get("guideline") or {}),
        "dispatch_table": dict(state.get("dispatch_table") or {}),
        "preliminary_kg": dict(state.get("preliminary_kg") or {}),
        "kg_refinement_items": list(state.get("kg_refinement_items") or []),
        "docgen_kg_draft": dict(state.get("docgen_kg_draft") or {}),
        "review_decision": str(state.get("review_decision") or ""),
        "review_actions": list(state.get("review_actions") or []),
        "chapter_metadatas": list(state.get("chapter_metadatas") or []),
        "final_chapter_titles": list(state.get("final_chapter_titles") or []),
        "title_review_report": dict(state.get("title_review_report") or {}),
        "merged_markdown_chars": len(str(state.get("merged_markdown") or "")),
        "digest_mode": str(state.get("digest_mode") or ""),
    }


def _chapters_for_prefetch(state: DocGenState) -> list[dict[str, Any]]:
    metadatas = _as_dict_list(state.get("chapter_metadatas"))
    reviewed = _as_dict_list(state.get("reviewed_chapter_drafts"))
    enhanced = _as_dict_list(state.get("enhanced_chapter_drafts"))
    drafts = reviewed or enhanced or _as_dict_list(state.get("chapter_drafts"))
    if not metadatas:
        return drafts
    if not drafts:
        return sorted(metadatas, key=lambda item: int(item.get("chapter_index", 0) or 0))

    drafts_by_index = {
        int(item.get("chapter_index", 0) or fallback_index): dict(item)
        for fallback_index, item in enumerate(drafts, start=1)
    }
    merged: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for fallback_index, metadata in enumerate(metadatas, start=1):
        chapter_index = int(metadata.get("chapter_index", 0) or fallback_index)
        base = dict(drafts_by_index.get(chapter_index, {}))
        base.update(metadata)
        if not str(base.get("markdown") or "").strip() and chapter_index in drafts_by_index:
            base["markdown"] = str(drafts_by_index[chapter_index].get("markdown") or "")
        base["chapter_index"] = chapter_index
        merged.append(base)
        seen_indices.add(chapter_index)
    for chapter_index in sorted(set(drafts_by_index) - seen_indices):
        merged.append(drafts_by_index[chapter_index])
    return sorted(merged, key=lambda item: int(item.get("chapter_index", 0) or 0))


async def _await_prefetch(
    *,
    course_id: str,
    build_session_id: str,
    wait_timeout_s: float | None = None,
) -> dict[str, int | str]:
    kwargs: dict[str, object] = {}
    if wait_timeout_s is not None:
        kwargs["wait_timeout_s"] = wait_timeout_s
    return await await_docgen_kg_prefetch(
        course_id=course_id,
        build_session_id=build_session_id,
        **kwargs,
    )


def _persist_draft_graph_before_publish(*, course_id: str, draft: dict[str, Any]) -> dict[str, object]:
    if not bool(draft.get("quality_ready") or draft.get("fast_visible_ready")):
        return {
            "ok": True,
            "skipped": True,
            "skip_reason": "docgen_kg_draft_quality_not_ready",
        }
    with managed_session() as session:
        return persist_docgen_kg_draft_graph_early(
            session,
            course_id=course_id,
            docgen_kg_draft=draft,
            require_quality_ready=not bool(draft.get("fast_visible_ready")),
        )


def _publish_graph_lane_preview(
    *,
    course_id: str,
    state: DocGenState,
    metrics: dict[str, object],
    early_persist_metrics: dict[str, object],
) -> None:
    unit_count = int(early_persist_metrics.get("unit_count", 0) or 0)
    edge_count = int(early_persist_metrics.get("edge_count", 0) or 0)
    if unit_count <= 0:
        return
    graph_metrics = {
        **dict(metrics),
        "graph_active_unit_count": unit_count,
        "graph_active_edge_count": edge_count,
        "doc_sync_unit_changes": unit_count,
        "doc_sync_edge_changes": edge_count,
        "revision_no": int(early_persist_metrics.get("build_revision_no", 0) or 0),
    }
    update_knowledge_build_status(
        course_id,
        requested_at=state["requested_at"],
        build_kind="graph",
        status="running",
        stage="knowledge_graph_prefetch_prepared",
        digest_mode=state.get("digest_mode") or None,
        metrics=graph_metrics,
        current_stage_description="可预览知识图谱已写入，文档发布后将继续补齐证据和关系。",
    )


def build_prepare_knowledge_graph_node(*, context: WorkflowContext):
    """Build the DocGen-side KG preparation node.

    This node makes the DocGen sidecar extraction visible right after
    review/repair, so merge/title/publish can continue while a queryable graph
    skeleton is already available. Source refs, catch-up extraction, and
    deprecated cleanup remain owned by final sync.
    """

    async def prepare_knowledge_graph_node(state: DocGenState) -> dict[str, object]:
        started_at = perf_counter()
        settings = get_settings()
        course_id = state["course_id"]
        build_session_id = str(state.get("build_session_id") or "").strip()
        node_logger = context.get_logger().bind(node="prepare_knowledge_graph")

        if not settings.knowledge_graph.sync_after_docgen or not settings.knowledge_graph.prefetch_during_docgen:
            metrics = {
                "prefetch_status": "skipped",
                "prefetch_section_count": 0,
                "prefetch_failed_section_count": 0,
                "prefetch_ready": 0,
            }
            draft = build_docgen_kg_draft(
                preliminary_kg=dict(state.get("preliminary_kg") or {}),
                kg_refinement_items=list(state.get("kg_refinement_items") or []),
                reviewed_chapters=_chapters_for_prefetch(state),
                prefetched_records=[],
                prefetch_metrics=metrics,
                stage="prepare_knowledge_graph",
            )
            quality_audit = dict(draft.get("quality_audit") or {})
            metrics.update(
                {
                    "docgen_kg_draft_node_count": int(draft.get("node_count", 0) or 0),
                    "docgen_kg_draft_edge_count": int(draft.get("edge_count", 0) or 0),
                    "docgen_kg_draft_chapter_coverage_ratio": str(draft.get("chapter_coverage_ratio", 0.0)),
                    "docgen_kg_fast_visible_ready": 1 if draft.get("fast_visible_ready") else 0,
                    "docgen_kg_quality_status": str(draft.get("quality_status") or quality_audit.get("quality_status") or ""),
                    "docgen_kg_quality_score": str(draft.get("quality_score") or quality_audit.get("quality_score") or 0.0),
                    "docgen_kg_quality_warning_count": int(quality_audit.get("warning_count", 0) or 0),
                    "docgen_kg_missing_chapter_count": int(quality_audit.get("missing_chapter_count", 0) or 0),
                    "docgen_kg_edge_endpoint_issue_count": int(quality_audit.get("edge_endpoint_issue_count", 0) or 0),
                    "docgen_kg_edge_endpoint_ambiguity_count": int(quality_audit.get("edge_endpoint_ambiguity_count", 0) or 0),
                    "docgen_kg_relation_direction_issue_count": int(quality_audit.get("relation_direction_issue_count", 0) or 0),
                    "docgen_kg_valid_relation_edge_count": int(quality_audit.get("valid_relation_edge_count", 0) or 0),
                    "docgen_kg_exam_ready_unit_count": int(quality_audit.get("exam_ready_unit_count", 0) or 0),
                    "docgen_kg_profile_ready_unit_count": int(quality_audit.get("profile_ready_unit_count", 0) or 0),
                    "docgen_kg_diagnostic_unit_count": int(quality_audit.get("diagnostic_unit_count", 0) or 0),
                    "docgen_kg_structure_edge_count": int(quality_audit.get("structure_edge_count", 0) or 0),
                    "docgen_kg_examine_profile_ready": 1 if quality_audit.get("examine_profile_ready") else 0,
                }
            )
            if settings.knowledge_graph.sync_after_docgen:
                try:
                    early_persist_metrics = _persist_draft_graph_before_publish(course_id=course_id, draft=draft)
                except Exception as exc:
                    early_persist_metrics = {
                        "ok": False,
                        "skipped": True,
                        "skip_reason": "docgen_kg_draft_pre_publish_persist_failed",
                        "error": str(exc),
                    }
                    node_logger.warning(
                        "docgen_kg_draft_pre_publish_persist_failed",
                        course_id=course_id,
                        build_session_id=build_session_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
            else:
                early_persist_metrics = {
                    "ok": True,
                    "skipped": True,
                    "skip_reason": "knowledge_graph_sync_disabled",
                }
            metrics["docgen_kg_pre_publish_unit_count"] = int(early_persist_metrics.get("unit_count", 0) or 0)
            metrics["docgen_kg_pre_publish_edge_count"] = int(early_persist_metrics.get("edge_count", 0) or 0)
            metrics["docgen_kg_pre_publish_persisted"] = 0 if early_persist_metrics.get("skipped") else 1
            _publish_graph_lane_preview(
                course_id=course_id,
                state=state,
                metrics=metrics,
                early_persist_metrics=early_persist_metrics,
            )
            if int(early_persist_metrics.get("unit_count", 0) or 0) > 0:
                publish_workflow_stream_event(
                    course_id,
                    "graph_delta",
                    {
                        "stage": "prepare_knowledge_graph",
                        "build_revision_no": int(early_persist_metrics.get("build_revision_no", 0) or 0),
                        "unit_count": int(early_persist_metrics.get("unit_count", 0) or 0),
                        "created_unit_count": int(early_persist_metrics.get("created_unit_count", 0) or 0),
                        "updated_unit_count": int(early_persist_metrics.get("updated_unit_count", 0) or 0),
                        "edge_count": int(early_persist_metrics.get("edge_count", 0) or 0),
                        "created_edge_count": int(early_persist_metrics.get("created_edge_count", 0) or 0),
                        "updated_edge_count": int(early_persist_metrics.get("updated_edge_count", 0) or 0),
                        "deprecated_edge_count": 0,
                        "emitted_at": utcnow().isoformat(),
                    },
                )
            update_knowledge_build_status(
                course_id,
                requested_at=state["requested_at"],
                status="running",
                stage="knowledge_graph_prefetch_prepared",
                digest_mode=state.get("digest_mode") or None,
                metrics=dict(metrics),
                current_stage_description="知识图谱规则候选已准备，后续会在最终同步中补齐并固化。",
            )
            return {
                "kg_prefetch_status": "skipped",
                "kg_prefetch_metrics": metrics,
                "kg_prefetch_ready": False,
                "docgen_kg_draft": draft,
                "kg_draft_early_persist_metrics": early_persist_metrics,
                "graph_prepare_ms": int((perf_counter() - started_at) * 1000),
            }

        update_knowledge_build_status(
            course_id,
            requested_at=state["requested_at"],
            status="running",
            stage="preparing_knowledge_graph",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在等待知识图谱预抽取完成，准备在发布前提前展示候选图谱。",
        )

        final_title_changed = int(dict(state.get("title_review_report") or {}).get("changed_count", 0) or 0) > 0
        final_chapters = _as_dict_list(state.get("chapter_metadatas"))
        if final_title_changed and final_chapters:
            refreshed = start_docgen_kg_prefetch(
                course_id=course_id,
                build_session_id=build_session_id,
                chapters=_chapters_for_prefetch(state),
                document_backbone=dict(state.get("document_backbone") or {}),
                docgen_manifest={**_kg_manifest(state), "kg_prefetch_phase": "final_locked_markdown"},
            )
            metrics = (
                await _await_prefetch(course_id=course_id, build_session_id=build_session_id)
                if refreshed
                else {
                    "prefetch_status": "missing",
                    "prefetch_section_count": 0,
                    "prefetch_failed_section_count": 0,
                    "prefetch_ready": 0,
                }
            )
        else:
            metrics = await _await_prefetch(course_id=course_id, build_session_id=build_session_id)
        if metrics.get("prefetch_status") == "missing":
            chapters = _chapters_for_prefetch(state)
            restarted = start_docgen_kg_prefetch(
                course_id=course_id,
                build_session_id=build_session_id,
                chapters=chapters,
                document_backbone=dict(state.get("document_backbone") or {}),
                docgen_manifest={**_kg_manifest(state), "kg_prefetch_phase": "final_locked_markdown" if final_chapters else "prepare_fallback"},
            )
            if restarted:
                metrics = await _await_prefetch(course_id=course_id, build_session_id=build_session_id)
            else:
                metrics = {
                    "prefetch_status": "not_started",
                    "prefetch_section_count": 0,
                    "prefetch_failed_section_count": 0,
                    "prefetch_ready": 0,
                }

        records, snapshot_metrics = snapshot_docgen_kg_prefetch(
            course_id=course_id,
            build_session_id=build_session_id,
        )
        if snapshot_metrics.get("prefetch_status") != "missing" or metrics.get("prefetch_status") == "missing":
            metrics = {**dict(metrics), **dict(snapshot_metrics)}
        prefetch_status = str(metrics.get("prefetch_status") or "").strip() or "unknown"
        prefetch_ready = bool(int(metrics.get("prefetch_ready", 0) or 0))
        draft = build_docgen_kg_draft(
            preliminary_kg=dict(state.get("preliminary_kg") or {}),
            kg_refinement_items=list(state.get("kg_refinement_items") or []),
            reviewed_chapters=_chapters_for_prefetch(state),
            prefetched_records=records,
            prefetch_metrics=metrics,
            stage="prepare_knowledge_graph",
        )
        quality_recheck_waited = False
        if not draft.get("quality_ready") and not prefetch_ready:
            quality_recheck_waited = True
            recheck_metrics = await _await_prefetch(
                course_id=course_id,
                build_session_id=build_session_id,
                wait_timeout_s=_QUALITY_READY_RECHECK_WAIT_S,
            )
            recheck_records, recheck_snapshot_metrics = snapshot_docgen_kg_prefetch(
                course_id=course_id,
                build_session_id=build_session_id,
            )
            metrics = {**dict(metrics), **dict(recheck_metrics)}
            if (
                recheck_snapshot_metrics.get("prefetch_status") != "missing"
                or recheck_metrics.get("prefetch_status") == "missing"
            ):
                metrics = {**dict(metrics), **dict(recheck_snapshot_metrics)}
                records = recheck_records
            prefetch_status = str(metrics.get("prefetch_status") or "").strip() or "unknown"
            prefetch_ready = bool(int(metrics.get("prefetch_ready", 0) or 0))
            draft = build_docgen_kg_draft(
                preliminary_kg=dict(state.get("preliminary_kg") or {}),
                kg_refinement_items=list(state.get("kg_refinement_items") or []),
                reviewed_chapters=_chapters_for_prefetch(state),
                prefetched_records=records,
                prefetch_metrics=metrics,
                stage="prepare_knowledge_graph",
            )
        metrics["docgen_kg_draft_node_count"] = int(draft.get("node_count", 0) or 0)
        metrics["docgen_kg_draft_edge_count"] = int(draft.get("edge_count", 0) or 0)
        metrics["docgen_kg_draft_chapter_coverage_ratio"] = str(draft.get("chapter_coverage_ratio", 0.0))
        metrics["docgen_kg_fast_visible_ready"] = 1 if draft.get("fast_visible_ready") else 0
        metrics["docgen_kg_quality_recheck_waited"] = 1 if quality_recheck_waited else 0
        quality_audit = dict(draft.get("quality_audit") or {})
        metrics["docgen_kg_quality_status"] = str(draft.get("quality_status") or quality_audit.get("quality_status") or "")
        metrics["docgen_kg_quality_score"] = str(draft.get("quality_score") or quality_audit.get("quality_score") or 0.0)
        metrics["docgen_kg_quality_warning_count"] = int(quality_audit.get("warning_count", 0) or 0)
        metrics["docgen_kg_missing_chapter_count"] = int(quality_audit.get("missing_chapter_count", 0) or 0)
        metrics["docgen_kg_edge_endpoint_issue_count"] = int(quality_audit.get("edge_endpoint_issue_count", 0) or 0)
        metrics["docgen_kg_edge_endpoint_ambiguity_count"] = int(quality_audit.get("edge_endpoint_ambiguity_count", 0) or 0)
        metrics["docgen_kg_relation_direction_issue_count"] = int(quality_audit.get("relation_direction_issue_count", 0) or 0)
        metrics["docgen_kg_valid_relation_edge_count"] = int(quality_audit.get("valid_relation_edge_count", 0) or 0)
        metrics["docgen_kg_exam_ready_unit_count"] = int(quality_audit.get("exam_ready_unit_count", 0) or 0)
        metrics["docgen_kg_profile_ready_unit_count"] = int(quality_audit.get("profile_ready_unit_count", 0) or 0)
        metrics["docgen_kg_diagnostic_unit_count"] = int(quality_audit.get("diagnostic_unit_count", 0) or 0)
        metrics["docgen_kg_structure_edge_count"] = int(quality_audit.get("structure_edge_count", 0) or 0)
        metrics["docgen_kg_examine_profile_ready"] = 1 if quality_audit.get("examine_profile_ready") else 0
        try:
            early_persist_metrics = _persist_draft_graph_before_publish(course_id=course_id, draft=draft)
        except Exception as exc:
            early_persist_metrics = {
                "ok": False,
                "skipped": True,
                "skip_reason": "docgen_kg_draft_pre_publish_persist_failed",
                "error": str(exc),
            }
            node_logger.warning(
                "docgen_kg_draft_pre_publish_persist_failed",
                course_id=course_id,
                build_session_id=build_session_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
        metrics["docgen_kg_pre_publish_unit_count"] = int(early_persist_metrics.get("unit_count", 0) or 0)
        metrics["docgen_kg_pre_publish_edge_count"] = int(early_persist_metrics.get("edge_count", 0) or 0)
        metrics["docgen_kg_pre_publish_persisted"] = 0 if early_persist_metrics.get("skipped") else 1
        _publish_graph_lane_preview(
            course_id=course_id,
            state=state,
            metrics=metrics,
            early_persist_metrics=early_persist_metrics,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            course_id,
            requested_at=state["requested_at"],
            status="running",
            stage="knowledge_graph_prefetch_prepared",
            digest_mode=state.get("digest_mode") or None,
            metrics=dict(metrics),
            current_stage_description=(
                "知识图谱候选已准备，文档收口和最终固化将继续进行。"
                if draft.get("fast_visible_ready")
                else "知识图谱候选已准备但仍需最终同步补齐，文档收口将继续进行。"
            ),
        )

        append_knowledge_build_recent_event(
            course_id,
            requested_at=state["requested_at"],
            event={
                "stage": "knowledge_graph_prefetch_prepared",
                "summary": (
                    f"知识图谱预抽取准备完成，状态 {prefetch_status}，"
                    f"候选 section {int(metrics.get('prefetch_section_count', 0) or 0)} 个，"
                    f"草稿节点 {int(draft.get('node_count', 0) or 0)} 个，"
                    f"质量状态 {metrics['docgen_kg_quality_status'] or 'unknown'}。"
                ),
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="knowledge_graph_prefetch_prepared",
            payload={
                "kg_prefetch_status": prefetch_status,
                "kg_prefetch_ready": prefetch_ready,
                "kg_prefetch_metrics": dict(metrics),
                "docgen_kg_draft_node_count": int(draft.get("node_count", 0) or 0),
                "docgen_kg_draft_edge_count": int(draft.get("edge_count", 0) or 0),
                "docgen_kg_fast_visible_ready": bool(draft.get("fast_visible_ready")),
                "docgen_kg_chapter_coverage_ratio": draft.get("chapter_coverage_ratio", 0.0),
                "docgen_kg_quality_status": draft.get("quality_status"),
                "docgen_kg_quality_score": draft.get("quality_score"),
                "docgen_kg_quality_audit": quality_audit,
                "docgen_kg_exam_ready_unit_count": int(quality_audit.get("exam_ready_unit_count", 0) or 0),
                "docgen_kg_profile_ready_unit_count": int(quality_audit.get("profile_ready_unit_count", 0) or 0),
                "docgen_kg_diagnostic_unit_count": int(quality_audit.get("diagnostic_unit_count", 0) or 0),
                "docgen_kg_structure_edge_count": int(quality_audit.get("structure_edge_count", 0) or 0),
                "docgen_kg_edge_endpoint_ambiguity_count": int(quality_audit.get("edge_endpoint_ambiguity_count", 0) or 0),
                "docgen_kg_relation_direction_issue_count": int(quality_audit.get("relation_direction_issue_count", 0) or 0),
                "docgen_kg_valid_relation_edge_count": int(quality_audit.get("valid_relation_edge_count", 0) or 0),
                "docgen_kg_examine_profile_ready": bool(quality_audit.get("examine_profile_ready")),
                "docgen_kg_pre_publish_unit_count": int(early_persist_metrics.get("unit_count", 0) or 0),
                "docgen_kg_pre_publish_edge_count": int(early_persist_metrics.get("edge_count", 0) or 0),
                "docgen_kg_pre_publish_persisted": not bool(early_persist_metrics.get("skipped")),
            },
        )
        if int(early_persist_metrics.get("unit_count", 0) or 0) > 0:
            publish_workflow_stream_event(
                course_id,
                "graph_delta",
                {
                    "stage": "prepare_knowledge_graph",
                    "build_revision_no": int(early_persist_metrics.get("build_revision_no", 0) or 0),
                    "unit_count": int(early_persist_metrics.get("unit_count", 0) or 0),
                    "created_unit_count": int(early_persist_metrics.get("created_unit_count", 0) or 0),
                    "updated_unit_count": int(early_persist_metrics.get("updated_unit_count", 0) or 0),
                    "edge_count": int(early_persist_metrics.get("edge_count", 0) or 0),
                    "created_edge_count": int(early_persist_metrics.get("created_edge_count", 0) or 0),
                    "updated_edge_count": int(early_persist_metrics.get("updated_edge_count", 0) or 0),
                    "deprecated_edge_count": 0,
                    "emitted_at": utcnow().isoformat(),
                },
            )

        return {
            "kg_prefetch_status": prefetch_status,
            "kg_prefetch_metrics": dict(metrics),
            "kg_prefetch_ready": prefetch_ready,
            "docgen_kg_draft": draft,
            "kg_draft_early_persist_metrics": early_persist_metrics,
            "graph_prepare_ms": elapsed_ms,
        }

    return prepare_knowledge_graph_node


__all__ = ["build_prepare_knowledge_graph_node"]
