from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
from app.models import Course, KnowledgeEdge, KnowledgeUnit
import app.workflows.digest.kg_doc_sync.lib.incremental_sync as sync
from app.workflows.digest.common.markdown_knowledge_anchors import (
    MarkdownKnowledgeUnit,
    MarkdownSectionChunk,
    extract_markdown_chapter_chunks,
    extract_markdown_section_chunks,
)
from app.workflows.digest.kg_doc_sync.lib.models import (
    ChapterSourceContext,
    PendingMarkdownExtractedEdge,
    SectionExtractionContext,
    SectionExtractionPayload,
)


COURSE_ID = "course_kgsync000000"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(Course(id=COURSE_ID, user_id="user-kg", name="KG Sync"))
        db.commit()
        yield db


def _unit(anchor: str, name: str, *, chapter_index: int = 1, source_kind: str = "llm_section") -> MarkdownKnowledgeUnit:
    return MarkdownKnowledgeUnit(
        anchor=anchor,
        name=name,
        summary=f"{name} summary",
        body_markdown=f"## {name}\n{name} body",
        knowledge_unit_type="core_knowledge",
        source_kind=source_kind,
        chapter_index=chapter_index,
    )


def _payload(
    *,
    unit: MarkdownKnowledgeUnit,
    candidate_id: str,
    primary: bool = True,
    pending_edges: list[PendingMarkdownExtractedEdge] | None = None,
) -> SectionExtractionPayload:
    return SectionExtractionPayload(
        units=[unit],
        pending_edges=list(pending_edges or []),
        candidate_id_to_anchor={candidate_id: unit.anchor},
        anchors_by_name={unit.name: [unit.anchor]},
        anchors_by_normalized_name={sync.normalize_name(unit.name): [unit.anchor]},
        node_contexts_by_anchor={
            unit.anchor: {
                "name": unit.name,
                "knowledge_unit_type": unit.knowledge_unit_type,
                "taxonomy_hint": "Parent" if unit.name == "Child" else "",
                "parent_entity_name": "Parent" if unit.name == "Child" else "",
                "section_index": unit.chapter_index,
                "knowledge_document_id": 10 + unit.chapter_index,
                "source_file_ids": ["file-a"],
            }
        },
        section_context=SectionExtractionContext(
            section_index=unit.chapter_index,
            title=unit.name,
            header_path=f"Parent > {unit.name}" if unit.name == "Child" else unit.name,
            body_markdown=f"{unit.name} uses Parent for application",
            primary_anchor=unit.anchor if primary else None,
            primary_name=unit.name if primary else "",
            primary_type=unit.knowledge_unit_type,
            knowledge_document_id=10 + unit.chapter_index,
            source_file_ids=["file-a"],
        ),
        diagnostics={
            "successful_section_count": 1,
            "llm_section_count": 1,
            "total_extracted_node_count": 1,
            "total_extracted_edge_count": len(pending_edges or []),
        },
    )


def test_context_payloads_build_chapter_hints_and_backbone() -> None:
    structured_context = {
        "chapters": [
            {
                "knowledge_document_id": 101,
                "chapter_index": "1",
                "title": "Limits",
                "summary": "Limit chapter",
                "source_file_ids": ["file-a", "file-a", ""],
            },
            {"chapter_index": 0, "title": "ignored"},
        ],
        "document_summary_json": {
            "chapters": [
                {
                    "chapter_index": 1,
                    "digest_mode": "sprint",
                    "objective": "掌握极限",
                    "concept_targets": ["Limit", "Limit", "Continuity"],
                    "example_coverage_plan": [{"target": "epsilon-delta examples"}],
                }
            ],
            "docgen_learning_backbone": {
                "canonical_glossary": [{"term": "Limit", "target_chapters": [1]}],
                "concept_dependency_graph": [
                    {"from_concept": "Limit", "to_concept": "Continuity", "relation": "chapter_order", "reason": "needs first"}
                ],
            },
        },
        "docgen_manifest": {
            "chapter_task_seeds": [{"chapter_index": 1, "required_elements": ["Derivative"]}],
        },
    }

    payloads = sync._docgen_chapter_payloads_by_index(structured_context)
    digest_mode, hints = sync._chapter_docgen_hints(payloads[1])
    contexts = sync._chapter_context_lookup(structured_context)
    backbone = sync._document_backbone_payload(structured_context)

    assert digest_mode == "sprint"
    assert any("Limit" in hint and "Continuity" in hint for hint in hints)
    assert contexts[1].knowledge_document_id == 101
    assert contexts[1].source_file_ids == ["file-a"]
    assert sync._chapter_context_for_index(contexts, 99).chapter_index == 99
    assert backbone["canonical_glossary"][0]["term"] == "Limit"


def test_extraction_task_planning_splits_large_chapters_and_hashes_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_max_parallel_extractions", lambda: 4)
    monkeypatch.setattr(sync, "_graph_llm_concurrency_cap", lambda: 4)
    monkeypatch.setattr(sync, "_DOCS_SYNC_SPLIT_MIN_CHILD_SECTIONS", 2)
    monkeypatch.setattr(sync, "_DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS", 10)
    monkeypatch.setattr(sync, "_DOCS_SYNC_SPLIT_TARGET_TASK_CHARS", 80)
    markdown = "\n\n".join(
        [
            "# Chapter",
            "Intro text",
            "## Alpha",
            "Alpha body " * 20,
            "## Beta",
            "Beta body " * 20,
            "## Gamma",
            "Gamma body " * 20,
        ]
    )
    chapter = MarkdownSectionChunk(
        title="Chapter",
        anchor="ku_chapter",
        header_path="Chapter",
        body_markdown=markdown,
        heading_level=1,
    )

    child_chunks = sync._chapter_child_chunks(chapter)
    tasks, metrics = sync._build_extraction_tasks([chapter], {1: ChapterSourceContext(chapter_index=1, source_file_ids=["file-a"])})
    record = sync._section_record_for_task(tasks[0], payload=None, error="failed")

    assert len(child_chunks) == 3
    assert sync._should_split_chapter(chapter, child_chunks) is True
    assert sync._desired_child_task_count(chapter, child_chunks, extra_task_budget=2) == 3
    assert metrics["chapter_split_count"] == 1
    assert metrics["subsection_task_count"] == 3
    assert [task.task_index for task in tasks] == [1, 2, 3]
    assert sync._section_task_key(tasks[0]).startswith("ch1:subsection")
    assert sync._hashable_section_body("# Heading\n\nbody \n") == "body"
    assert len(sync._section_task_content_hash(tasks[0])) == 64
    assert record.error == "failed"
    assert record.content_hash == sync._section_task_content_hash(tasks[0])


def test_section_payload_context_uniqueness_namespace_and_combination() -> None:
    parent = _unit("ku_parent", "Parent", chapter_index=1)
    child = _unit("ku_child", "Child", chapter_index=2)
    duplicate_child = _unit("ku_child", "Child Duplicate", chapter_index=3)
    child_edge = PendingMarkdownExtractedEdge(
        source_candidate_id="child",
        target_candidate_id=None,
        source_name="Child",
        target_name="Parent",
        edge_type="application",
        description="Child applies Parent",
    )
    parent_payload = _payload(unit=parent, candidate_id="parent")
    child_payload = _payload(unit=child, candidate_id="child", pending_edges=[child_edge])
    duplicate_payload = _payload(unit=duplicate_child, candidate_id="dup")
    task = sync._ExtractionTask(
        task_index=7,
        source_chapter_index=2,
        chunk=MarkdownSectionChunk(
            title="Child",
            anchor="ku_child",
            header_path="Parent > Child",
            body_markdown="Child body",
        ),
        chapter_context=ChapterSourceContext(
            knowledge_document_id=202,
            chapter_index=2,
            source_file_ids=["file-b"],
        ),
        source_kind="subsection",
    )

    updated = sync._apply_task_context_to_payload(child_payload, task)
    unique = sync._make_payload_anchors_unique(duplicate_payload, {"ku_parent", "ku_child"})
    namespaced = sync._namespace_payload_candidate_ids(child_payload, namespace="s1")
    units, edges, diagnostics = sync._combine_section_payloads(
        markdown="",
        structured_context={
            "chapters": [{"chapter_index": 1, "title": "Parent"}, {"chapter_index": 2, "title": "Child"}],
            "document_summary_json": {
                "document_backbone": {
                    "canonical_glossary": [
                        {"term": "Parent", "target_chapters": [1]},
                        {"term": "Child", "target_chapters": [2]},
                    ],
                    "concept_dependency_graph": [
                        {"from_concept": "Parent", "to_concept": "Child", "relation": "chapter_order", "reason": "order"}
                    ],
                }
            },
        },
        chapters=[],
        sections=[
            MarkdownSectionChunk(title="Parent", anchor="ku_parent", header_path="Parent"),
            MarkdownSectionChunk(title="Child", anchor="ku_child", header_path="Parent > Child"),
        ],
        extraction_tasks=[],
        task_metrics={"planned_task_count": 2},
        section_payloads=[parent_payload, child_payload],
    )

    assert updated.units[0].knowledge_document_id == 202
    assert updated.units[0].source_file_ids == ["file-b"]
    assert unique.units[0].anchor != "ku_child"
    assert unique.candidate_id_to_anchor["dup"] == unique.units[0].anchor
    assert namespaced.candidate_id_to_anchor == {"s1:child": "ku_child"}
    assert {unit.name for unit in units} == {"Parent", "Child"}
    assert {"application", "contains", "prerequisite"} <= {edge.edge_type for edge in edges}
    assert diagnostics["successful_section_count"] == 2
    assert diagnostics["planned_task_count"] == 2


def test_prefetched_units_payload_reuses_matching_sections_and_reports_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_max_parallel_extractions", lambda: 4)
    monkeypatch.setattr(sync, "_graph_llm_concurrency_cap", lambda: 4)
    markdown = "# Chapter\n\n## Parent\nParent body\n\n## Child\nChild body"
    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, _ = sync._build_extraction_tasks(chapters, {})
    payload = _payload(unit=_unit("ku_parent", "Parent"), candidate_id="parent")
    matching = sync._section_record_for_task(tasks[0], payload=payload)
    stale = sync._section_record_for_task(tasks[0], payload=payload)
    stale.section_key = "stale"
    failed = sync._section_record_for_task(tasks[0], payload=None, error="llm failed")

    result = sync.build_prefetched_knowledge_graph_units_payload(
        markdown=markdown,
        prefetched_records=[matching, stale, failed],
    )

    assert [unit.name for unit in result.units] == ["Parent"]
    assert result.diagnostics_totals["prefetch_section_count"] == 3
    assert result.diagnostics_totals["prefetch_reused_section_count"] == 1
    assert result.diagnostics_totals["prefetch_failed_section_count"] == 1
    assert result.diagnostics_totals["prefetch_early_unit_count"] == 1


def test_async_section_record_extraction_captures_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_max_parallel_extractions", lambda: 2)
    monkeypatch.setattr(sync, "_graph_llm_concurrency_cap", lambda: 2)
    markdown = "# Chapter\n\n## Parent\nParent body\n\n## Child\nChild body"

    async def fake_extract(task_index, chapter, **kwargs):
        if "Child" in chapter.title:
            raise RuntimeError("boom")
        return _payload(
            unit=_unit(f"ku_{chapter.title.lower()}", chapter.title, chapter_index=kwargs["source_chapter_index"]),
            candidate_id="node",
        )

    monkeypatch.setattr(sync, "_extract_chapter_with_retries", fake_extract)

    records, diagnostics = asyncio.run(
        sync.extract_knowledge_graph_section_records_async(
            markdown=markdown,
            course_context="course",
            concurrency_limit=2,
        )
    )

    assert len(records) == 2
    assert [record.title for record in records] == ["Parent", "Child"]
    assert records[0].payload is not None
    assert records[1].payload is not None
    assert records[1].payload.diagnostics["failed_section_count"] == 1
    assert records[1].error == "boom"
    assert diagnostics["prefetch_section_count"] == 2
    assert diagnostics["prefetch_failed_section_count"] == 1


def test_async_graph_extraction_combines_prefetch_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_max_parallel_extractions", lambda: 4)
    monkeypatch.setattr(sync, "_graph_llm_concurrency_cap", lambda: 4)
    markdown = "# Chapter\n\n## Parent\nParent body\n\n## Child\nChild uses Parent"
    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, _ = sync._build_extraction_tasks(chapters, {})
    parent_payload = _payload(unit=_unit("ku_parent", "Parent"), candidate_id="parent")
    child_payload = _payload(
        unit=_unit("ku_child", "Child", chapter_index=2),
        candidate_id="child",
        pending_edges=[
            PendingMarkdownExtractedEdge(
                source_candidate_id="child",
                target_candidate_id=None,
                source_name="Child",
                target_name="Parent",
                edge_type="application",
                description="Child uses Parent",
            )
        ],
    )
    records = [
        sync._section_record_for_task(tasks[0], payload=parent_payload),
        sync._section_record_for_task(tasks[1], payload=child_payload),
    ]

    units, edges, diagnostics = asyncio.run(
        sync._extract_markdown_graph_items_async(
            markdown,
            course_context="course",
            prefetched_records=records,
        )
    )

    assert {unit.name for unit in units} == {"Parent", "Child"}
    assert any(edge.edge_type == "application" for edge in edges)
    assert diagnostics["prefetch_reused_section_count"] == 2
    assert diagnostics["prefetch_catchup_section_count"] == 0
    assert diagnostics["total_extracted_node_count"] == 2


def test_unit_edge_upsert_lookup_cache_and_deprecation(session: Session) -> None:
    parent_item = MarkdownKnowledgeUnit(
        anchor="ku_matrix",
        name="Matrix",
        summary="Matrix summary",
        body_markdown="Matrix body",
        knowledge_unit_type="concept",
        source_kind="docgen_heading",
        chapter_index=1,
    )
    child_item = MarkdownKnowledgeUnit(
        anchor="ku_rank",
        name="Rank",
        summary="Rank summary",
        body_markdown="Rank body",
        knowledge_unit_type="concept",
        source_kind="llm_section",
        chapter_index=2,
    )
    unit_cache = sync._build_unit_lookup_cache(session, course_id=COURSE_ID)

    parent, parent_created = sync._upsert_unit(
        session,
        course_id=COURSE_ID,
        item=parent_item,
        build_revision_no=1,
        lookup_cache=unit_cache,
    )
    child, child_created = sync._upsert_unit(
        session,
        course_id=COURSE_ID,
        item=child_item,
        build_revision_no=1,
        lookup_cache=unit_cache,
    )
    updated_parent, parent_recreated = sync._upsert_unit(
        session,
        course_id=COURSE_ID,
        item=MarkdownKnowledgeUnit(
            anchor=parent_item.anchor,
            name=parent_item.name,
            summary="Updated summary",
            body_markdown=parent_item.body_markdown,
            knowledge_unit_type=parent_item.knowledge_unit_type,
            source_kind=parent_item.source_kind,
            chapter_index=parent_item.chapter_index,
        ),
        build_revision_no=2,
        lookup_cache=unit_cache,
    )
    session.commit()

    assert parent_created is True
    assert child_created is True
    assert parent_recreated is False
    assert updated_parent.id == parent.id
    assert updated_parent.summary == "Updated summary"
    assert sync._find_unit_by_anchor(session, course_id=COURSE_ID, anchor="ku_matrix").id == parent.id
    assert sync._find_unit_by_exact_name(
        session,
        course_id=COURSE_ID,
        item=parent_item,
        knowledge_unit_type="core_knowledge",
    ).id == parent.id
    assert sync._resolve_edge_anchor(
        candidate_id="parent",
        endpoint_name="ignored",
        anchor_by_candidate_id={"parent": "ku_matrix"},
        anchors_by_name={},
        anchors_by_normalized_name={},
    ) == "ku_matrix"
    assert sync._resolve_edge_anchor(
        candidate_id=None,
        endpoint_name="Matrix",
        anchor_by_candidate_id={},
        anchors_by_name={"Matrix": ["ku_matrix"]},
        anchors_by_normalized_name={},
    ) == "ku_matrix"
    assert sync._resolve_edge_anchor(
        candidate_id=None,
        endpoint_name="Matrix",
        anchor_by_candidate_id={},
        anchors_by_name={"Matrix": ["a", "b"]},
        anchors_by_normalized_name={},
    ) is None

    edge_cache = sync._build_edge_lookup_cache(session, course_id=COURSE_ID)
    edge, edge_created = sync._upsert_edge(
        session,
        course_id=COURSE_ID,
        source_node_id=int(parent.id or 0),
        target_node_id=int(child.id or 0),
        edge_type="prerequisite",
        description="Matrix comes before Rank",
        build_revision_no=2,
        lookup_cache=edge_cache,
    )
    updated_edge, edge_recreated = sync._upsert_edge(
        session,
        course_id=COURSE_ID,
        source_node_id=int(parent.id or 0),
        target_node_id=int(child.id or 0),
        edge_type="prerequisite",
        description="Updated edge",
        build_revision_no=3,
        lookup_cache=edge_cache,
    )
    session.commit()

    assert edge_created is True
    assert edge_recreated is False
    assert updated_edge.id == edge.id
    assert updated_edge.description.endswith("Updated edge")
    assert updated_edge.confidence >= 0.95
    assert sync._build_edge_lookup_cache(session, course_id=COURSE_ID).by_key[
        (parent.id, child.id, "prerequisite")
    ].id == edge.id

    deprecated_units = sync._deprecate_removed_anchor_units(
        session,
        course_id=COURSE_ID,
        active_anchors={"ku_matrix"},
        build_revision_no=4,
    )
    deprecated_edges = sync._deprecate_removed_sync_edges(
        session,
        course_id=COURSE_ID,
        seen_edge_keys=set(),
        build_revision_no=4,
    )
    session.commit()

    assert deprecated_units == [child.id]
    assert session.get(KnowledgeUnit, child.id).status == "deprecated"
    assert deprecated_edges == [edge.id]
    assert session.get(KnowledgeEdge, edge.id).status == "deprecated"
    assert len(sync._load_aliases(sync._add_anchor_alias(parent.aliases_json, "ku_matrix"))) == 1
    assert sync._source_confidence_for_kind("llm_section") > sync._source_confidence_for_kind("structural_heading")
    assert sync._source_confidence_for_kind("unknown") == 0.75


def test_structural_and_cross_section_semantic_edges_cover_relationship_inference() -> None:
    anchors_by_name = {
        "Parent": ["ku_parent"],
        "Child": ["ku_child"],
        "Practice": ["ku_practice"],
        "Contrast": ["ku_contrast"],
    }
    anchors_by_normalized_name = {
        sync.normalize_name(name): anchors
        for name, anchors in anchors_by_name.items()
    }
    sections = [
        MarkdownSectionChunk(title="Parent", anchor="ku_parent", header_path="Parent"),
        MarkdownSectionChunk(title="Child", anchor="ku_child", header_path="Parent > Child"),
    ]
    structural_edges = sync._build_structural_heading_edges(
        sections=sections,
        anchors_by_name=anchors_by_name,
        anchors_by_normalized_name=anchors_by_normalized_name,
    )
    node_contexts = {
        "ku_parent": {"name": "Parent", "knowledge_unit_type": "core_knowledge", "section_index": 1},
        "ku_child": {
            "name": "Child",
            "knowledge_unit_type": "core_knowledge",
            "parent_entity_name": "Parent",
            "section_index": 2,
            "knowledge_document_id": 20,
            "source_file_ids": ["file-a"],
        },
        "ku_practice": {"name": "Practice", "knowledge_unit_type": "practice_assessment", "section_index": 3},
        "ku_contrast": {"name": "Contrast", "knowledge_unit_type": "core_knowledge", "section_index": 4},
    }
    section_contexts = [
        SectionExtractionContext(
            section_index=1,
            title="Parent",
            header_path="Parent",
            body_markdown="Parent body",
            primary_anchor="ku_parent",
            primary_name="Parent",
            primary_type="core_knowledge",
            knowledge_document_id=20,
            source_file_ids=["file-a"],
        ),
        SectionExtractionContext(
            section_index=3,
            title="Practice",
            header_path="Practice",
            body_markdown="利用 Parent 完成训练",
            primary_anchor="ku_practice",
            primary_name="Practice",
            primary_type="practice_assessment",
            knowledge_document_id=20,
            source_file_ids=["file-a"],
        ),
        SectionExtractionContext(
            section_index=4,
            title="Contrast",
            header_path="Contrast",
            body_markdown="对比 Parent 的不同之处",
            primary_anchor="ku_contrast",
            primary_name="Contrast",
            primary_type="core_knowledge",
            knowledge_document_id=20,
            source_file_ids=["file-a"],
        ),
    ]
    semantic_edges = sync._build_cross_section_semantic_edges(
        node_contexts_by_anchor=node_contexts,
        section_contexts=section_contexts,
        anchors_by_name=anchors_by_name,
        anchors_by_normalized_name=anchors_by_normalized_name,
    )

    assert [(edge.source_name, edge.target_name, edge.edge_type) for edge in structural_edges] == [
        ("Parent", "Child", "contains")
    ]
    assert sync._infer_relation_from_section_text(body_markdown="", primary_type="core_knowledge") is None
    assert sync._infer_relation_from_section_text(body_markdown="需要先掌握 Parent", primary_type="core_knowledge") == "prerequisite"
    assert sync._infer_relation_from_section_text(body_markdown="由 Parent 推出", primary_type="core_knowledge") == "reasoning"
    assert sync._infer_relation_from_section_text(body_markdown="类似 Parent", primary_type="core_knowledge") == "similar"
    assert {
        (edge.source_name, edge.target_name, edge.edge_type)
        for edge in semantic_edges
    } >= {
        ("Parent", "Child", "contains"),
        ("Parent", "Practice", "training"),
        ("Contrast", "Parent", "contrast"),
    }
