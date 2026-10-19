from __future__ import annotations

import asyncio
import hashlib
import io
import json
from dataclasses import asdict

import pytest
from PIL import Image

from app.shared.infra.execution import TracedExecutionContext, TracedExecutionResult
from app.shared.infra.observability.trace import sanitize_langsmith_value
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.utils.time import utcnow
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.models import ChapterGenerationTask
from app.workflows.digest.docgen_multimodal.lib import writer, writer_images
from app.workflows.digest.docgen_multimodal.lib.chapter_visual_context import visual_source_url
from app.workflows.digest.docgen_multimodal.lib.models import RereadAssessment, VisualEvidence
from app.workflows.digest.docgen_multimodal.nodes import generate_chapters

_DENSE_CONTEXT = "Source-specific experiment: beta connects the encoder to the custom decoder."
_MARKDOWN = "# Custom architecture\n\n## Encoder\n\nThe custom beta link joins the encoder to the decoder.\n"


class _Store:
    def __init__(self, assets: dict[str, bytes]) -> None:
        self.assets = assets
        self.reads: list[str] = []

    async def list_prefix(self, prefix: str) -> list[str]:
        return [key for key in self.assets if key.startswith(prefix)]

    async def read_bytes(self, key: str) -> bytes:
        self.reads.append(key)
        return self.assets[key]


def _case(monkeypatch):
    assets: dict[str, bytes] = {}
    evidence: list[VisualEvidence] = []
    for index, color in enumerate(("red", "blue", "green", "yellow")):
        output = io.BytesIO()
        Image.new("RGB", (320, 240), color).save(output, format="PNG")
        raw = output.getvalue()
        assets[f"lesson/assets/img_{index}.png"] = raw
        evidence.append(VisualEvidence(
            image_id=f"img_{index}", file_id="file-1", source_filename="lesson.pdf",
            section_ref="section-1", asset_filename=f"img_{index}.png",
            visual_type="architecture", summary="The beta link belongs to this custom architecture.",
            reread_recommended=index != 0,
            reread_reason="The source-specific beta arrow is not explained in prose." if index != 0 else "",
            reread_assessment=RereadAssessment(
                knowledge_scope="source_specific", text_coverage="missing", original_required=True,
                missing_knowledge="The beta branch bypasses two custom decoder stages.",
                original_required_reason="Crossing branches need joint verification beyond the extracted facts.",
            ),
            teaching_value=0.9, confidence=0.9,
            image_sha256=hashlib.sha256(raw).hexdigest(), context_sha256="b" * 64,
            model="light", prompt_version="visual-evidence-v4",
        ))
    store = _Store(assets)
    monkeypatch.setattr(writer_images, "get_content_store", lambda: store)
    material = DigestMaterialContext(
        source_documents=[SourcePacket(
            file_id="file-1", filename="lesson.pdf", filetype=".pdf", markdown_path="lesson.md",
            asset_dir="lesson/assets", normalized_content=_DENSE_CONTEXT, char_count=len(_DENSE_CONTEXT),
            has_formulas=False, has_tables=False, has_images=True,
        )],
        material_sections=[SectionPacket(
            digest_chunk_uid="section-1", source_file_id="file-1", source_filename="lesson.pdf",
            chunk_index=0, title="Custom architecture", header_path="Custom architecture", level=1,
            normalized_content=_DENSE_CONTEXT, preview=_DENSE_CONTEXT, char_count=len(_DENSE_CONTEXT),
        )],
    )
    plan = {
        "chapter_index": 1, "total_chapters": 1, "title": "Custom architecture",
        "objective": "Understand the custom architecture.", "required_elements": ["beta"],
        "execution_contract": {"min_word_count": 1, "target_word_count": 1200},
        "source_slices": [{"file_id": "file-1", "section_ref": "section-1", "relevance": 0.9}],
        # img_3 is not among the chapter's actual visual sources.
        "source_details": [{"url": visual_source_url(item)} for item in evidence[:3]],
    }
    return material, evidence, plan, store


@pytest.mark.parametrize("mode, expected", [("sprint", ["img_1", "img_2"]), ("systematic", ["img_1", "img_2"])])
def test_loader_requires_recommendation_and_chapter_source_and_caps_images(monkeypatch, mode, expected) -> None:
    material, evidence, plan, store = _case(monkeypatch)
    loaded = asyncio.run(writer_images.load_writer_reread_images(
        material_context=material, visual_evidence=evidence, chapter_plan=plan, digest_mode=mode,
    ))

    assert [item.image_id for item in loaded.images] == expected
    assert store.reads == [f"lesson/assets/{image_id}.png" for image_id in expected]
    assert loaded.failures == []
    assert all("data_url" not in item.model_dump() and "base64" not in repr(item) for item in loaded.images)


@pytest.mark.parametrize("mode", ["sprint", "systematic"])
def test_loader_caps_three_eligible_images_at_two_in_every_mode(monkeypatch, mode) -> None:
    material, evidence, plan, store = _case(monkeypatch)
    plan["source_details"].append({"url": visual_source_url(evidence[3])})
    loaded = asyncio.run(writer_images.load_writer_reread_images(
        material_context=material, visual_evidence=evidence, chapter_plan=plan, digest_mode=mode,
    ))

    assert [item.image_id for item in loaded.images] == ["img_1", "img_2"]
    assert store.reads == ["lesson/assets/img_1.png", "lesson/assets/img_2.png"]


@pytest.mark.parametrize("assessment", [None, RereadAssessment(knowledge_scope="common")])
def test_loader_rechecks_eligibility_even_if_recommended_flag_is_stale(monkeypatch, assessment) -> None:
    material, evidence, plan, store = _case(monkeypatch)
    evidence[1] = evidence[1].model_copy(update={
        "reread_recommended": True, "reread_assessment": assessment,
    })
    loaded = asyncio.run(writer_images.load_writer_reread_images(
        material_context=material, visual_evidence=evidence, chapter_plan=plan, digest_mode="systematic",
    ))

    assert [item.image_id for item in loaded.images] == ["img_2"]
    assert store.reads == ["lesson/assets/img_2.png"]


def test_loader_skips_changed_or_missing_assets_and_deduplicates_originals(monkeypatch) -> None:
    material, evidence, plan, store = _case(monkeypatch)
    evidence[1] = evidence[1].model_copy(update={"image_sha256": "f" * 64})
    duplicate = evidence[2].model_copy(update={"image_id": "img_2_duplicate"})
    missing = evidence[2].model_copy(update={"image_id": "img_4_missing", "asset_filename": "missing.png", "image_sha256": "c" * 64})
    plan["source_details"].extend({"url": visual_source_url(item)} for item in (duplicate, missing))
    loaded = asyncio.run(writer_images.load_writer_reread_images(
        material_context=material, visual_evidence=[*evidence, duplicate, missing],
        chapter_plan=plan, digest_mode="systematic",
    ))

    assert [item.image_id for item in loaded.images] == ["img_2"]
    assert [item["reason"] for item in loaded.failures] == ["image_changed_since_understanding", "missing_or_ambiguous_asset"]
    assert store.reads == ["lesson/assets/img_1.png", "lesson/assets/img_2.png"]


def test_writer_sends_originals_directly_with_dense_context_and_redacts_traces(monkeypatch) -> None:
    material, evidence, plan, _store = _case(monkeypatch)
    calls = []

    async def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        return _MARKDOWN

    runtime = writer.DocGenWriterRuntime(TracedExecutionContext(course_id="course_multimodal", llm_caller=complete))
    result = asyncio.run(runtime.execute(
        chapter_plan=plan, dense_context=_DENSE_CONTEXT, digest_mode="systematic",
        material_context=material, visual_evidence=evidence,
    ))

    assert len(calls) == 1
    messages, kwargs = calls[0]
    content = messages[-1]["content"]
    images = [block for block in content if block["type"] == "image_url"]
    assert len(images) == 2
    assert _DENSE_CONTEXT in content[0]["text"]
    assert all(block["image_url"]["detail"] == "high" for block in images)
    assert all(block["image_url"]["url"].startswith("data:image/png;base64,") for block in images)
    assert "[IMAGE_BEGIN image_id=img_1]" in content[2]["text"]
    assert kwargs["api_mode"] == "chat_completions"
    assert result.metadata["writer_reread_image_ids"] == ["img_1", "img_2"]
    assert "base64" not in json.dumps(sanitize_langsmith_value(messages, capture_text=True))
    assert "base64" not in json.dumps(asdict(result), ensure_ascii=False)


@pytest.mark.parametrize("failure", ["error", "empty"])
def test_failed_image_call_retries_text_without_changing_context(monkeypatch, failure) -> None:
    material, evidence, plan, _store = _case(monkeypatch)
    calls = []

    async def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        if len(calls) == 1:
            if failure == "error":
                raise RuntimeError("gateway rejected images")
            return ""
        return _MARKDOWN

    runtime = writer.DocGenWriterRuntime(TracedExecutionContext(course_id="course_multimodal", llm_caller=complete))
    result = asyncio.run(runtime.execute(
        chapter_plan=plan, dense_context=_DENSE_CONTEXT, digest_mode="systematic",
        material_context=material, visual_evidence=evidence,
    ))

    assert len(calls) == 2
    assert isinstance(calls[0][0][-1]["content"], list)
    assert isinstance(calls[1][0][-1]["content"], str)
    assert _DENSE_CONTEXT in calls[1][0][-1]["content"]
    assert "api_mode" not in calls[1][1]
    assert calls[1][1]["extra_metadata"]["writer_reread_image_count"] == 0
    assert result.metadata["writer_reread_fallback_text_only"] is True
    assert result.metadata["writer_reread_image_ids"] == []
    assert result.metadata["writer_reread_attempted_image_ids"] == ["img_1", "img_2"]


def test_writer_without_recommended_images_preserves_text_only_path(monkeypatch) -> None:
    material, evidence, plan, store = _case(monkeypatch)
    calls = []

    async def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        return _MARKDOWN

    runtime = writer.DocGenWriterRuntime(TracedExecutionContext(course_id="course_multimodal", llm_caller=complete))
    result = asyncio.run(runtime.execute(
        chapter_plan=plan, dense_context=_DENSE_CONTEXT, digest_mode="systematic",
        material_context=material, visual_evidence=[evidence[0]],
    ))

    assert len(calls) == 1
    assert isinstance(calls[0][0][-1]["content"], str)
    assert "api_mode" not in calls[0][1]
    assert store.reads == []
    assert result.metadata["writer_reread_attempted_image_ids"] == []


@pytest.mark.parametrize("stream_fails", [False, True])
def test_writer_stream_uses_images_and_degrades_to_text_on_failure(monkeypatch, stream_fails) -> None:
    material, evidence, plan, _store = _case(monkeypatch)
    stream_calls = []
    completion_calls = []
    previews = []

    async def stream(messages, **kwargs):
        stream_calls.append((messages, kwargs))
        if stream_fails:
            raise RuntimeError("stream failed")
        yield _MARKDOWN

    async def complete(messages, **kwargs):
        completion_calls.append((messages, kwargs))
        return _MARKDOWN

    async def preview(markdown):
        previews.append(markdown)

    monkeypatch.setattr(writer, "acompletion_stream", stream)
    monkeypatch.setattr(TracedExecutionContext, "resolve_llm_caller", lambda _self: complete)
    runtime = writer.DocGenWriterRuntime(TracedExecutionContext(course_id="course_multimodal"))
    result = asyncio.run(runtime.execute(
        chapter_plan=plan, dense_context=_DENSE_CONTEXT, digest_mode="systematic",
        material_context=material, visual_evidence=evidence, on_stream_update=preview,
    ))

    assert len(stream_calls) == 1
    assert isinstance(stream_calls[0][0][-1]["content"], list)
    assert stream_calls[0][1]["api_mode"] == "chat_completions"
    if stream_fails:
        assert len(completion_calls) == 1
        assert isinstance(completion_calls[0][0][-1]["content"], str)
        assert result.metadata["writer_reread_fallback_text_only"] is True
    else:
        assert completion_calls == []
        assert previews[-1] == _MARKDOWN
        assert result.metadata["writer_reread_image_count"] == 2


def test_chapter_node_passes_routed_original_to_writer_and_records_reread(monkeypatch) -> None:
    material, evidence, plan, _store = _case(monkeypatch)
    stream_messages = []

    async def research(_self, **kwargs):
        assert any("img_1" in section.digest_chunk_uid for section in kwargs["local_sections"])
        return TracedExecutionResult()

    async def run_writer(self, **kwargs):
        return await self.execute(**kwargs)

    async def stream(messages, **kwargs):
        stream_messages.append(messages)
        yield _MARKDOWN

    async def unit_test(**kwargs):
        return kwargs["body_markdown"]

    async def progress(*args, **kwargs):
        pass

    def ignore(*args, **kwargs):
        pass

    monkeypatch.setattr(generate_chapters.DocGenChapterContextRuntime, "run", research)
    monkeypatch.setattr(writer.DocGenWriterRuntime, "run", run_writer)
    monkeypatch.setattr(writer, "acompletion_stream", stream)
    monkeypatch.setattr(generate_chapters, "generate_chapter_unit_test_markdown", unit_test)
    monkeypatch.setattr(generate_chapters, "publish_docgen_progress", progress)
    for name in ("publish_workflow_stream_event", "upsert_knowledge_build_chapter_progress",
                 "upsert_knowledge_build_chapter_preview", "append_knowledge_build_recent_event"):
        monkeypatch.setattr(generate_chapters, name, ignore)
    task = ChapterGenerationTask(
        chapter_index=1, confirmed_title="Custom architecture", concept_targets=["beta"],
        source_slices=plan["source_slices"], min_word_count=1, target_word_count=1200,
    )
    context = WorkflowContext(
        workflow_name="digest.docgen_multimodal", course_id="course_multimodal", event_bus=InProcessEventBus(),
    )
    state = {
        "course_id": "course_multimodal", "requested_at": utcnow(), "total_chapters": 1,
        "shared_inputs": material, "chapter_task": task.model_dump(mode="json"),
        "digest_mode": "systematic", "visual_evidence_items": [evidence[1].model_dump(mode="json")],
    }
    result = asyncio.run(generate_chapters.build_generate_chapters_node(context=context)(state))

    assert len(stream_messages) == 1
    image_blocks = [block for block in stream_messages[0][-1]["content"] if block["type"] == "image_url"]
    assert len(image_blocks) == 1
    draft = result["chapter_drafts"][0]
    assert draft["source_scope"]["writer_reread_image_ids"] == ["img_1"]
    assert draft["source_scope"]["writer_reread_fallback_text_only"] is False
    assert any(detail.get("image_id") == "img_1" for detail in draft["source_details"])
    assert "base64" not in json.dumps(result, ensure_ascii=False)
    assert len(material.section_packets) == 1
