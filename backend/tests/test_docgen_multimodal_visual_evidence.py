from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen_multimodal.lib import visual_evidence as visual_module
from app.workflows.digest.docgen_multimodal.lib.models import (
    MaterialImageOccurrence,
    RereadAssessment,
    VisualEvidence,
    VisualEvidenceBatchResponse,
    VisualEvidenceDecision,
)
from app.workflows.digest.docgen_multimodal.prompts.visual_evidence import (
    build_visual_evidence_messages,
)


def _png_bytes(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(output, format="PNG")
    return output.getvalue()


class _AssetStore:
    def __init__(self, assets: dict[str, bytes]) -> None:
        self.assets = assets
        self.json_entries: dict[str, dict] = {}

    async def list_prefix(self, prefix: str) -> list[str]:
        return [key for key in self.assets if key.startswith(prefix)]

    async def read_bytes(self, key: str) -> bytes:
        return self.assets[key]

    async def read_json(self, key, model):
        return model.model_validate(self.json_entries[key]) if key in self.json_entries else None

    async def write_json(self, key, value):
        self.json_entries[key] = value.model_dump(mode="json")


def _material_context() -> DigestMaterialContext:
    markdown = """# 图示

下面是教材封面。

![教材封面](../assets/cover.png)

下面的结构图说明编码器和解码器之间的数据流。

![GC-LSTM 结构](../assets/architecture.png)
"""
    packet = SourcePacket(
        file_id="file-1",
        filename="lesson.pdf",
        filetype=".pdf",
        markdown_path="users/u/files/file-1/markdown.md",
        asset_dir="users/u/files/file-1/assets",
        normalized_content=markdown,
        char_count=len(markdown),
        has_formulas=False,
        has_tables=False,
        has_images=True,
        image_refs=["cover.png", "architecture.png"],
    )
    section = SectionPacket(
        digest_chunk_uid="section-1",
        source_file_id="file-1",
        source_filename="lesson.pdf",
        chunk_index=0,
        title="图示",
        header_path="图示",
        level=1,
        normalized_content=markdown,
        preview=markdown[:200],
        char_count=len(markdown),
        image_refs=["cover.png", "architecture.png"],
    )
    return DigestMaterialContext(source_documents=[packet], material_sections=[section])


def test_collect_image_occurrences_preserves_markdown_order(monkeypatch) -> None:
    store = _AssetStore(
        {
            "users/u/files/file-1/assets/cover.png": _png_bytes("white"),
            "users/u/files/file-1/assets/architecture.png": _png_bytes("blue"),
        }
    )
    monkeypatch.setattr(visual_module, "get_content_store", lambda: store)

    occurrences, failures = asyncio.run(
        visual_module.collect_material_image_occurrences(_material_context())
    )

    assert failures == []
    assert [item.asset_filename for item in occurrences] == ["cover.png", "architecture.png"]
    assert [item.occurrence_index for item in occurrences] == [1, 2]
    assert all(item.section_ref == "section-1" for item in occurrences)
    assert all(item.data_url.startswith("data:image/png;base64,") for item in occurrences)


def _occurrence() -> MaterialImageOccurrence:
    return MaterialImageOccurrence(
        image_id="img_1",
        file_id="file-1",
        source_filename="lesson.pdf",
        section_ref="section-1",
        section_title="图示",
        occurrence_index=1,
        markdown_target="../assets/architecture.png",
        asset_key="users/u/files/file-1/assets/architecture.png",
        asset_filename="architecture.png",
        alt_text="结构图",
        nearby_text="编码器和解码器之间的数据流。",
        mime_type="image/png",
        file_size=1024,
        width=320,
        height=240,
        sha256="a" * 64,
        context_sha256="b" * 64,
        data_url="data:image/png;base64,AAAA",
    )


def _reread_assessment(**updates) -> RereadAssessment:
    return RereadAssessment.model_validate({
        "knowledge_scope": "source_specific",
        "text_coverage": "missing",
        "original_required": True,
        "missing_knowledge": "The beta branch bypasses two decoder stages and joins the second encoder.",
        "original_required_reason": "The multiple crossing branches need joint verification beyond the extracted facts.",
        **updates,
    })


def test_meaningless_decision_cannot_leak_evidence() -> None:
    decision = VisualEvidenceDecision(
        image_id="img_1",
        is_meaningful=False,
        visual_type="architecture",
        summary="不应保留",
        key_facts=["不应保留"],
        confidence=0.9,
        reread_recommended=True,
        reread_reason="不应保留的复读理由",
        reread_assessment=_reread_assessment(),
    )

    assert decision.summary is None
    assert decision.key_facts == []
    assert decision.confidence is None
    assert decision.reread_recommended is None
    assert decision.reread_reason is None
    assert decision.reread_assessment is None
    assert decision.to_evidence(
        _occurrence(),
        model="light|gpt-5.6-luna",
        prompt_version="visual-evidence-v1",
    ) is None


def test_visual_prompt_uses_high_detail_and_cache_key_tracks_context() -> None:
    occurrence = _occurrence()
    messages = build_visual_evidence_messages([occurrence])
    image_block = messages[1]["content"][2]

    assert image_block["type"] == "image_url"
    assert image_block["image_url"]["detail"] == "high"
    first_key = visual_module.visual_evidence_cache_key(
        occurrence,
        model_identity="light|gpt-5.6-luna",
    )
    changed_context = occurrence.model_copy(update={"context_sha256": "c" * 64})
    second_key = visual_module.visual_evidence_cache_key(
        changed_context,
        model_identity="light|gpt-5.6-luna",
    )
    assert first_key != second_key


@pytest.mark.parametrize("reason, expected", [(None, False), ("   ", False), ("Source-specific values absent from prose.", True)])
def test_reread_requires_a_specific_reason(reason, expected) -> None:
    decision = VisualEvidenceDecision(
        image_id="img_1",
        is_meaningful=True,
        summary="Custom experimental measurements.",
        reread_recommended=True,
        reread_reason=reason,
        reread_assessment=_reread_assessment(),
    )
    evidence = decision.to_evidence(_occurrence(), model="light", prompt_version="v2")

    assert evidence is not None
    assert evidence.reread_recommended is expected
    assert bool(evidence.reread_reason) is expected


@pytest.mark.parametrize("assessment, expected", [
    (None, False),
    (RereadAssessment(), False),
    (_reread_assessment(knowledge_scope="common"), False),
    (_reread_assessment(knowledge_scope="uncertain"), False),
    (_reread_assessment(text_coverage="covered"), False),
    (_reread_assessment(text_coverage="uncertain"), False),
    (_reread_assessment(original_required=False), False),
    (_reread_assessment(missing_knowledge="  "), False),
    (_reread_assessment(original_required_reason="  "), False),
    (_reread_assessment(), True),
])
def test_reread_requires_all_structured_checks(assessment, expected) -> None:
    decision = VisualEvidenceDecision(
        image_id="img_1", is_meaningful=True, summary="Useful teaching illustration.",
        key_facts=["This evidence stays available even without rereading."],
        reread_recommended=True, reread_reason="Important information missing from the prose.",
        reread_assessment=assessment,
    )
    evidence = decision.to_evidence(_occurrence(), model="light", prompt_version="v3")

    assert decision.reread_recommended is expected
    assert evidence is not None
    assert evidence.can_reread is expected
    assert evidence.reread_assessment == assessment
    assert evidence.key_facts == ["This evidence stays available even without rereading."]
    assert bool(evidence.reread_reason) is expected


def test_old_evidence_without_checks_cannot_authorize_rereading() -> None:
    decision = VisualEvidenceDecision(
        image_id="img_1", is_meaningful=True, summary="Custom architecture.",
        reread_recommended=True, reread_reason="The custom branches require verification.",
        reread_assessment=_reread_assessment(),
    )
    evidence = decision.to_evidence(_occurrence(), model="light", prompt_version="v2")
    old_payload = evidence.model_dump()
    old_payload.pop("reread_assessment")
    restored = VisualEvidence.model_validate(old_payload)

    assert restored.reread_recommended is False
    assert restored.reread_reason == ""
    assert restored.summary == evidence.summary


def test_visual_prompt_includes_complete_section_once_per_batch() -> None:
    first = _occurrence().model_copy(update={"section_text": "FULL_SECTION_CONTEXT", "nearby_text": "NEARBY"})
    second = first.model_copy(update={"image_id": "img_2", "occurrence_index": 2})
    messages = build_visual_evidence_messages([first, second])
    blocks = messages[1]["content"]
    combined = "\n".join(block.get("text", "") for block in blocks)

    assert combined.count("FULL_SECTION_CONTEXT") == 1
    assert [block["type"] for block in blocks] == ["text", "text", "image_url", "text", "text", "image_url", "text"]
    assert "reread_reason" in messages[0]["content"]


def test_distant_section_edit_invalidates_visual_cache(monkeypatch) -> None:
    store = _AssetStore({"users/u/files/file-1/assets/architecture.png": _png_bytes("blue")})
    monkeypatch.setattr(visual_module, "get_content_store", lambda: store)
    material = _material_context()
    body = "Original explanation.\n" + "Unchanged text. " * 300 + "![Diagram](architecture.png)"
    material.section_packets[0].normalized_content = body
    first, _ = asyncio.run(visual_module.collect_material_image_occurrences(material))
    material.section_packets[0].normalized_content = body.replace("Original explanation.", "The new explanation covers all arrows.")
    second, _ = asyncio.run(visual_module.collect_material_image_occurrences(material))

    assert first[0].nearby_text == second[0].nearby_text
    assert first[0].section_text != second[0].section_text
    assert visual_module.visual_evidence_cache_key(first[0], model_identity="light") != visual_module.visual_evidence_cache_key(second[0], model_identity="light")


def test_first_understanding_caches_reread_decision_and_filters_meaningless_images(monkeypatch) -> None:
    store = _AssetStore({
        "users/u/files/file-1/assets/cover.png": _png_bytes("white"),
        "users/u/files/file-1/assets/architecture.png": _png_bytes("blue"),
    })
    calls = []

    async def understand(messages, **kwargs):
        calls.append(kwargs)
        ids = kwargs["extra_metadata"]["image_ids"]
        return VisualEvidenceBatchResponse(decisions=[
            VisualEvidenceDecision(image_id=ids[0], is_meaningful=False),
            VisualEvidenceDecision(
                image_id=ids[1], is_meaningful=True, summary="Custom architecture with beta link.",
                reread_recommended=True, reread_reason="The custom beta arrow is missing from the section prose.",
                reread_assessment=_reread_assessment(),
            ),
        ])

    monkeypatch.setattr(visual_module, "get_content_store", lambda: store)
    monkeypatch.setattr(visual_module, "_cache_prefix", lambda _course_id: "cache/visual/")
    monkeypatch.setattr(visual_module, "acompletion_with_fallback", understand)

    async def run_twice():
        kwargs = {"course_id": "course_multimodal", "material_context": _material_context(), "visual_model_name": "gpt-5.6-luna"}
        first_progress, second_progress = [], []

        async def report_first(completed, total):
            first_progress.append((completed, total))

        async def report_second(completed, total):
            second_progress.append((completed, total))

        first = await visual_module.generate_visual_evidence(**kwargs, on_progress=report_first)
        second = await visual_module.generate_visual_evidence(**kwargs, on_progress=report_second)
        return first, second, first_progress, second_progress

    first, second, first_progress, second_progress = asyncio.run(run_twice())
    assert first_progress == [(0, 2), (2, 2)]
    assert second_progress == [(2, 2)]

    assert len(calls) == 1
    assert calls[0]["model"] == "gpt-5.6-luna"
    assert len(first.evidence) == len(second.evidence) == 1
    assert first.meaningless_count == second.meaningless_count == 1
    assert second.cache_hit_count == 2
    assert second.llm_call_count == 0
    assert second.evidence[0].reread_recommended is True
    assert second.evidence[0].reread_reason == first.evidence[0].reread_reason
    assert second.evidence[0].reread_assessment == _reread_assessment()
    assert second.metrics()["reread_recommended_image_count"] == 1
    assert all("base64" not in str(entry) for entry in store.json_entries.values())
