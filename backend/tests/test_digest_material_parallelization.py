from __future__ import annotations

import pytest

from app.workflows.digest.common import material_digest
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib import file_summaries
from app.workflows.digest.docgen.lib.file_summaries import derive_source_affinity_and_evidence
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


def _section(
    index: int,
    *,
    title: str,
    body: str,
    file_id: str = "file_1",
    repeat: int = 1,
) -> SectionPacket:
    content = (body + " ") * repeat
    return SectionPacket(
        digest_chunk_uid=f"rf_{file_id}_sec_{index:03d}_test",
        source_file_id=file_id,
        source_filename=f"{file_id}.md",
        chunk_index=index,
        page_num=index + 1,
        title=title,
        header_path=title,
        level=2,
        normalized_content=content,
        preview=content[:240],
        char_count=len(content),
        formula_refs=[],
        question_block_count=0,
        header_candidates=[title],
        image_refs=[],
    )


@pytest.mark.anyio
async def test_docgen_routes_complete_sections_semantically_to_confirmed_chapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections = [
        _section(
            0,
            title="矩阵乘法",
            body="矩阵乘法的维度条件、行列计算和结合律。",
        ),
        _section(
            1,
            title="面积计算",
            body="三角形面积、圆形面积和单位换算。",
        ),
    ]
    packet = _source_packet(file_id="file_1", sections=sections)
    context = DigestMaterialContext(source_documents=[packet], material_sections=sections)
    chapters = [
        {
            "chapter_index": 1,
            "title": "矩阵乘法",
            "objective": "掌握矩阵乘法",
        },
        {
            "chapter_index": 2,
            "title": "面积计算",
            "objective": "掌握几何面积计算",
        },
    ]

    captured_messages: list[dict[str, str]] = []

    async def fake_completion(messages, **kwargs):
        del kwargs
        captured_messages.extend(messages)
        return FileMaterialSummary(
            summary="矩阵运算与几何测量资料",
            chapter_slices=[
                ChapterSourceSlice(
                    chapter_index=1,
                    section_ref=sections[0].digest_chunk_uid,
                    relevance=0.94,
                    usage="definition",
                    summary="矩阵乘法的维度和行列规则",
                ),
                ChapterSourceSlice(
                    chapter_index=2,
                    section_ref=sections[1].digest_chunk_uid,
                    relevance=0.91,
                    usage="example",
                    summary="面积公式与单位换算",
                ),
            ],
            source_quality=0.9,
        )

    monkeypatch.setattr(file_summaries, "acompletion_with_fallback", fake_completion)
    summaries = await file_summaries.summarize_files(
        context,
        chapters=chapters,
        digest_mode="systematic",
    )
    affinity, evidence = derive_source_affinity_and_evidence(
        context,
        summaries=summaries,
        chapters=chapters,
    )

    assert len(summaries) == 1
    assert summaries[0].llm_call_count == 1
    assert summaries[0].fallback_used is False
    prompt = "\n".join(item["content"] for item in captured_messages)
    assert sections[0].normalized_content.strip() in prompt
    assert sections[1].normalized_content.strip() in prompt
    assert '"objective": "掌握矩阵乘法"' in prompt
    refs_by_chapter = {
        item.chapter_index: set(item.section_refs)
        for item in affinity
    }
    assert refs_by_chapter[1] == {sections[0].digest_chunk_uid}
    assert refs_by_chapter[2] == {sections[1].digest_chunk_uid}
    assert {item.source_span for item in evidence} == {
        sections[0].digest_chunk_uid,
        sections[1].digest_chunk_uid,
    }


@pytest.mark.anyio
async def test_planner_material_digest_packs_long_context_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections = [
        _section(
            index,
            title=f"第 {index + 1} 节",
            body=f"第 {index + 1} 节主题内容。知识点说明。",
            repeat=900,
        )
        for index in range(48)
    ]
    packet = _source_packet(file_id="file_1", sections=sections)
    context = DigestMaterialContext(source_documents=[packet], material_sections=sections)
    monkeypatch.setattr(
        material_digest,
        "_estimate_text_tokens",
        lambda text: max(1, len(text) // 2),
    )

    result = await material_digest.build_material_digest(context)

    assert result.llm_used is False
    assert "上传资料结构化摘录" in result.digest
    assert "未经过额外模型改写" in result.digest
    assert sections[0].digest_chunk_uid in result.digest
    assert sections[-1].digest_chunk_uid in result.digest
    assert "已完整拼接" not in result.digest
