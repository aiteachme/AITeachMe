import asyncio

from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_chapter_chunks
from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.kg_doc_sync.lib import incremental_sync
from app.workflows.digest.kg_doc_sync.lib.extraction import ChunkExtractionResult
from app.workflows.digest.kg_doc_sync.lib.extraction import _assign_candidate_ids_and_edge_types
from app.workflows.digest.kg_doc_sync.lib.extraction import _prepare_llm_chunk_content
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    _build_backbone_graph_items,
    _build_extraction_tasks,
)
from app.workflows.digest.kg_doc_sync.lib.models import (
    ChapterSourceContext,
    PendingMarkdownExtractedEdge,
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


def _edge_payload(
    source_anchor: str,
    target_anchor: str,
    *,
    source_name: str,
    target_name: str,
) -> SectionExtractionPayload:
    return SectionExtractionPayload(
        units=[
            MarkdownKnowledgeUnit(
                anchor=source_anchor,
                name=source_name,
                knowledge_unit_type="concept",
                summary="summary",
                body_markdown="body",
                chapter_index=1,
                knowledge_document_id=1,
                source_file_ids=[],
            ),
            MarkdownKnowledgeUnit(
                anchor=target_anchor,
                name=target_name,
                knowledge_unit_type="concept",
                summary="summary",
                body_markdown="body",
                chapter_index=1,
                knowledge_document_id=1,
                source_file_ids=[],
            ),
        ],
        pending_edges=[
            PendingMarkdownExtractedEdge(
                source_candidate_id="n1",
                target_candidate_id="n2",
                source_name=source_name,
                target_name=target_name,
                edge_type="prerequisite_for",
                description="source before target",
                knowledge_document_id=1,
                chapter_index=1,
            )
        ],
        candidate_id_to_anchor={"n1": source_anchor, "n2": target_anchor},
        anchors_by_name={source_name: [source_anchor], target_name: [target_anchor]},
        anchors_by_normalized_name={
            source_name.lower(): [source_anchor],
            target_name.lower(): [target_anchor],
        },
        node_contexts_by_anchor={},
        section_context=SectionExtractionContext(
            section_index=1,
            title=source_name,
            header_path=source_name,
            body_markdown="body",
            primary_anchor=source_anchor,
            primary_name=source_name,
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
            "total_extracted_node_count": 2,
            "total_extracted_edge_count": 1,
        },
    )


def test_section_candidate_ids_are_local_when_payloads_are_combined() -> None:
    _units, edges, _diagnostics = incremental_sync._combine_section_payloads(
        markdown="",
        structured_context={},
        chapters=[],
        sections=[],
        extraction_tasks=[],
        task_metrics={},
        section_payloads=[
            _edge_payload("ku_alpha", "ku_beta", source_name="Alpha", target_name="Beta"),
            _edge_payload("ku_gamma", "ku_delta", source_name="Gamma", target_name="Delta"),
        ],
    )

    edge_pairs = {(edge.source_anchor, edge.target_anchor) for edge in edges}

    assert ("ku_alpha", "ku_beta") in edge_pairs
    assert ("ku_gamma", "ku_delta") in edge_pairs


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
    assert metrics["planned_task_limit"] == incremental_sync._graph_llm_concurrency_cap()
    assert metrics["chapter_split_count"] == 0


def test_published_knowledge_doc_starts_with_first_chapter_without_overview() -> None:
    markdown = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "行列式",
                "markdown": "# 行列式\n\n## 几何意义\n\n行列式描述有向面积或体积。",
            }
        ],
        document_context={"course": "线性代数", "digest_mode": "sprint"},
    )

    assert "\n## 目录\n" not in markdown
    assert "# 知识文档总览" not in markdown
    assert markdown.startswith("# 行列式")


def test_published_knowledge_doc_hides_source_appendix_by_default() -> None:
    markdown = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "DOS 命令",
                "markdown": "# DOS 命令\n\n## PROMPT\n\n`PROMPT $P$G` 用于设置提示符。",
                "source_details": [
                    {
                        "url": "local://file/abc#L1-L3",
                        "title": "计算机基础.pdf / DOS",
                        "source": "docgen_source_slice",
                        "score": 0.9,
                    }
                ],
            }
        ],
        document_context={"course_id": "course_demo", "digest_mode": "sprint"},
    )

    assert "参考资料与延伸阅读" not in markdown
    assert "计算机基础.pdf" not in markdown
    assert "`PROMPT $P$G`" in markdown


def test_medium_chapters_with_many_sections_split_into_subsection_tasks() -> None:
    markdown = "\n\n".join(
        [
            "# C1\n"
            + "\n".join(f"## C1-S{index}\n" + ("x" * 420) for index in range(1, 7)),
            "# C2\n"
            + "\n".join(f"## C2-S{index}\n" + ("x" * 420) for index in range(1, 7)),
            "# C3\n"
            + "\n".join(f"## C3-S{index}\n" + ("x" * 420) for index in range(1, 7)),
            "# C4\n"
            + "\n".join(f"## C4-S{index}\n" + ("x" * 420) for index in range(1, 7)),
        ]
    )

    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, metrics = _build_extraction_tasks(chapters, {})

    assert len(chapters) == 4
    assert len(tasks) > len(chapters)
    assert len(tasks) <= metrics["planned_task_limit"]
    assert metrics["chapter_split_count"] == 4
    assert metrics["subsection_task_count"] == len(tasks)


def test_legacy_support_edge_type_is_normalized_before_literal_validation() -> None:
    result = ChunkExtractionResult.model_validate(
        {
            "nodes": [
                {
                    "candidate_id": "method",
                    "name": "主成分分析方法",
                    "knowledge_unit_type": "method",
                    "local_summary": "通过特征值和特征向量选择主成分。",
                },
                {
                    "candidate_id": "remark",
                    "name": "主成分分析前需标准化数据提醒",
                    "knowledge_unit_type": "remark",
                    "local_summary": "未标准化会导致量纲大的变量主导主成分方向。",
                },
            ],
            "edges": [
                {
                    "source_name": "主成分分析方法",
                    "target_name": "主成分分析前需标准化数据提醒",
                    "source_candidate_id": "method",
                    "target_candidate_id": "remark",
                    "edge_type": "support",
                    "description": "提醒是方法实施的补充。",
                }
            ],
        }
    )

    assert result.nodes[0].knowledge_unit_type == "procedure"
    assert result.nodes[1].knowledge_unit_type == "misconception"
    assert result.edges[0].edge_type == "explains"


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
    assert units[0].source_file_ids == ["7"]


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


def test_prefetch_payload_reused_when_only_heading_changes() -> None:
    original_markdown = "# Old heading\nSame body"
    final_markdown = "# New heading\nSame body"
    original_chapters = extract_markdown_chapter_chunks(original_markdown, max_body_chars=None)
    original_tasks, _metrics = _build_extraction_tasks(original_chapters, {})
    record = incremental_sync._section_record_for_task(original_tasks[0], payload=_payload("ku_a"))

    units, _edges, diagnostics = asyncio.run(
        incremental_sync._extract_markdown_graph_items_async(
            final_markdown,
            prefetched_records=[record],
        )
    )

    assert diagnostics["prefetch_reused_section_count"] == 1
    assert diagnostics["prefetch_stale_section_count"] == 0
    assert [unit.anchor for unit in units] == ["ku_a"]


def test_docgen_backbone_links_existing_units_and_fills_missing_skeleton_units() -> None:
    structured_context = {
        "docgen_manifest": {
            "document_backbone_snapshot": {
                "canonical_glossary": [
                    {"term": "Alpha", "target_chapters": [1]},
                    {"term": "Beta", "target_chapters": [1]},
                    {"term": "Gamma", "target_chapters": [1]},
                ],
                "concept_dependency_graph": [
                    {"from_concept": "Alpha", "to_concept": "Beta", "relation": "chapter_order"},
                    {"from_concept": "Alpha", "to_concept": "Gamma", "relation": "chapter_order"},
                ],
            }
        }
    }

    units, edges = _build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts={1: ChapterSourceContext(chapter_index=1, title="Chapter 1")},
        existing_normalized_names={"alpha", "beta"},
    )

    assert [unit.name for unit in units] == ["Gamma"]
    assert units[0].source_kind == "docgen_backbone"
    assert len(edges) == 2
    assert edges[0].source_name == "Alpha"
    assert edges[0].target_name == "Beta"
    assert edges[0].source_kind == "docgen_backbone"
    assert edges[1].source_name == "Alpha"
    assert edges[1].target_name == "Gamma"
    assert edges[1].source_kind == "docgen_backbone"


def test_preliminary_kg_creates_rule_seed_units_and_edges() -> None:
    structured_context = {
        "docgen_manifest": {
            "preliminary_kg": {
                "nodes": [
                    {"name": "矩阵基础", "knowledge_unit_type": "topic", "chapter_index": 1, "summary": "章节主题"},
                    {"name": "矩阵乘法", "knowledge_unit_type": "concept", "chapter_index": 1, "summary": "按行列配对求和"},
                ],
                "edges": [
                    {
                        "source_name": "矩阵乘法",
                        "target_name": "矩阵基础",
                        "edge_type": "part_of",
                        "description": "矩阵乘法属于本章。",
                        "chapter_index": 1,
                    }
                ],
            }
        }
    }

    units, edges = _build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts={1: ChapterSourceContext(knowledge_document_id=10, chapter_index=1, source_file_ids=["file-a"])},
        existing_normalized_names=set(),
    )

    assert {unit.name for unit in units} == {"矩阵基础", "矩阵乘法"}
    assert {unit.knowledge_unit_type for unit in units} == {"topic", "concept"}
    assert all(unit.source_kind == "docgen_preliminary_kg" for unit in units)
    assert edges[0].source_name == "矩阵乘法"
    assert edges[0].target_name == "矩阵基础"
    assert edges[0].edge_type == "part_of"
    assert edges[0].source_kind == "docgen_preliminary_kg"


def test_docgen_kg_draft_takes_precedence_over_preliminary_kg() -> None:
    structured_context = {
        "docgen_manifest": {
            "preliminary_kg": {
                "nodes": [
                    {"name": "粗略节点", "knowledge_unit_type": "concept", "chapter_index": 1},
                ],
            },
            "docgen_kg_draft": {
                "nodes": [
                    {
                        "name": "细化节点",
                        "knowledge_unit_type": "skill",
                        "chapter_index": 1,
                        "summary": "来自发布前图谱草稿。",
                        "source": "kg_prefetch_llm",
                    },
                ],
            },
        }
    }

    units, edges = _build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts={1: ChapterSourceContext(knowledge_document_id=10, chapter_index=1, source_file_ids=["file-a"])},
        existing_normalized_names=set(),
    )

    assert edges == []
    assert [unit.name for unit in units] == ["细化节点"]
    assert units[0].knowledge_unit_type == "skill"
    assert units[0].source_kind == "kg_prefetch_llm"


def test_chunk_extraction_result_caps_candidate_counts() -> None:
    result = ChunkExtractionResult.model_validate(
        {
            "nodes": [
                {
                    "candidate_id": f"n{index}",
                    "name": f"Node {index}",
                    "knowledge_unit_type": "concept",
                    "local_summary": "summary",
                }
                for index in range(12)
            ],
            "edges": [
                {
                    "source_name": "Node 0",
                    "target_name": "Node 1",
                    "edge_type": "prerequisite_for",
                    "description": "description",
                }
                for _index in range(14)
            ],
        }
    )

    assert len(result.nodes) == 8
    assert len(result.edges) == 12


def test_chunk_extraction_drops_edges_with_unreturned_endpoints() -> None:
    result = ChunkExtractionResult.model_validate(
        {
            "nodes": [
                {
                    "candidate_id": "core",
                    "name": "核心对象",
                    "knowledge_unit_type": "concept",
                    "local_summary": "本节说明核心对象。",
                },
                {
                    "candidate_id": "method",
                    "name": "操作方法",
                    "knowledge_unit_type": "procedure",
                    "local_summary": "本节给出操作方法。",
                },
            ],
            "edges": [
                {
                    "source_name": "核心对象",
                    "target_name": "操作方法",
                    "edge_type": "applies_to",
                    "description": "核心对象用于操作方法。",
                },
                {
                    "source_name": "核心对象",
                    "target_name": "不存在的练习",
                    "source_candidate_id": "core",
                    "target_candidate_id": "fabricated",
                    "edge_type": "assesses",
                    "description": "端点不在本次节点中。",
                },
            ],
        }
    )

    finalized = _assign_candidate_ids_and_edge_types(result)

    assert len(finalized.edges) == 1
    assert finalized.edges[0].source_candidate_id == "core"
    assert finalized.edges[0].target_candidate_id == "method"


def test_prepare_llm_chunk_content_removes_callout_markers_but_keeps_body() -> None:
    prepared = _prepare_llm_chunk_content(
        "# 数据标准化\n\n"
        "> [!WARNING]\n"
        ">\n"
        "> ⚠️ **易错点**：不要把未标准化的数据直接用于主成分分析。\n\n"
        "[!TIP]\n"
        "💡 快速抓手：先检查变量量纲。"
    )

    assert "[!WARNING]" not in prepared
    assert "[!TIP]" not in prepared
    assert "易错点" in prepared
    assert "快速抓手" in prepared
