"""Reduce local outline candidates into a global plan."""

from __future__ import annotations

import json
from time import perf_counter

import structlog

from app.services.upload_support import build_docgen_intermediate_latest_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.outline_service import (
    build_chapter_assignments,
    build_fallback_outline_tree,
    ensure_multi_chapter_outline,
    generate_global_outline,
)
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy
from app.workflows.digest.shared.models import SectionPacket, SharedInputs
from app.workflows.digest.unified.models import ChapterPrior, ChapterPriors
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
        outline_input = local_text
        if fast_hints_lines:
            outline_input += "\n\n" + "\n".join(fast_hints_lines)

        plan = strategy.plan_outline(
            chunk_count=len(clean_chunks),
            local_outlines=local_outlines,
            user_prompt=user_prompt,
        )
        node_logger.info("docgen_outline_planning_started", mode=plan.mode, reason=plan.reason)

        try:
            outline_tree = await generate_global_outline(
                chunk_count=len(clean_chunks),
                local_outlines_text=outline_input,
                user_prompt=user_prompt,
            )
            llm_calls_total = 1
        except Exception:
            outline_tree = build_fallback_outline_tree(clean_chunks, local_outlines)
            llm_calls_total = 0
            node_logger.warning("docgen_outline_fallback_used")

        outline_tree = ensure_multi_chapter_outline(outline_tree, clean_chunks, local_outlines)
        chapter_assignments = build_chapter_assignments(outline_tree, clean_chunks)
        chapter_assignments = _enrich_chapter_assignments(
            chapter_assignments=chapter_assignments,
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
            outline_ms=outline_ms,
        )
        return {
            "outline_tree": outline_tree,
            "chapter_assignments": chapter_assignments,
            "outline_ms": outline_ms,
            "llm_calls_total": llm_calls_total,
        }

    return outline_reduce_node


def _enrich_chapter_assignments(
    *,
    chapter_assignments: list[dict],
    section_packets: list[SectionPacket],
) -> list[dict]:
    sections_by_file_id: dict[int, list[SectionPacket]] = {}
    for packet in section_packets:
        sections_by_file_id.setdefault(packet.source_file_id, []).append(packet)

    enriched: list[dict] = []
    for assignment in chapter_assignments:
        matched_sections = _match_sections_for_assignment(assignment, sections_by_file_id)
        chunk_uids = [packet.digest_chunk_uid for packet in matched_sections]
        image_refs = list(dict.fromkeys(ref for packet in matched_sections for ref in packet.image_refs))
        formula_refs = list(
            dict.fromkeys(
                [*assignment.get("formula_refs", []), *[ref for packet in matched_sections for ref in packet.formula_refs]]
            )
        )
        enriched.append(
            {
                **assignment,
                "chunk_uids": chunk_uids,
                "image_refs": image_refs,
                "formula_refs": formula_refs,
            }
        )
    return enriched


def _match_sections_for_assignment(
    assignment: dict,
    sections_by_file_id: dict[int, list[SectionPacket]],
) -> list[SectionPacket]:
    source_file_ids = set(assignment.get("source_file_ids", []))
    section_titles = {
        str(title).strip().lower() for title in assignment.get("section_titles", []) if str(title).strip()
    }
    matched_sections: list[SectionPacket] = []
    for file_id in source_file_ids:
        sections = sections_by_file_id.get(file_id, [])
        direct_matches = [
            packet
            for packet in sections
            if not section_titles
            or packet.title.strip().lower() in section_titles
            or any(section_title in packet.header_path.lower() for section_title in section_titles)
        ]
        matched_sections.extend(direct_matches or sections)
    deduped: list[SectionPacket] = []
    seen: set[str] = set()
    for packet in matched_sections:
        if packet.digest_chunk_uid in seen:
            continue
        seen.add(packet.digest_chunk_uid)
        deduped.append(packet)
    return deduped


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
