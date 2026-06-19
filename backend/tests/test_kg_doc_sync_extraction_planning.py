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
    _build_chapter_membership_edges,
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
    assert metrics["planned_task_limit"] == incremental_sync._planned_extraction_task_limit()
    assert incremental_sync._effective_concurrency_limit(len(tasks)) == min(
        len(tasks),
        incremental_sync._graph_llm_concurrency_cap(),
    )
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
    assert result.nodes[1].knowledge_unit_type == "concept"
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


def test_docgen_backbone_payload_does_not_seed_knowledge_units_by_rule() -> None:
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

    assert [unit.name for unit in units] == ["Chapter 1"]
    assert units[0].source_kind == "structural_heading"
    assert edges == []


def test_preliminary_kg_does_not_seed_rule_units_and_edges() -> None:
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

    assert units == []
    assert edges == []


def test_course_root_links_chapter_topics_from_structured_context() -> None:
    structured_context = {
        "document_summary_json": {
            "course_name": "初中数学",
        }
    }

    units, edges = _build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts={
            1: ChapterSourceContext(knowledge_document_id=10, chapter_index=1, title="函数"),
            2: ChapterSourceContext(knowledge_document_id=11, chapter_index=2, title="几何"),
        },
        existing_normalized_names=set(),
    )

    assert {unit.name for unit in units} == {"初中数学", "函数", "几何"}
    assert {unit.name: unit.knowledge_unit_type for unit in units} == {
        "初中数学": "topic",
        "函数": "topic",
        "几何": "topic",
    }
    assert {
        (edge.source_name, edge.target_name, edge.edge_type, edge.source_kind)
        for edge in edges
    } == {
        ("函数", "初中数学", "part_of", "structural_heading"),
        ("几何", "初中数学", "part_of", "structural_heading"),
    }


def test_chapter_membership_edges_attach_llm_units_to_chapter_topic() -> None:
    units = [
        MarkdownKnowledgeUnit(
            anchor="ku_chapter",
            name="函数的基本概念、图像与读图方法",
            knowledge_unit_type="topic",
            summary="章节主题",
            body_markdown="章节主题",
            chapter_index=1,
        ),
        MarkdownKnowledgeUnit(
            anchor="ku_method",
            name="代入求函数值",
            knowledge_unit_type="procedure",
            summary="把自变量代入表达式求函数值。",
            body_markdown="把自变量代入表达式求函数值。",
            chapter_index=1,
        ),
    ]

    edges = _build_chapter_membership_edges(
        units=units,
        chapter_contexts={1: ChapterSourceContext(chapter_index=1, title="函数的基本概念、图像与读图方法")},
        anchors_by_normalized_name={
            "函数的基本概念图像与读图方法": ["ku_chapter"],
            "代入求函数值": ["ku_method"],
        },
    )

    assert [
        (edge.source_name, edge.target_name, edge.edge_type, edge.source_kind)
        for edge in edges
    ] == [
        ("代入求函数值", "函数的基本概念、图像与读图方法", "part_of", "structural_heading")
    ]


def test_stale_docgen_context_only_contributes_structural_topics() -> None:
    structured_context = {
        "document_summary_json": {
            "course_name": "函数课程",
        },
        "docgen_manifest": {
            "document_backbone_snapshot": {
                "canonical_glossary": [
                    {
                        "term": "围绕函数讲清核心概念、图示、方法步骤、典型例题、易错点、练习、单元测试。",
                        "definition": "教学安排句。",
                        "target_chapters": [1],
                    },
                    {
                        "term": "函数图像",
                        "definition": "用坐标图表示函数关系。",
                        "target_chapters": [1],
                    },
                    {
                        "term": "建立函数、变量、自变量与因变量的基本概念，理解函数关系的表达方式",
                        "definition": "教学动作句。",
                        "target_chapters": [1],
                    },
                ],
                "concept_dependency_graph": [
                    {
                        "from_concept": "围绕函数讲清核心概念、图示、方法步骤、典型例题、易错点、练习、单元测试。",
                        "to_concept": "函数",
                        "relation": "prerequisite_for",
                    },
                    {
                        "from_concept": "函数",
                        "to_concept": "函数图像",
                        "relation": "prerequisite_for",
                    },
                ],
            },
            "preliminary_kg": {
                "nodes": [
                    {"name": "函数", "knowledge_unit_type": "concept", "chapter_index": 1},
                    {"name": "图示", "knowledge_unit_type": "application_case", "chapter_index": 1},
                    {"name": "方法步骤", "knowledge_unit_type": "procedure", "chapter_index": 1},
                    {"name": "单元测试", "knowledge_unit_type": "skill", "chapter_index": 1},
                    {"name": "重点检查概念理解", "knowledge_unit_type": "procedure", "chapter_index": 1},
                    {"name": "讲后纠错与回顾", "knowledge_unit_type": "misconception", "chapter_index": 1},
                    {"name": "为后续章节打底", "knowledge_unit_type": "concept", "chapter_index": 1},
                    {"name": "结合图示认识函数图像", "knowledge_unit_type": "concept", "chapter_index": 1},
                    {"name": "配套例题：函数值求解", "knowledge_unit_type": "application_case", "chapter_index": 1},
                    {"name": "常见易错点：自变量与因变量混淆", "knowledge_unit_type": "misconception", "chapter_index": 1},
                    {"name": "整理", "knowledge_unit_type": "procedure", "chapter_index": 1},
                    {"name": "判定题", "knowledge_unit_type": "skill", "chapter_index": 1},
                    {"name": "图表分析", "knowledge_unit_type": "skill", "chapter_index": 1},
                    {
                        "name": "在本章内完成总结巩固，围绕自身题型完成检测、纠错与复习收束",
                        "knowledge_unit_type": "misconception",
                        "chapter_index": 1,
                    },
                    {"name": "自变量与因变量", "knowledge_unit_type": "concept", "chapter_index": 1},
                ],
                "edges": [
                    {"source_name": "图示", "target_name": "函数", "edge_type": "part_of", "chapter_index": 1},
                    {"source_name": "配套例题：函数值求解", "target_name": "函数", "edge_type": "applies_to", "chapter_index": 1},
                    {"source_name": "自变量与因变量", "target_name": "函数", "edge_type": "part_of", "chapter_index": 1},
                ],
            }
        }
    }

    units, edges = _build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts={1: ChapterSourceContext(knowledge_document_id=10, chapter_index=1, title="函数的基本概念")},
        existing_normalized_names=set(),
    )

    assert {unit.name for unit in units} == {"函数课程", "函数的基本概念"}
    assert [(edge.source_name, edge.target_name, edge.edge_type) for edge in edges] == [
        ("函数的基本概念", "函数课程", "part_of")
    ]


def test_quality_checked_docgen_kg_draft_uses_dedicated_payload_path() -> None:
    payload = incremental_sync.build_docgen_kg_draft_units_payload(
        docgen_kg_draft={
            "quality_ready": True,
            "fast_visible_ready": True,
            "quality_status": "ready",
            "quality_audit": {
                "quality_ready": True,
                "warning_count": 0,
                "missing_chapter_count": 0,
                "edge_endpoint_issue_count": 0,
                "edge_endpoint_ambiguity_count": 0,
                "relation_direction_issue_count": 0,
                "examine_profile_ready": True,
                "downstream_unit_count": 1,
            },
            "nodes": [
                {
                    "name": "细化节点",
                    "knowledge_unit_type": "skill",
                    "chapter_index": 1,
                    "summary": "来自发布前图谱草稿。",
                    "source": "kg_prefetch_llm",
                },
            ],
        }
    )

    units = payload.units
    edges = payload.extracted_edges
    assert payload.diagnostics_totals["docgen_draft_quality_ready"] == 1
    assert [unit.name for unit in units] == ["细化节点"]
    assert units[0].knowledge_unit_type == "skill"
    assert units[0].source_kind == "kg_prefetch_llm"
    assert edges == []


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
            for index in range(16)
            ],
            "edges": [
                {
                    "source_name": "Node 0",
                    "target_name": "Node 1",
                    "edge_type": "prerequisite_for",
                    "description": "description",
                }
            for _index in range(20)
            ],
        }
    )

    assert len(result.nodes) == 12
    assert len(result.edges) == 18


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


def test_prepare_llm_chunk_content_does_not_trim_normal_long_sections() -> None:
    long_body = "函数连续性判定需要同时比较左极限、右极限和函数值。\n" * 700

    prepared = _prepare_llm_chunk_content(long_body)

    assert prepared == long_body.strip()
    assert "中间内容已压缩" not in prepared
