import asyncio

from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_chapter_chunks
from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
from app.workflows.digest.kg_doc_sync.lib import incremental_sync
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import _build_extraction_tasks
from app.workflows.digest.kg_doc_sync.lib.models import (
    SectionExtractionContext,
    SectionExtractionPayload,
)


def _payload(anchor: str, *, name: str = "概念 A") -> SectionExtractionPayload:
    return SectionExtractionPayload(
        units=[
            MarkdownKnowledgeUnit(
                anchor=anchor,
                name=name,
                knowledge_unit_type="concept",
                summary="summary",
                body_markdown="body",
                chapter_index=0,
                knowledge_document_id=None,
                source_file_ids=[],
            )
        ],
        pending_edges=[],
        candidate_id_to_anchor={"c1": anchor},
        anchors_by_name={name: [anchor]},
        anchors_by_normalized_name={name.lower(): [anchor]},
        node_contexts_by_anchor={
            anchor: {
                "name": name,
                "knowledge_unit_type": "concept",
                "section_index": 0,
                "knowledge_document_id": None,
                "source_file_ids": [],
            }
        },
        section_context=SectionExtractionContext(
            section_index=0,
            title="概念 A",
            header_path="概念 A",
            body_markdown="body",
            primary_anchor=anchor,
            primary_name=name,
            primary_type="concept",
        ),
        diagnostics={
            "section_count": 0,
            "successful_section_count": 1,
            "failed_section_count": 0,
            "llm_section_count": 1,
            "markdown_short_circuit_section_count": 0,
            "llm_error_count": 0,
            "empty_llm_result_count": 0,
            "empty_repair_attempt_count": 0,
            "empty_repair_success_count": 0,
            "total_extracted_node_count": 1,
            "total_extracted_edge_count": 0,
        },
    )


def test_long_chapter_is_split_with_untruncated_body() -> None:
    markdown = "# Doc\n## Long chapter\n" + "\n".join(
        f"### S{index}\n" + ("x" * 1800)
        for index in range(1, 11)
    )

    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, metrics = _build_extraction_tasks(chapters, {})

    assert len(tasks) > 1
    assert len(tasks) <= metrics["planned_task_limit"]
    assert metrics["chapter_split_count"] == 1
    assert metrics["subsection_task_count"] == len(tasks)


def test_many_chapters_keep_chapter_tasks_and_limit_parallel_lanes() -> None:
    markdown = "\n".join(
        f"# C{index}\n" + ("x" * 1000)
        for index in range(1, 15)
    )

    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, metrics = _build_extraction_tasks(chapters, {})

    assert len(tasks) == len(chapters)
    assert metrics["planned_task_limit"] == 20
    assert metrics["chapter_split_count"] == 0


def test_prefetched_section_payload_is_reused_and_context_is_finalized() -> None:
    markdown = "# C1\n正文"
    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, _metrics = _build_extraction_tasks(chapters, {})
    record = incremental_sync._section_record_for_task(tasks[0], payload=_payload("ku_a"))

    units, _edges, diagnostics = asyncio.run(
        incremental_sync._extract_markdown_graph_items_async(
            markdown,
            structured_context={
                "chapters": [
                    {
                        "chapter_index": 1,
                        "knowledge_document_id": 42,
                        "source_file_ids": [7],
                    }
                ]
            },
            prefetched_records=[record],
        )
    )

    assert diagnostics["prefetch_reused_section_count"] == 1
    assert diagnostics["prefetch_catchup_section_count"] == 0
    assert units[0].knowledge_document_id == 42
    assert units[0].source_file_ids == [7]


def test_stale_prefetch_payload_falls_back_to_catchup(monkeypatch) -> None:
    original_markdown = "# C1\n旧正文"
    final_markdown = "# C1\n新正文"
    chapters = extract_markdown_chapter_chunks(original_markdown, max_body_chars=None)
    tasks, _metrics = _build_extraction_tasks(chapters, {})
    record = incremental_sync._section_record_for_task(tasks[0], payload=_payload("ku_old"))

    async def fake_extract(*args, **kwargs):
        del args, kwargs
        return _payload("ku_new", name="概念 B")

    monkeypatch.setattr(incremental_sync, "_extract_chapter_with_retries", fake_extract)

    units, _edges, diagnostics = asyncio.run(
        incremental_sync._extract_markdown_graph_items_async(
            final_markdown,
            prefetched_records=[record],
        )
    )

    assert diagnostics["prefetch_reused_section_count"] == 0
    assert diagnostics["prefetch_catchup_section_count"] == 1
    assert diagnostics["prefetch_stale_section_count"] == 1
    assert [unit.anchor for unit in units] == ["ku_new"]
