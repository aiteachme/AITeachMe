"""Draft one chapter in the docgen lane."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.utils.path_helpers import build_docgen_intermediate_latest_dir, build_knowledge_doc_build_path
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.services.writer_service import (
    build_global_outline_summary,
    write_chapter,
)
from app.workflows.digest.docgen.strategy import DocGenExecutionStrategy
from app.workflows.digest.shared.models import AssetItem, SharedInputs

logger = structlog.get_logger()


def build_draft_chapter_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the chapter draft node."""

    async def draft_chapter_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="draft_chapter")

        chapter = state["chapter"]
        outline_tree = state.get("outline_tree", {})
        total_chapters = int(state.get("total_chapters", 1))
        user_prompt = state.get("user_prompt")
        prev_summary = str(state.get("prev_summary", ""))
        next_preview = str(state.get("next_preview", ""))
        subject = str(state.get("subject", ""))
        shared_inputs: SharedInputs | None = state.get("shared_inputs")

        chapter_index = int(chapter["chapter_index"])
        chapter_title = str(chapter.get("title", f"Chapter {chapter_index}"))
        source_contents = list(chapter.get("source_contents", []))
        source_file_ids = list(chapter.get("source_file_ids", []))
        section_titles = list(chapter.get("section_titles", []))
        formula_refs = list(chapter.get("formula_refs", []))
        source_brief = build_teacher_source_brief(chapter)
        chunk_uids = list(chapter.get("chunk_uids", []))
        source_text = "\n\n---\n\n".join(source_contents) if source_contents else "(no source content)"
        image_hints, asset_count = build_image_hints(shared_inputs=shared_inputs, chapter=chapter)

        if asset_count:
            node_logger.info(
                "docgen_drafting_with_assets",
                chapter_index=chapter_index,
                asset_count=asset_count,
            )

        global_outline_text = build_global_outline_summary(outline_tree)
        subject_context = ""
        teaching_style_hint = ""
        if shared_inputs and shared_inputs.subject_profile:
            subject_context = shared_inputs.subject_profile.build_context_string()
            teaching_style_hint = shared_inputs.subject_profile.teaching_style_hint
        async with strategy.chapter_semaphore:
            markdown = await write_chapter(
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
                source_content=f"{source_text}{image_hints}",
                subject_context=subject_context,
                teaching_style_hint=teaching_style_hint,
            )

        if subject:
            intermediate_dir = build_docgen_intermediate_latest_dir(subject)
            intermediate_dir.mkdir(parents=True, exist_ok=True)
            draft_path = build_knowledge_doc_build_path(subject, chapter_index, f"draft_{chapter_title}")
            (intermediate_dir / draft_path.name).write_text(
                markdown,
                encoding="utf-8",
            )

        draft_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_drafting_chapter_completed",
            chapter_index=chapter_index,
            chars=len(markdown),
            draft_ms=draft_ms,
        )
        return {
            "chapter_drafts": [
                {
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "markdown": markdown,
                    "source_contents": source_contents,
                    "source_file_ids": source_file_ids,
                    "section_titles": section_titles,
                    "formula_refs": formula_refs,
                    "source_brief": source_brief,
                    "prev_summary": prev_summary,
                    "next_preview": next_preview,
                    "chunk_uids": chunk_uids,
                    "image_refs": list(chapter.get("image_refs", [])),
                    "draft_ms": draft_ms,
                }
            ],
            "draft_ms": draft_ms,
            "llm_calls_total": 1,
        }

    return draft_chapter_node


def build_teacher_source_brief(chapter: dict) -> str:
    """Summarize the chapter inputs as a teacher-facing synthesis brief."""

    base_brief = str(chapter.get("source_brief", "")).strip()
    section_payloads = list(chapter.get("section_payloads", []))
    if not section_payloads:
        return base_brief

    lines: list[str] = []
    if base_brief:
        lines.extend([base_brief, ""])
    lines.append("Teaching synthesis focus:")
    for payload in section_payloads[:8]:
        title = str(payload.get("title", "")).strip() or "Unnamed section"
        preview = str(payload.get("preview", "")).strip()
        formula_refs = list(payload.get("formula_refs", []))
        hint = f"- {title}"
        if preview:
            hint += f": {preview[:160]}"
        lines.append(hint)
        if formula_refs:
            lines.append(f"  formulas: {', '.join(formula_refs[:3])}")
    return "\n".join(lines).strip()


def build_image_hints(*, shared_inputs: SharedInputs | None, chapter: dict) -> tuple[str, int]:
    """Build chapter-specific image hints from markdown-linked assets."""

    if shared_inputs is None:
        return "", 0

    chunk_uids = set(chapter.get("chunk_uids", []))
    if not chunk_uids:
        return "", 0

    section_by_uid = {
        section.digest_chunk_uid: section for section in shared_inputs.section_packets
    }
    asset_metadata = {
        (asset.file_id, asset.filename): asset for asset in shared_inputs.asset_registry.assets
    }
    related_assets: list[tuple[str, AssetItem | None]] = []
    seen_assets: set[tuple[int, str]] = set()
    for chunk_uid in chunk_uids:
        section = section_by_uid.get(chunk_uid)
        if section is None:
            continue
        for image_ref in section.image_refs:
            asset_key = (section.source_file_id, image_ref)
            if asset_key in seen_assets:
                continue
            seen_assets.add(asset_key)
            related_assets.append((image_ref, asset_metadata.get(asset_key)))

    if not related_assets:
        return "", 0

    lines = ["", "", "Available related assets:"]
    for filename, asset in related_assets[:8]:
        if asset is None:
            lines.append(f"- {filename}")
            continue
        suffix = f" page {asset.page_number}" if asset.page_number is not None else ""
        lines.append(f"- {filename} ({asset.asset_type}{suffix})")
    return "\n".join(lines) + "\n", len(related_assets)



