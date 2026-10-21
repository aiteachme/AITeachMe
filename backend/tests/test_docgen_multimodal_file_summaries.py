from __future__ import annotations

import pytest

from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.models import ChapterSourceSlice, FileMaterialSummary
from app.workflows.digest.docgen_multimodal.lib import file_summaries as multimodal_routing
from app.workflows.digest.docgen_multimodal.lib.models import VisualEvidence


def _section(file_id: str, ref: str, body: str, index: int) -> SectionPacket:
    return SectionPacket(
        digest_chunk_uid=ref,
        source_file_id=file_id,
        source_filename=f"{file_id}.pdf",
        chunk_index=index,
        title=f"Topic {index}",
        header_path=f"Topic {index}",
        level=1,
        normalized_content=body,
        preview=body[:100],
        char_count=len(body),
    )


def _material() -> DigestMaterialContext:
    first = "# Topic 0\n\n![architecture](assets/architecture.png)\n\n"
    second = "# Topic 1\n\nA separate section about algebra.\n"
    return DigestMaterialContext(
        source_documents=[
            SourcePacket(
                file_id="file-1",
                filename="file-1.pdf",
                filetype=".pdf",
                markdown_path="file-1.md",
                asset_dir="assets",
                normalized_content=first + second,
                char_count=len(first + second),
                has_formulas=False,
                has_tables=False,
                has_images=True,
            )
        ],
        material_sections=[
            _section("file-1", "sec-1", first, 0),
            _section("file-1", "sec-2", second, 1),
        ],
    )


def _evidence(ref: str = "sec-1", image_id: str = "img_1") -> dict:
    return VisualEvidence(
        image_id=image_id,
        file_id="file-1",
        section_ref=ref,
        source_filename="file-1.pdf",
        asset_filename="architecture.png",
        summary="Encoder sends hidden states to the decoder.",
        key_facts=["Encoder-decoder data flow is directional."],
        relationships=["Encoder -> decoder"],
        image_sha256="a" * 64,
        context_sha256="b" * 64,
        model="light|gpt-5.6-luna",
        prompt_version="visual-evidence-v1",
    ).model_dump(mode="json")


@pytest.mark.anyio
async def test_visual_evidence_only_enriches_its_section_and_preserves_source_spans(monkeypatch):
    context = _material()
    original_texts = [item.normalized_content for item in context.section_packets]
    captures = []

    async def fake_completion(messages, **kwargs):
        del kwargs
        captures.append(messages[1]["content"])
        return FileMaterialSummary(
            summary="Architecture is relevant to chapter 1",
            chapter_slices=[
                ChapterSourceSlice(
                    chapter_index=1,
                    section_ref="sec-1",
                    relevance=0.95,
                    usage="background",
                    summary="Encoder-decoder relationship",
                    line_start=999,
                    line_end=1000,
                )
            ],
        )

    monkeypatch.setattr(multimodal_routing, "acompletion_with_fallback", fake_completion)
    result = await multimodal_routing.summarize_files(
        context,
        chapters=[{"chapter_index": 1, "title": "Architectures"}],
        digest_mode="systematic",
        visual_evidence_items=[_evidence(), _evidence()],
    )

    assert len(captures) == 1
    prompt = captures[0]
    first, second = prompt.split("## Section sec-2")
    assert first.count("Encoder sends hidden states to the decoder") == 1
    assert "Encoder -> decoder" in first
    assert "Encoder sends hidden states to the decoder" not in second
    assert '"line_start": 1' in prompt
    assert '"line_end": 3' in prompt or '"line_end": 4' in prompt
    assert result[0].chapter_slices[0].section_ref == "sec-1"
    assert result[0].chapter_slices[0].line_start == 1
    assert result[0].chapter_slices[0].line_end != 1000
    assert [item.normalized_content for item in context.section_packets] == original_texts


@pytest.mark.anyio
async def test_unmatched_or_missing_visuals_keep_text_only_route(monkeypatch):
    context = _material()
    calls = []

    async def text_only(material_context, **kwargs):
        calls.append((material_context, kwargs))
        return []

    monkeypatch.setattr(multimodal_routing.text_routing, "summarize_files", text_only)
    for items in ([], [_evidence(ref="unknown")]):
        assert await multimodal_routing.summarize_files(
            context,
            chapters=[],
            digest_mode="systematic",
            visual_evidence_items=items,
        ) == []
    assert len(calls) == 2
    assert all(item[0] is context for item in calls)


def test_image_only_section_is_labeled_and_visual_text_is_bounded():
    context = _material()
    empty = context.section_packets[0].model_copy(update={"normalized_content": ""})
    grouped = multimodal_routing._evidence_by_section(context, [_evidence()])
    rendered = multimodal_routing._render_sections([empty], evidence_by_section=grouped)

    assert "## Section sec-1" in rendered
    assert "Encoder sends hidden states" in rendered
    assert len(multimodal_routing._visual_context([VisualEvidence.model_validate(_evidence())] * 100)) < 6200
