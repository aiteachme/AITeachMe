from __future__ import annotations

import asyncio
import re

import pytest

import app.shared.infra.llm_support.scheduler as llm_scheduler
from app.workflows.digest.common import material_digest
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib import file_summaries
from app.workflows.digest.docgen.lib.models import ChapterSourceSlice, FileMaterialSummary


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _source_packet(*, file_id: str, sections: list[SectionPacket]) -> SourcePacket:
    return SourcePacket(
        file_id=file_id,
        filename=f"{file_id}.md",
        filetype=".md",
        markdown_path="",
        asset_dir="",
        normalized_content="\n\n".join(section.normalized_content for section in sections),
        char_count=sum(section.char_count for section in sections),
        has_formulas=False,
        has_tables=False,
        has_images=False,
        image_refs=[],
    )


def _section(index: int, *, file_id: str = "file_1", repeat: int = 700) -> SectionPacket:
    content = f"第 {index + 1} 节 主题内容。" + ("知识点说明。" * repeat)
    return SectionPacket(
        digest_chunk_uid=f"rf_{file_id}_sec_{index:03d}_test",
        source_file_id=file_id,
        source_filename=f"{file_id}.md",
        chunk_index=index,
        page_num=index + 1,
        title=f"第 {index + 1} 节",
        header_path=f"第 {index + 1} 节",
        level=2,
        normalized_content=content,
        preview=content[:120],
        char_count=len(content),
        formula_refs=[],
        question_block_count=0,
        header_candidates=[f"第 {index + 1} 节"],
        image_refs=[],
    )


@pytest.mark.anyio
async def test_docgen_summarize_files_batches_single_long_file(monkeypatch) -> None:
    sections = [_section(index) for index in range(48)]
    packet = _source_packet(file_id="file_1", sections=sections)
    context = DigestMaterialContext(source_documents=[packet], material_sections=sections)
    calls: list[str] = []

    async def fake_completion(messages, **kwargs):
        prompt = messages[-1]["content"]
        calls.append(prompt)
        match = re.search(r"rf_file_1_sec_\d{3}_test", prompt)
        section_ref = match.group(0) if match else sections[0].digest_chunk_uid
        return FileMaterialSummary(
            summary=f"批次摘要 {len(calls)}",
            concepts=[f"概念 {len(calls)}"],
            chapter_affinity={1: 0.8},
            chapter_slices=[
                ChapterSourceSlice(
                    chapter_index=1,
                    section_ref=section_ref,
                    relevance=0.9,
                    usage="definition",
                    summary="适合作为章节定义材料",
                )
            ],
            source_quality=0.8,
        )

    monkeypatch.setattr(file_summaries, "acompletion_with_fallback", fake_completion)
    monkeypatch.setattr(llm_scheduler, "get_llm_concurrency_limit", lambda: 16)

    summaries = await file_summaries.summarize_files(
        context,
        chapters=[{"chapter_index": 1, "title": "核心主题"}],
        digest_mode="systematic",
    )

    assert len(calls) > 1
    assert len(summaries) == 1
    assert summaries[0].summary_mode == "llm_section_batches"
    assert summaries[0].llm_call_count == len(calls)
    assert len(summaries[0].chapter_slices) == len(calls)


def test_docgen_long_file_batch_count_is_not_capped_by_concurrency() -> None:
    sections = [_section(index, repeat=200) for index in range(240)]
    packet = _source_packet(file_id="file_1", sections=sections)

    batches = file_summaries._build_long_file_section_batches(packet, sections)

    assert len(batches) > 2
    assert max(len(batch.sections) for batch in batches) <= file_summaries._FILE_SUMMARY_MAX_SECTIONS_PER_BATCH


def test_docgen_merge_chapter_slices_balances_across_chapters() -> None:
    summaries = [
        FileMaterialSummary(
            file_id="file_1",
            chapter_slices=[
                *[
                    ChapterSourceSlice(
                        chapter_index=1,
                        file_id="file_1",
                        section_ref=f"rf_file_1_sec_{index:03d}_test",
                        relevance=0.95 - (index * 0.001),
                    )
                    for index in range(60)
                ],
                *[
                    ChapterSourceSlice(
                        chapter_index=chapter_index,
                        file_id="file_1",
                        section_ref=f"rf_file_1_sec_ch{chapter_index:02d}_test",
                        relevance=0.7,
                    )
                    for chapter_index in range(2, 11)
                ],
            ],
        )
    ]

    merged = file_summaries._merge_chapter_slices(summaries)
    merged_chapters = {source_slice.chapter_index for source_slice in merged}

    assert len(merged) == file_summaries._FILE_SUMMARY_MAX_MERGED_CHAPTER_SLICES
    assert set(range(1, 11)).issubset(merged_chapters)


@pytest.mark.anyio
async def test_docgen_summarize_files_uses_one_global_concurrency_gate(monkeypatch) -> None:
    sections = [
        *[_section(index, file_id="file_1") for index in range(48)],
        *[_section(index, file_id="file_2") for index in range(48)],
    ]
    packets = [
        _source_packet(file_id="file_1", sections=[section for section in sections if section.source_file_id == "file_1"]),
        _source_packet(file_id="file_2", sections=[section for section in sections if section.source_file_id == "file_2"]),
    ]
    context = DigestMaterialContext(source_documents=packets, material_sections=sections)
    active_calls = 0
    max_active_calls = 0
    calls: list[str] = []

    async def fake_completion(messages, **kwargs):
        nonlocal active_calls, max_active_calls
        prompt = messages[-1]["content"]
        calls.append(prompt)
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        try:
            await asyncio.sleep(0.01)
            match = re.search(r"rf_file_\d_sec_\d{3}_test", prompt)
            section_ref = match.group(0) if match else sections[0].digest_chunk_uid
            return FileMaterialSummary(
                summary=f"批次摘要 {len(calls)}",
                chapter_affinity={1: 0.8},
                chapter_slices=[
                    ChapterSourceSlice(
                        chapter_index=1,
                        section_ref=section_ref,
                        relevance=0.9,
                        usage="definition",
                        summary="适合作为章节定义材料",
                    )
                ],
                source_quality=0.8,
            )
        finally:
            active_calls -= 1

    monkeypatch.setattr(file_summaries, "acompletion_with_fallback", fake_completion)
    monkeypatch.setattr(llm_scheduler, "get_llm_concurrency_limit", lambda: 2)

    summaries = await file_summaries.summarize_files(
        context,
        chapters=[{"chapter_index": 1, "title": "核心主题"}],
        digest_mode="systematic",
    )

    assert len(calls) > 2
    assert max_active_calls <= 2
    assert [summary.file_id for summary in summaries] == ["file_1", "file_2"]
    assert all(summary.summary_mode == "llm_section_batches" for summary in summaries)
    assert sum(summary.llm_call_count for summary in summaries) == len(calls)


@pytest.mark.anyio
async def test_planner_material_digest_batches_long_context(monkeypatch) -> None:
    sections = [_section(index, repeat=900) for index in range(48)]
    packet = _source_packet(file_id="file_1", sections=sections)
    context = DigestMaterialContext(source_documents=[packet], material_sections=sections)
    calls: list[str] = []

    async def fake_completion(messages, **kwargs):
        prompt = messages[-1]["content"]
        calls.append(prompt)
        match = re.search(r"rf_file_1_sec_\d{3}_test", prompt)
        section_ref = match.group(0) if match else sections[0].digest_chunk_uid
        return {
            "summary": f"并行摘要 {len(calls)}",
            "topics": [f"主题 {len(calls)}"],
            "structure_hints": [f"结构 {len(calls)}"],
            "high_value_sections": [section_ref],
            "warnings": [],
        }

    monkeypatch.setattr(material_digest, "acompletion_with_fallback", fake_completion)
    monkeypatch.setattr(llm_scheduler, "get_llm_concurrency_limit", lambda: 2)
    monkeypatch.setattr(material_digest, "_estimate_text_tokens", lambda text: max(1, len(text) // 2))

    result = await material_digest.build_material_digest(context)

    assert len(calls) > 2
    assert result.llm_used is True
    assert "上传资料并行切片摘要" in result.digest
    assert "已完整拼接" not in result.digest
