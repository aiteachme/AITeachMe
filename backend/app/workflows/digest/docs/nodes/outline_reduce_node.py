"""Reduce local outline candidates into a global plan."""

from __future__ import annotations

import json
from time import perf_counter

import structlog

from app.utils.path_helpers import build_docgen_intermediate_latest_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.outline_service import (
    build_anchor_outline_tree,
    build_chapter_assignments_from_sections,
    build_fallback_outline_tree,
    build_thematic_outline_summary,
    build_thematic_outline_tree,
    ensure_multi_chapter_outline,
    generate_global_outline,
    select_preferred_outline_tree,
)
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy
from app.workflows.digest.shared.models import SharedInputs
from app.workflows.digest.unified.models import ChapterPrior, ChapterPriors, TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session

logger = structlog.get_logger()


def build_outline_reduce_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the global outline reducer."""

    async def outline_reduce_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="outline_reduce")
        clean_chunks = state.get("clean_chunks", [])
        local_outlines = state.get("local_outlines", [])
        user_prompt = state.get("user_prompt")
        shared_inputs: SharedInputs | None = state.get("shared_inputs")
        build_session_id = state.get("build_session_id", "")

        if shared_inputs is None:
            return {"error": "Docs lane missing shared inputs."}

        fast_hints_lines = []
        if shared_inputs.fast_hints.high_freq_terms:
            fast_hints_lines.append(
                "High frequency terms: "
                + ", ".join(term for term, _ in shared_inputs.fast_hints.high_freq_terms[:12])
            )
        if shared_inputs.fast_hints.chapter_candidates:
            fast_hints_lines.append(
                "Chapter candidates: "
                + ", ".join(shared_inputs.fast_hints.chapter_candidates[:8])
            )
        if shared_inputs.fast_hints.formula_patterns:
            fast_hints_lines.append(
                f"Formula count: {len(shared_inputs.fast_hints.formula_patterns)}"
            )
        fast_hints_lines.append(
            f"Question density: {shared_inputs.fast_hints.question_density:.2%}"
        )

        local_text = "\n".join(
            (
                f"Source chunk {item['chunk_index']} ({item['source_filename']})\n"
                f"Titles: {', '.join(item['titles']) or '(none)'}\n"
                f"Preview: {item.get('preview', '(none)')}"
            )
            for item in local_outlines
        )
        topic_snapshot = await _load_outline_topic_snapshot(build_session_id)
        semantic_outline_tree = build_anchor_outline_tree(
            shared_inputs.section_packets,
            topic_snapshot=topic_snapshot,
        )
        fallback_outline_tree = build_thematic_outline_tree(
            shared_inputs.section_packets,
            fast_hints=shared_inputs.fast_hints,
        )
        preferred_seed_outline = semantic_outline_tree if semantic_outline_tree.get("chapters") else {}
        seed_outline_text = (
            build_thematic_outline_summary(preferred_seed_outline)
            if preferred_seed_outline.get("chapters")
            else ""
        )

        outline_input = local_text
        if seed_outline_text:
            outline_input += (
                "\n\nSemantic teaching plan from graph anchors:\n" + seed_outline_text
            )
        if fast_hints_lines:
            outline_input += "\n\n" + "\n".join(fast_hints_lines)

        plan = strategy.plan_outline(
            chunk_count=len(clean_chunks),
            local_outlines=local_outlines,
            user_prompt=user_prompt,
        )
        node_logger.info("docgen_outline_planning_started", mode=plan.mode, reason=plan.reason)

        try:
            subject_context = shared_inputs.subject_profile.build_context_string()
            llm_outline_tree = await generate_global_outline(
                chunk_count=len(clean_chunks),
                local_outlines_text=outline_input,
                user_prompt=user_prompt,
                subject_context=subject_context,
            )
            llm_calls_total = 1
        except Exception:
            llm_outline_tree = build_fallback_outline_tree(clean_chunks, local_outlines)
            llm_calls_total = 0
            node_logger.warning("docgen_outline_fallback_used")

        llm_outline_tree = ensure_multi_chapter_outline(
            llm_outline_tree,
            clean_chunks,
            local_outlines,
        )
        if semantic_outline_tree.get("chapters"):
            outline_tree = select_preferred_outline_tree(
                llm_outline_tree=llm_outline_tree,
                thematic_outline_tree=semantic_outline_tree,
                clean_chunks=clean_chunks,
                section_packets=shared_inputs.section_packets,
                prefer_thematic_alignment=True,
            )
        else:
            outline_tree = (
                llm_outline_tree
                if llm_outline_tree.get("chapters")
                else fallback_outline_tree
            )
        chapter_assignments = build_chapter_assignments_from_sections(
            outline_tree,
            clean_chunks=clean_chunks,
            section_packets=shared_inputs.section_packets,
        )

        chapter_priors = ChapterPriors(
            chapters=[
                ChapterPrior(
                    chapter_index=assignment["chapter_index"],
                    title=assignment["title"],
                    section_titles=list(assignment.get("section_titles", [])),
                    key_terms=_build_key_terms(assignment),
                    chunk_uids=list(assignment.get("chunk_uids", [])),
                )
                for assignment in chapter_assignments
            ]
        )
        if build_session_id:
            session = get_unified_build_session(build_session_id)
            session.publish_chapter_priors(chapter_priors)

        out_dir = build_docgen_intermediate_latest_dir(state["subject"])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "outline_tree.json").write_text(
            json.dumps(outline_tree, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "chapter_assignments.json").write_text(
            json.dumps(chapter_assignments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        outline_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_outline_planning_completed",
            chapter_count=len(chapter_assignments),
            semantic_anchor_count=len(topic_snapshot.anchors) if topic_snapshot else 0,
            outline_source=(
                "kg_semantic"
                if semantic_outline_tree.get("chapters") and outline_tree == semantic_outline_tree
                else "llm_primary"
                if llm_outline_tree.get("chapters") and outline_tree == llm_outline_tree
                else "fallback_structure"
            ),
            outline_ms=outline_ms,
        )
        return {
            "outline_tree": outline_tree,
            "chapter_assignments": chapter_assignments,
            "outline_ms": outline_ms,
            "llm_calls_total": llm_calls_total,
        }

    return outline_reduce_node


async def _load_outline_topic_snapshot(build_session_id: str) -> TopicAnchorSnapshot | None:
    if not build_session_id:
        return None
    session = get_unified_build_session(build_session_id)
    return await session.wait_for_topic_anchor_snapshot(timeout_ms=2200)


def _build_key_terms(assignment: dict) -> list[str]:
    terms = [
        str(assignment.get("title", "")),
        *[str(title) for title in assignment.get("section_titles", [])],
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped[:12]
