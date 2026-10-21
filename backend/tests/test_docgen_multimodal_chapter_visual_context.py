from __future__ import annotations

import asyncio

from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.models import ChapterGenerationTask, ChapterSourceSlice
from app.workflows.digest.docgen.lib.quality import build_evidence_ledger
from app.workflows.digest.docgen.lib.source_slices import build_priority_source_context
from app.workflows.digest.docgen_multimodal.lib.chapter_visual_context import (
    annotate_visual_sources,
    build_chapter_visual_context,
    visual_source_url,
)
from app.workflows.digest.docgen_multimodal.lib.models import VisualEvidence


def _section(ref: str, index: int, body: str) -> SectionPacket:
    return SectionPacket(
        digest_chunk_uid=ref,
        source_file_id="file-1",
        source_filename="lesson.pdf",
        chunk_index=index,
        page_num=index + 1,
        title=f"Section {index + 1}",
        header_path=f"Chapter / Section {index + 1}",
        level=2,
        normalized_content=body,
        preview=body,
        char_count=len(body),
    )


def _material() -> DigestMaterialContext:
    first = "The source text names an encoder diagram but does not explain its arrows."
    second = "This section belongs to an unrelated chapter."
    return DigestMaterialContext(
        source_documents=[
            SourcePacket(
                file_id="file-1",
                filename="lesson.pdf",
                filetype=".pdf",
                markdown_path="lesson.md",
                asset_dir="lesson/assets",
                normalized_content=f"{first}\n\n{second}",
                char_count=len(first) + len(second) + 2,
                has_formulas=False,
                has_tables=False,
                has_images=True,
            )
        ],
        material_sections=[
            _section("sec-1", 0, first),
            _section("sec-2", 1, second),
        ],
    )


def _visual(ref: str, image_id: str, concept: str) -> VisualEvidence:
    return VisualEvidence(
        image_id=image_id,
        file_id="file-1",
        source_filename="lesson.pdf",
        section_ref=ref,
        section_title=ref,
        asset_filename=f"{image_id}.png",
        visual_type="architecture",
        summary=f"The diagram shows {concept}.",
        key_facts=[f"{concept} is visible only in this image."],
        relationships=["Encoder sends hidden state to decoder."],
        key_concepts=[concept],
        teaching_value=0.9,
        confidence=0.88,
        image_sha256="a" * 64,
        context_sha256="b" * 64,
        model="light|gpt-5.6-luna",
        prompt_version="visual-evidence-v1",
    )


def _state() -> tuple[dict, VisualEvidence, VisualEvidence]:
    material = _material()
    task = ChapterGenerationTask(
        chapter_index=1,
        confirmed_title="Encoder architecture",
        source_slices=[
            ChapterSourceSlice(
                chapter_index=1,
                file_id="file-1",
                filename="lesson.pdf",
                section_ref="sec-1",
                relevance=0.92,
            )
        ],
    )
    selected = _visual("sec-1", "img-selected", "LatentBridgeSignal")
    unrelated = _visual("sec-2", "img-unrelated", "UnrelatedVisualSignal")
    return (
        {
            "shared_inputs": material,
            "chapter_task": task.model_dump(mode="json"),
            "visual_evidence_items": [
                selected.model_dump(mode="json"),
                unrelated.model_dump(mode="json"),
            ],
        },
        selected,
        unrelated,
    )


def test_chapter_visual_context_selects_only_routed_sections_without_mutation() -> None:
    state, selected, unrelated = _state()
    original_material = state["shared_inputs"]
    original_task = ChapterGenerationTask.model_validate(state["chapter_task"])

    result = build_chapter_visual_context(state)
    enriched_material = DigestMaterialContext.model_validate(result.state["shared_inputs"])
    enriched_task = ChapterGenerationTask.model_validate(result.state["chapter_task"])

    assert [item.image_id for item in result.evidence] == [selected.image_id]
    assert unrelated.image_id not in result.urls_by_image_id
    assert len(original_material.section_packets) == 2
    assert len(original_task.source_slices) == 1
    assert len(enriched_material.section_packets) == 3
    assert len(enriched_task.source_slices) == 2
    assert enriched_task.source_slices[0].usage == "visual_evidence"


def test_visual_evidence_enters_priority_context_rag_and_ledger() -> None:
    state, selected, _unrelated = _state()
    result = build_chapter_visual_context(state)
    material = DigestMaterialContext.model_validate(result.state["shared_inputs"])
    task = ChapterGenerationTask.model_validate(result.state["chapter_task"])

    hydrated = build_priority_source_context(
        material,
        list(task.source_slices),
        max_total_chars=5000,
    )
    expected_url = visual_source_url(selected)
    assert "LatentBridgeSignal" in hydrated.text
    assert hydrated.sources[0] == expected_url
    assert hydrated.source_details[0]["url"] == expected_url

    rag_results = asyncio.run(
        LocalRAGRetriever(local_sections=list(material.section_packets)).search(
            "LatentBridgeSignal",
            max_results=3,
        )
    )
    assert rag_results
    assert "LatentBridgeSignal" in rag_results[0].snippet

    ledger = build_evidence_ledger(
        chapter_index=1,
        dense_context=hydrated.text,
        source_details=hydrated.source_details,
        targets=["LatentBridgeSignal"],
    )
    assert ledger.items
    assert ledger.items[0].source_ref == expected_url


def test_visual_output_annotations_mark_sources_and_ledger() -> None:
    state, selected, _unrelated = _state()
    context = build_chapter_visual_context(state)
    url = visual_source_url(selected)
    raw_result = {
        "chapter_drafts": [{"source_details": [{"url": url, "source": "docgen_source_slice"}]}],
        "research_traces": [{"opened_contexts": [{"url": url}], "budget_used": {}}],
        "evidence_ledgers": [{"items": [{"source_ref": url, "kind": "core"}]}],
    }

    annotated = annotate_visual_sources(raw_result, context)

    detail = annotated["chapter_drafts"][0]["source_details"][0]
    assert detail["source"] == "docgen_visual_evidence"
    assert detail["image_id"] == selected.image_id
    assert annotated["research_traces"][0]["budget_used"]["visual_evidence_count"] == 1
    evidence = annotated["evidence_ledgers"][0]["items"][0]
    assert evidence["kind"] == "visual"
    assert evidence["source_span"] == selected.image_id


def test_chapter_without_routed_visuals_is_unchanged() -> None:
    state, _selected, unrelated = _state()
    state["visual_evidence_items"] = [unrelated.model_dump(mode="json")]

    result = build_chapter_visual_context(state)

    assert result.evidence == []
    assert result.state["shared_inputs"] is state["shared_inputs"]
    assert result.state["chapter_task"] is state["chapter_task"]
