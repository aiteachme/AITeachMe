"""Review one drafted docs chapter."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.services.writer_service import (
    build_global_outline_summary,
    review_chapter,
    write_chapter,
)
from app.workflows.digest.docgen.strategy import DocGenExecutionStrategy
from app.workflows.digest.unified.models import TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session

logger = structlog.get_logger()


def build_review_chapter_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the docs chapter review node."""

    async def review_chapter_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="review_chapter")

        draft = state["draft"]
        outline_tree = state.get("outline_tree", {})
        total_chapters = int(state.get("total_chapters", 1))
        user_prompt = state.get("user_prompt")
        build_session_id = str(state.get("build_session_id", ""))

        chapter_index = int(draft["chapter_index"])
        chapter_title = str(draft["title"])
        markdown = str(draft["markdown"])
        source_contents = list(draft.get("source_contents", []))
        section_titles = list(draft.get("section_titles", []))
        formula_refs = list(draft.get("formula_refs", []))
        source_brief = str(draft.get("source_brief", ""))
        prev_summary = str(draft.get("prev_summary", ""))
        next_preview = str(draft.get("next_preview", ""))
        chunk_uids = list(draft.get("chunk_uids", []))
        source_summary = "\n".join(content[:300] for content in source_contents[:3])

        topic_snapshot = await _load_topic_anchor_snapshot(build_session_id)
        coverage_hints = build_coverage_hints(
            chapter_title=chapter_title,
            section_titles=section_titles,
            chunk_uids=chunk_uids,
            topic_snapshot=topic_snapshot,
        )
        needs_anchor_rewrite = should_rewrite_for_anchor_alignment(
            chapter_title=chapter_title,
            markdown=markdown,
            chunk_uids=chunk_uids,
            topic_snapshot=topic_snapshot,
        )

        # Resolve subject context from shared inputs via unified session
        subject_context = ""
        teaching_style_hint = ""
        if build_session_id:
            try:
                _session = get_unified_build_session(build_session_id)
                if _session.shared_inputs and _session.shared_inputs.subject_profile:
                    subject_context = _session.shared_inputs.subject_profile.build_context_string()
                    teaching_style_hint = _session.shared_inputs.subject_profile.teaching_style_hint
            except (KeyError, AttributeError):
                pass

        async with strategy.chapter_semaphore:
            review_result = await review_chapter(
                markdown,
                source_summary + coverage_hints,
                user_prompt=user_prompt,
                subject_context=subject_context,
            )

        llm_calls_total = 1
        final_markdown = markdown
        if needs_anchor_rewrite or not review_result.get("passed", True):
            global_outline_text = build_global_outline_summary(outline_tree)
            source_text = "\n\n---\n\n".join(source_contents) if source_contents else "(no source content)"
            async with strategy.chapter_semaphore:
                rewritten_markdown = await write_chapter(
                    chapter_title=chapter_title,
                    chapter_index=chapter_index,
                    total_chapters=total_chapters,
                    global_outline_text=global_outline_text,
                    section_titles=section_titles,
                    user_prompt=user_prompt,
                    prev_summary=prev_summary,
                    next_preview=next_preview,
                    source_brief=source_brief,
                    formula_refs=formula_refs,
                    source_content=source_text + coverage_hints,
                    subject_context=subject_context,
                    teaching_style_hint=teaching_style_hint,
                )
                second_review = await review_chapter(
                    rewritten_markdown,
                    source_summary + coverage_hints,
                    user_prompt=user_prompt,
                    subject_context=subject_context,
                )
            llm_calls_total += 2
            # BUG-4 fix: only use rewrite if second review passed or is better than first
            if second_review.get("passed", False) or second_review.get("review_skipped", False):
                final_markdown = rewritten_markdown
                review_result = second_review
            else:
                node_logger.warning(
                    "docgen_rewrite_rejected",
                    chapter_index=chapter_index,
                    reason="second_review_also_failed",
                )
                # Keep original markdown (first draft) which at least was closer to source

        review_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_reviewing_chapter_completed",
            chapter_index=chapter_index,
            anchor_rewrite=needs_anchor_rewrite,
            passed=review_result.get("passed", True),
            review_ms=review_ms,
        )
        return {
            "chapter_reviews": [
                {
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "markdown": final_markdown,
                    "review": review_result,
                    "source_contents": source_contents,
                    "section_titles": section_titles,
                    "formula_refs": formula_refs,
                    "chunk_uids": chunk_uids,
                    "review_ms": review_ms,
                }
            ],
            "review_ms": review_ms,
            "llm_calls_total": llm_calls_total,
        }

    return review_chapter_node


async def _load_topic_anchor_snapshot(build_session_id: str) -> TopicAnchorSnapshot | None:
    if not build_session_id:
        return None
    session = get_unified_build_session(build_session_id)
    return await session.wait_for_topic_anchor_snapshot(timeout_ms=500)


def build_coverage_hints(
    *,
    chapter_title: str,
    section_titles: list[str],
    chunk_uids: list[str],
    topic_snapshot: TopicAnchorSnapshot | None,
) -> str:
    """Build soft review hints from graph anchors."""

    if topic_snapshot is None or not topic_snapshot.anchors:
        return ""

    relevant_anchors = [
        anchor
        for anchor in topic_snapshot.anchors
        if set(anchor.chunk_uids) & set(chunk_uids)
    ]
    if relevant_anchors:
        anchor_names = ", ".join(anchor.topic_name for anchor in relevant_anchors[:6])
        return f"\n\nGraph anchors for this chapter: {anchor_names}"

    chapter_terms = {chapter_title.lower(), *[title.lower() for title in section_titles]}
    missing_anchors = [
        anchor.topic_name
        for anchor in topic_snapshot.anchors[:20]
        if anchor.confidence >= 0.7
        and anchor.topic_name.lower() not in chapter_terms
    ]
    if not missing_anchors:
        return ""
    return (
        "\n\nPotential missing graph anchors: "
        + ", ".join(missing_anchors[:6])
    )


def should_rewrite_for_anchor_alignment(
    *,
    chapter_title: str,
    markdown: str,
    chunk_uids: list[str],
    topic_snapshot: TopicAnchorSnapshot | None,
) -> bool:
    """Require one rewrite when graph anchors and docs wording clearly drift apart."""

    if topic_snapshot is None or not topic_snapshot.anchors or not chunk_uids:
        return False

    relevant_anchor_names = [
        anchor.topic_name.strip()
        for anchor in topic_snapshot.anchors
        if anchor.topic_name.strip() and set(anchor.chunk_uids) & set(chunk_uids)
    ]
    if not relevant_anchor_names:
        return False

    lowered_markdown = markdown.lower()
    lowered_title = chapter_title.lower()
    if any(
        anchor_name.lower() in lowered_markdown or anchor_name.lower() in lowered_title
        for anchor_name in relevant_anchor_names
    ):
        return False
    return True
