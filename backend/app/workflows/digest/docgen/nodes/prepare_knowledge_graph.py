"""Prepare DocGen KG prefetch after review/repair and before document publish."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_status,
)
from app.shared.infra.settings import get_settings
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.pipeline_artifacts import build_docgen_kg_draft
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.prefetch import (
    snapshot_docgen_kg_prefetch,
    start_docgen_kg_prefetch,
)


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


def _deferred_pre_publish_metrics(*, sync_after_docgen: bool) -> dict[str, object]:
    """Keep the legacy state shape without exposing KG rows before publish."""

    return {
        "ok": True,
        "skipped": True,
        "skip_reason": (
            "deferred_until_document_publish"
            if sync_after_docgen
            else "knowledge_graph_sync_disabled"
        ),
        "persisted": 0,
        "unit_count": 0,
        "created_unit_count": 0,
        "updated_unit_count": 0,
        "edge_count": 0,
        "created_edge_count": 0,
        "updated_edge_count": 0,
    }


def build_prepare_knowledge_graph_node(*, context: WorkflowContext):
    """Build the DocGen-side KG preparation node.

    This node finishes the DocGen sidecar draft after review/repair. The draft
    remains in workflow state until the document is published; only the final
    sync may persist query-visible graph rows.
    """

    async def prepare_knowledge_graph_node(state: DocGenState) -> dict[str, object]:
        started_at = perf_counter()
        settings = get_settings()
        course_id = state["course_id"]
        build_group_id = str(state.get("build_group_id") or "").strip()
        build_session_id = str(state.get("build_session_id") or "").strip()
        node_logger = context.get_logger().bind(node="prepare_knowledge_graph")

        def finalize_failure_result(
            *,
            error: str,
            cancel_after_rollback: bool,
            prefetch_status: str,
            prefetch_metrics: dict[str, object],
            prefetch_ready: bool,
            draft: dict[str, Any],
            early_persist_metrics: dict[str, object],
        ) -> dict[str, object]:
            return {
                "error": error,
                "cancel_after_rollback": cancel_after_rollback,
                "kg_prefetch_status": prefetch_status,
                "kg_prefetch_metrics": dict(prefetch_metrics),
                "kg_prefetch_ready": prefetch_ready,
                "docgen_kg_draft": draft,
                "kg_draft_early_persist_metrics": dict(early_persist_metrics),
                "graph_prepare_ms": int((perf_counter() - started_at) * 1000),
            }

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
            early_persist_metrics = _deferred_pre_publish_metrics(
                sync_after_docgen=settings.knowledge_graph.sync_after_docgen
            )
            try:
                metrics["docgen_kg_pre_publish_unit_count"] = 0
                metrics["docgen_kg_pre_publish_edge_count"] = 0
                metrics["docgen_kg_pre_publish_persisted"] = 0
                update_knowledge_build_status(
                    course_id,
                    requested_at=state["requested_at"],
                    build_group_id=build_group_id,
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
            except asyncio.CancelledError:
                node_logger.info(
                    "knowledge_graph_prepare_finalize_cancelled",
                    course_id=course_id,
                    build_session_id=build_session_id,
                )
                return finalize_failure_result(
                    error="knowledge_build_cancelled",
                    cancel_after_rollback=True,
                    prefetch_status="skipped",
                    prefetch_metrics=metrics,
                    prefetch_ready=False,
                    draft=draft,
                    early_persist_metrics=early_persist_metrics,
                )
            except Exception as exc:
                node_logger.warning(
                    "knowledge_graph_prepare_finalize_failed",
                    course_id=course_id,
                    build_session_id=build_session_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return finalize_failure_result(
                    error="knowledge_graph_prepare_finalize_failed",
                    cancel_after_rollback=False,
                    prefetch_status="skipped",
                    prefetch_metrics=metrics,
                    prefetch_ready=False,
                    draft=draft,
                    early_persist_metrics=early_persist_metrics,
                )

        update_knowledge_build_status(
            course_id,
            requested_at=state["requested_at"],
            build_group_id=build_group_id,
            status="running",
            stage="preparing_knowledge_graph",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在启动最终知识图谱预抽取，文档发布将与抽取并行推进。",
        )

        final_chapters = _as_dict_list(state.get("chapter_metadatas"))
        if final_chapters:
            # Earlier chapter-side prefetches are speculative: whole-book review,
            # repair and final title locking may all change their section hashes.
            # Refresh from the exact publish payload so final graph sync can reuse
            # the work instead of extracting the published document a second time.
            start_docgen_kg_prefetch(
                course_id=course_id,
                build_session_id=build_session_id,
                chapters=_chapters_for_prefetch(state),
                document_backbone=dict(state.get("document_backbone") or {}),
                docgen_manifest={**_kg_manifest(state), "kg_prefetch_phase": "final_locked_markdown"},
            )

        records, metrics = snapshot_docgen_kg_prefetch(
            course_id=course_id,
            build_session_id=build_session_id,
        )
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
                records, metrics = snapshot_docgen_kg_prefetch(
                    course_id=course_id,
                    build_session_id=build_session_id,
                )
            else:
                records = []
                metrics = {
                    "prefetch_status": "not_started",
                    "prefetch_section_count": 0,
                    "prefetch_failed_section_count": 0,
                    "prefetch_ready": 0,
                }

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
        metrics["docgen_kg_quality_recheck_waited"] = 0
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
        early_persist_metrics = _deferred_pre_publish_metrics(
            sync_after_docgen=settings.knowledge_graph.sync_after_docgen
        )
        try:
            metrics["docgen_kg_pre_publish_unit_count"] = 0
            metrics["docgen_kg_pre_publish_edge_count"] = 0
            metrics["docgen_kg_pre_publish_persisted"] = 0
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            update_knowledge_build_status(
                course_id,
                requested_at=state["requested_at"],
                build_group_id=build_group_id,
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
                build_group_id=build_group_id or None,
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
                    "docgen_kg_edge_endpoint_ambiguity_count": int(
                        quality_audit.get("edge_endpoint_ambiguity_count", 0) or 0
                    ),
                    "docgen_kg_relation_direction_issue_count": int(
                        quality_audit.get("relation_direction_issue_count", 0) or 0
                    ),
                    "docgen_kg_valid_relation_edge_count": int(
                        quality_audit.get("valid_relation_edge_count", 0) or 0
                    ),
                    "docgen_kg_examine_profile_ready": bool(quality_audit.get("examine_profile_ready")),
                    "docgen_kg_pre_publish_unit_count": 0,
                    "docgen_kg_pre_publish_edge_count": 0,
                    "docgen_kg_pre_publish_persisted": 0,
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
        except asyncio.CancelledError:
            node_logger.info(
                "knowledge_graph_prepare_finalize_cancelled",
                course_id=course_id,
                build_session_id=build_session_id,
            )
            return finalize_failure_result(
                error="knowledge_build_cancelled",
                cancel_after_rollback=True,
                prefetch_status=prefetch_status,
                prefetch_metrics=metrics,
                prefetch_ready=prefetch_ready,
                draft=draft,
                early_persist_metrics=early_persist_metrics,
            )
        except Exception as exc:
            node_logger.warning(
                "knowledge_graph_prepare_finalize_failed",
                course_id=course_id,
                build_session_id=build_session_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return finalize_failure_result(
                error="knowledge_graph_prepare_finalize_failed",
                cancel_after_rollback=False,
                prefetch_status=prefetch_status,
                prefetch_metrics=metrics,
                prefetch_ready=prefetch_ready,
                draft=draft,
                early_persist_metrics=early_persist_metrics,
            )

    return prepare_knowledge_graph_node


__all__ = ["build_prepare_knowledge_graph_node"]
