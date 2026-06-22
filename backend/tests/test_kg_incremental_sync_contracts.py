from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
from app.models import Course, KnowledgeEdge, KnowledgeUnit
from app.shared.infra.exceptions import KnowledgeUnitNotFoundError
import app.workflows.digest.kg_doc_sync.lib.incremental_sync as sync
import app.workflows.digest.kg_doc_sync.nodes.extract_node as extract_node_module
from app.workflows.digest.kg_doc_sync.lib.query import (
    get_focus_subgraph,
    get_full_graph,
    get_knowledge_unit_detail,
    get_knowledge_unit_relations,
    get_knowledge_units,
)
from app.workflows.digest.kg_doc_sync.lib.overview import get_knowledge_overview
from app.workflows.digest.common.markdown_knowledge_anchors import (
    MarkdownKnowledgeUnit,
    MarkdownSectionChunk,
    extract_markdown_chapter_chunks,
    extract_markdown_section_chunks,
)
from app.workflows.digest.kg_doc_sync.lib.models import (
    ChapterSourceContext,
    KnowledgeSyncExtractionPayload,
    PendingMarkdownExtractedEdge,
    SectionExtractionContext,
    SectionExtractionPayload,
)


COURSE_ID = "course_kgsync000000"


def _quality_ready_draft_context() -> dict[str, object]:
    return {
        "chapters": [
            {
                "chapter_index": 1,
                "knowledge_document_id": 10,
                "source_file_ids": ["file-a"],
            },
            {
                "chapter_index": 2,
                "knowledge_document_id": 20,
                "source_file_ids": ["file-b"],
            },
        ],
        "docgen_manifest": {
            "docgen_kg_draft": {
                "quality_ready": True,
                "fast_visible_ready": True,
                "covered_chapter_indices": [1, 2],
                "nodes": [
                    {
                        "name": "矩阵乘法",
                        "knowledge_unit_type": "concept",
                        "chapter_index": 1,
                        "summary": "按行列配对求和。",
                        "source": "kg_prefetch_llm",
                    },
                    {
                        "name": "矩阵乘法维度检查",
                        "knowledge_unit_type": "skill",
                        "chapter_index": 1,
                        "summary": "检查矩阵乘法前后的行列维度是否匹配。",
                        "source": "kg_prefetch_llm",
                    },
                    {
                        "name": "应用题训练",
                        "knowledge_unit_type": "skill",
                        "chapter_index": 2,
                        "summary": "把矩阵乘法迁移到应用题。",
                        "source": "kg_prefetch_llm",
                    },
                ],
                "edges": [
                    {
                        "source_name": "矩阵乘法维度检查",
                        "target_name": "矩阵乘法",
                        "edge_type": "assesses",
                        "chapter_index": 1,
                    },
                    {
                        "source_name": "矩阵乘法",
                        "target_name": "应用题训练",
                        "edge_type": "applies_to",
                        "chapter_index": 2,
                    },
                ],
                "quality_audit": {
                    "quality_ready": True,
                    "quality_status": "ready",
                    "warning_count": 0,
                    "missing_chapter_count": 0,
                    "edge_endpoint_issue_count": 0,
                    "edge_endpoint_ambiguity_count": 0,
                    "relation_direction_issue_count": 0,
                    "downstream_unit_count": 3,
                    "diagnostic_unit_count": 2,
                    "valid_relation_edge_count": 2,
                    "structure_edge_count": 1,
                    "examine_profile_ready": True,
                },
            }
        },
    }


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
        knowledge_unit_type="concept",
        source_kind=source_kind,
        chapter_index=chapter_index,
    )


def test_symbol_only_unit_names_get_distinct_non_empty_identity(session: Session) -> None:
    symbols = [">", "<", "==", "!="]
    normalized_names = [sync.normalize_name(symbol) for symbol in symbols]

    assert normalized_names == ["sym_3e", "sym_3c", "sym_3d_3d", "sym_21_3d"]

    for index, symbol in enumerate(symbols, start=1):
        unit, created = sync._upsert_unit(
            session,
            course_id=COURSE_ID,
            item=_unit(f"symbol-{index}", symbol),
            build_revision_no=1,
        )
        assert created is True
        assert unit.normalized_name == sync.normalize_name(symbol)

    stored_units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.course_id == COURSE_ID,
            KnowledgeUnit.knowledge_unit_type == "concept",
        )
    ).all()
    assert {unit.normalized_name for unit in stored_units} == set(normalized_names)


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
            body_markdown=f"{unit.name} belongs to Parent",
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
            "intent_enhanced": {
                "learning_goal_text": "系统复习极限",
                "content_strategy_text": "先统一符号，再训练极限计算。",
            },
            "summary_enhanced": {
                "concepts": ["Derivative"],
                "chapter_source_affinity": [{"chapter_index": 1, "file_ids": ["file-c"]}],
            },
            "chapters_enhanced": [{"chapter_index": 1, "required_elements": ["Derivative"]}],
            "dispatch_table": {"items": [{"chapter_index": 1, "source_file_ids": ["file-b"]}]},
            "chapter_task_seeds": [{"chapter_index": 1, "required_elements": ["Continuity"]}],
            "guideline": {
                "canonical_glossary": [{"term": "GuidelineLimit", "definition": "统一使用极限记号", "target_chapters": [1]}],
                "dependency_edges": [
                    {"from": "GuidelineLimit", "to": "Continuity", "relation": "chapter_order", "reason": "先理解极限"}
                ],
            },
        },
    }

    payloads = sync._docgen_chapter_payloads_by_index(structured_context)
    digest_mode, hints = sync._chapter_docgen_hints(payloads[1])
    contexts = sync._chapter_context_lookup(structured_context)
    backbone = sync._document_backbone_payload(structured_context)

    assert digest_mode == "sprint"
    assert any("Limit" in hint and "Derivative" in hint and "Continuity" in hint for hint in hints)
    assert any("统一符号" in hint for hint in hints)
    assert contexts[1].knowledge_document_id == 101
    assert contexts[1].source_file_ids == ["file-a", "file-b", "file-c"]
    assert sync._chapter_context_for_index(contexts, 99).chapter_index == 99
    assert backbone["canonical_glossary"][0]["term"] == "GuidelineLimit"
    assert backbone["concept_dependency_graph"][0]["from"] == "GuidelineLimit"


def test_guideline_backbone_does_not_create_rule_seed_units_and_edges() -> None:
    structured_context = {
        "docgen_manifest": {
            "guideline": {
                "canonical_glossary": [
                    {
                        "term": "动量",
                        "definition": "物体运动状态的量化描述。",
                        "target_chapters": [1],
                        "knowledge_unit_type": "principle",
                    },
                    {
                        "term": "冲量",
                        "definition": "力对时间的累积效果。",
                        "target_chapters": [1],
                        "knowledge_unit_type": "concept",
                    },
                ],
                "dependency_edges": [
                    {"from": "动量", "to": "冲量", "relation": "prerequisite_for", "reason": "先理解运动状态再理解改变。"}
                ],
            }
        }
    }

    units, edges = sync._build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts={1: ChapterSourceContext(knowledge_document_id=88, chapter_index=1, source_file_ids=["file-x"])},
        existing_normalized_names=set(),
    )

    assert units == []
    assert edges == []


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
        edge_type="part_of",
        description="Child belongs to Parent",
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
    assert {edge.edge_type for edge in edges} == {"part_of"}
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


def test_prefetched_units_payload_does_not_use_docgen_seed_when_prefetch_empty() -> None:
    markdown = "# 矩阵基础\n\n## 矩阵乘法\n正文"
    result = sync.build_prefetched_knowledge_graph_units_payload(
        markdown=markdown,
        structured_context={
            "chapters": [
                {
                    "chapter_index": 1,
                    "knowledge_document_id": 10,
                    "source_file_ids": ["file-a"],
                }
            ],
            "docgen_manifest": {
                "preliminary_kg": {
                    "nodes": [
                        {
                            "name": "矩阵乘法",
                            "knowledge_unit_type": "concept",
                            "chapter_index": 1,
                            "summary": "按行列配对求和。",
                        }
                    ]
                }
            },
        },
        prefetched_records=[],
    )

    assert result.units == []
    assert result.extracted_edges == []
    assert result.diagnostics_totals["docgen_seed_unit_count"] == 0
    assert result.diagnostics_totals["early_unit_count"] == 0


def test_prefetched_units_payload_persists_resolved_edges_early(session: Session) -> None:
    markdown = "# Chapter\n\n## Parent\nParent body\n\n## Child\nChild body"
    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, _ = sync._build_extraction_tasks(chapters, {})
    parent = _unit("ku_parent", "Parent")
    child = _unit("ku_child", "Child")
    payload = SectionExtractionPayload(
        units=[parent, child],
        pending_edges=[
            PendingMarkdownExtractedEdge(
                source_candidate_id="parent",
                target_candidate_id="child",
                source_name="Parent",
                target_name="Child",
                edge_type="prerequisite_for",
                description="Parent is learned before Child.",
                source_kind="kg_prefetch_llm",
            )
        ],
        candidate_id_to_anchor={"parent": parent.anchor, "child": child.anchor},
        anchors_by_name={"Parent": [parent.anchor], "Child": [child.anchor]},
        anchors_by_normalized_name={
            sync.normalize_name("Parent"): [parent.anchor],
            sync.normalize_name("Child"): [child.anchor],
        },
        node_contexts_by_anchor={},
        section_context=SectionExtractionContext(
            section_index=1,
            title="Chapter",
            header_path="Chapter",
            body_markdown="Parent before Child",
            primary_anchor=parent.anchor,
            primary_name=parent.name,
            primary_type=parent.knowledge_unit_type,
        ),
        diagnostics={
            "successful_section_count": 1,
            "llm_section_count": 1,
            "total_extracted_node_count": 2,
            "total_extracted_edge_count": 1,
        },
    )
    record = sync._section_record_for_task(tasks[0], payload=payload)

    result = sync.build_prefetched_knowledge_graph_units_payload(
        markdown=markdown,
        prefetched_records=[record],
    )

    assert [unit.name for unit in result.units] == ["Parent", "Child"]
    assert [(edge.source_anchor, edge.target_anchor, edge.edge_type) for edge in result.extracted_edges] == [
        ("ku_parent", "ku_child", "prerequisite_for")
    ]
    assert result.diagnostics_totals["prefetch_early_edge_count"] == 1
    assert result.diagnostics_totals["early_edge_count"] == 1

    sync_run = sync.create_sync_run(
        session,
        course_id=COURSE_ID,
        build_session_id="build_seed_edges",
        doc_version_no=1,
        graph_revision_no=1,
    )
    assert sync_run.id is not None
    metrics = sync.persist_knowledge_graph_units_early(
        session,
        run_context=sync.KnowledgeSyncRunContext(
            course_id=COURSE_ID,
            build_revision_no=1,
            sync_run_id=sync_run.id,
            doc_version_no=1,
        ),
        payload=result,
    )

    assert metrics["unit_count"] == 2
    assert metrics["edge_count"] == 1
    assert metrics["created_edge_count"] == 1
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.course_id == COURSE_ID)).all()
    assert len(edges) == 1
    assert edges[0].edge_type == "prerequisite_for"


def test_docgen_kg_draft_graph_persists_before_publish_when_quality_ready(session: Session) -> None:
    metrics = sync.persist_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        docgen_kg_draft={
            "quality_ready": True,
            "fast_visible_ready": True,
            "nodes": [
                {
                    "name": "矩阵乘法",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "按行列配对求和。",
                    "source": "docgen_review_refinement",
                },
                {
                    "name": "矩阵乘法维度检查",
                    "knowledge_unit_type": "skill",
                    "chapter_index": 1,
                    "summary": "检查矩阵乘法前后的行列维度是否匹配。",
                    "source": "kg_prefetch_llm",
                },
            ],
            "edges": [{"source_name": "矩阵乘法维度检查", "target_name": "矩阵乘法", "edge_type": "assesses"}],
            "quality_status": "ready",
            "quality_audit": {
                "quality_ready": True,
                "quality_status": "ready",
                "warning_count": 0,
                "missing_chapter_count": 0,
                "edge_endpoint_issue_count": 0,
                "edge_endpoint_ambiguity_count": 0,
                "relation_direction_issue_count": 0,
                "downstream_unit_count": 2,
                "diagnostic_unit_count": 1,
                "valid_relation_edge_count": 1,
                "structure_edge_count": 1,
                "examine_profile_ready": True,
            },
        },
    )

    units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.course_id == COURSE_ID,
            KnowledgeUnit.status == "active",
        )
    ).all()
    edges = session.exec(
        select(KnowledgeEdge).where(
            KnowledgeEdge.course_id == COURSE_ID,
            KnowledgeEdge.status == "active",
        )
    ).all()

    assert metrics["skipped"] is False
    assert metrics["unit_count"] == 2
    assert metrics["edge_count"] == 1
    assert metrics["skipped_edge_count"] == 0
    assert {unit.canonical_name for unit in units} == {"矩阵乘法", "矩阵乘法维度检查"}
    assert {unit.knowledge_unit_type for unit in units} == {"concept", "skill"}
    assert len(edges) == 1


def test_docgen_kg_draft_graph_persists_fast_visible_quality_catchup(session: Session) -> None:
    metrics = sync.persist_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        require_quality_ready=False,
        docgen_kg_draft={
            "quality_ready": False,
            "fast_visible_ready": True,
            "nodes": [
                {
                    "name": "指针模型",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "变量、地址、指针、解引用的关系。",
                    "source": "docgen_review_refinement",
                },
                {
                    "name": "指针自检",
                    "knowledge_unit_type": "skill",
                    "chapter_index": 1,
                    "summary": "用输出判断题检查指针掌握情况。",
                    "source": "docgen_reviewed_heading",
                },
            ],
            "edges": [{"source_name": "指针自检", "target_name": "指针模型", "edge_type": "assesses"}],
            "quality_status": "needs_catchup",
            "quality_audit": {
                "quality_ready": False,
                "quality_status": "needs_catchup",
                "warning_count": 1,
                "warnings": ["review_repair_warning"],
                "missing_chapter_count": 0,
                "edge_endpoint_issue_count": 0,
                "edge_endpoint_ambiguity_count": 0,
                "relation_direction_issue_count": 0,
                "downstream_unit_count": 2,
                "diagnostic_unit_count": 1,
                "valid_relation_edge_count": 1,
                "structure_edge_count": 1,
                "examine_profile_ready": True,
            },
        },
    )

    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.course_id == COURSE_ID)).all()
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.course_id == COURSE_ID)).all()

    assert metrics["skipped"] is False
    assert metrics["docgen_draft_quality_ready"] == 0
    assert metrics["unit_count"] == 2
    assert metrics["edge_count"] == 1
    assert {unit.canonical_name for unit in units} == {"指针模型", "指针自检"}
    assert len(edges) == 1
    assert edges[0].edge_type == "assesses"


def test_unit_upsert_prefers_existing_name_over_stale_anchor(session: Session) -> None:
    stale = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="自变量与因变量",
        normalized_name=sync.normalize_name("自变量与因变量"),
        summary="旧节点。",
        body_markdown="旧节点。",
        status="active",
        aliases_json='[{"normalized_alias":"ku-stale","source":"markdown_anchor"}]',
    )
    target = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="自变量",
        normalized_name=sync.normalize_name("自变量"),
        summary="已有节点。",
        body_markdown="已有节点。",
        status="deprecated",
    )
    session.add_all([stale, target])
    session.commit()
    session.refresh(stale)
    session.refresh(target)

    unit, created = sync._upsert_unit(  # noqa: SLF001
        session,
        course_id=COURSE_ID,
        item=MarkdownKnowledgeUnit(
            anchor="ku-stale",
            name="自变量",
            knowledge_unit_type="concept",
            summary="函数输入量。",
            body_markdown="函数输入量。",
            source_kind="kg_prefetch_llm",
        ),
        build_revision_no=5,
        lookup_cache=sync._build_unit_lookup_cache(session, course_id=COURSE_ID),  # noqa: SLF001
    )

    assert created is False
    assert unit.id == target.id
    assert unit.status == "active"
    assert '"normalized_alias": "ku-stale"' in unit.aliases_json
    assert session.get(KnowledgeUnit, stale.id).canonical_name == "自变量与因变量"


def test_deprecate_removed_units_keeps_same_identity_when_anchor_changes(session: Session) -> None:
    kept = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="procedure",
        canonical_name="函数值求解方法",
        normalized_name=sync.normalize_name("函数值求解方法"),
        summary="旧 anchor 但本轮同名同类型仍存在。",
        body_markdown="旧 anchor 但本轮同名同类型仍存在。",
        status="active",
        aliases_json='[{"normalized_alias":"ku_old_method","source":"markdown_anchor"}]',
    )
    stale = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="procedure",
        canonical_name="错题回看方法",
        normalized_name=sync.normalize_name("错题回看方法"),
        summary="本轮不再出现的旧节点。",
        body_markdown="本轮不再出现的旧节点。",
        status="active",
        aliases_json='[{"normalized_alias":"ku_old_review","source":"markdown_anchor"}]',
    )
    session.add_all([kept, stale])
    session.commit()
    session.refresh(kept)
    session.refresh(stale)

    deprecated_units = sync._deprecate_removed_anchor_units(  # noqa: SLF001
        session,
        course_id=COURSE_ID,
        active_anchors={"ku_new_method"},
        active_identity_keys={("procedure", sync.normalize_name("函数值求解方法"))},
        build_revision_no=9,
    )
    session.commit()

    assert deprecated_units == [stale.id]
    assert session.get(KnowledgeUnit, kept.id).status == "active"
    assert session.get(KnowledgeUnit, stale.id).status == "deprecated"


def test_deprecate_removed_units_prefers_current_run_unit_ids(session: Session) -> None:
    old_same_identity = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="procedure",
        canonical_name="简单概率判断步骤",
        normalized_name=sync.normalize_name("简单概率判断步骤"),
        summary="上一轮的同名节点。",
        body_markdown="上一轮的同名节点。",
        status="active",
        aliases_json='[{"normalized_alias":"ku_old_probability","source":"markdown_anchor"}]',
    )
    current = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="topic",
        canonical_name="统计与概率",
        normalized_name=sync.normalize_name("统计与概率"),
        summary="本轮触达节点。",
        body_markdown="本轮触达节点。",
        status="active",
        aliases_json='[{"normalized_alias":"ku_current_topic","source":"markdown_anchor"}]',
    )
    session.add_all([old_same_identity, current])
    session.commit()
    session.refresh(old_same_identity)
    session.refresh(current)

    deprecated_units = sync._deprecate_removed_anchor_units(  # noqa: SLF001
        session,
        course_id=COURSE_ID,
        active_anchors={"ku_current_topic", "ku_old_probability"},
        active_unit_ids={int(current.id or 0)},
        active_identity_keys={("procedure", sync.normalize_name("简单概率判断步骤"))},
        build_revision_no=10,
    )
    session.commit()

    assert deprecated_units == [old_same_identity.id]
    assert session.get(KnowledgeUnit, old_same_identity.id).status == "deprecated"
    assert session.get(KnowledgeUnit, current.id).status == "active"


def test_docgen_kg_draft_graph_is_query_visible_before_publish(session: Session) -> None:
    draft = _quality_ready_draft_context()["docgen_manifest"]["docgen_kg_draft"]  # type: ignore[index]

    metrics = sync.persist_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        docgen_kg_draft=draft,  # type: ignore[arg-type]
    )

    graph = get_full_graph(session, course_id=COURSE_ID)
    page = get_knowledge_units(session, course_id=COURSE_ID, page=1, size=10)

    assert metrics["skipped"] is False
    assert metrics["unit_count"] == 3
    assert metrics["edge_count"] == 2
    assert metrics["skipped_edge_count"] == 0
    assert {node.canonical_name for node in graph.nodes} == {"矩阵乘法", "矩阵乘法维度检查", "应用题训练"}
    node_id_by_name = {node.canonical_name: node.id for node in graph.nodes}
    assert {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in graph.edges} == {
        (node_id_by_name["矩阵乘法维度检查"], node_id_by_name["矩阵乘法"], "assesses"),
        (node_id_by_name["矩阵乘法"], node_id_by_name["应用题训练"], "applies_to"),
    }
    assert page.total == 3
    assert [item.status for item in page.items] == ["active", "active", "active"]


def test_graph_queries_hide_legacy_resource_units_and_edges(session: Session) -> None:
    concept = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="指针变量",
        normalized_name=sync.normalize_name("指针变量"),
        summary="指针变量保存地址。",
        body_markdown="指针变量保存地址。",
        status="active",
    )
    skill = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="skill",
        canonical_name="指针练习",
        normalized_name=sync.normalize_name("指针练习"),
        summary="通过题目检查指针变量。",
        body_markdown="通过题目检查指针变量。",
        status="active",
    )
    resource = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="resource",
        canonical_name="教材页码说明",
        normalized_name=sync.normalize_name("教材页码说明"),
        summary="来源材料说明，不应进入主图谱。",
        body_markdown="来源材料说明，不应进入主图谱。",
        status="active",
    )
    legacy_resource = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="explanation_support",
        canonical_name="课件原文",
        normalized_name=sync.normalize_name("课件原文"),
        summary="旧类型来源材料说明，不应进入主图谱。",
        body_markdown="旧类型来源材料说明，不应进入主图谱。",
        status="active",
    )
    session.add_all([concept, skill, resource, legacy_resource])
    session.commit()
    session.refresh(concept)
    session.refresh(skill)
    session.refresh(resource)
    session.refresh(legacy_resource)

    assert concept.id is not None
    assert skill.id is not None
    assert resource.id is not None
    assert legacy_resource.id is not None
    session.add_all(
        [
            KnowledgeEdge(
                course_id=COURSE_ID,
                source_node_id=concept.id,
                target_node_id=skill.id,
                edge_type="applies_to",
                status="active",
            ),
            KnowledgeEdge(
                course_id=COURSE_ID,
                source_node_id=resource.id,
                target_node_id=concept.id,
                edge_type="explains",
                status="active",
            ),
            KnowledgeEdge(
                course_id=COURSE_ID,
                source_node_id=concept.id,
                target_node_id=resource.id,
                edge_type="explains",
                status="active",
            ),
            KnowledgeEdge(
                course_id=COURSE_ID,
                source_node_id=legacy_resource.id,
                target_node_id=concept.id,
                edge_type="explains",
                status="active",
            ),
        ]
    )
    session.commit()

    graph = get_full_graph(session, course_id=COURSE_ID)
    subgraph = get_focus_subgraph(session, course_id=COURSE_ID, center_knowledge_unit_id=concept.id, hops=1)
    page = get_knowledge_units(session, course_id=COURSE_ID, page=1, size=10)
    resource_page = get_knowledge_units(session, course_id=COURSE_ID, knowledge_unit_type="resource", page=1, size=10)
    legacy_resource_page = get_knowledge_units(
        session,
        course_id=COURSE_ID,
        knowledge_unit_type="explanation_support",
        page=1,
        size=10,
    )
    detail = get_knowledge_unit_detail(session, course_id=COURSE_ID, knowledge_unit_id=concept.id)
    relations = get_knowledge_unit_relations(session, course_id=COURSE_ID, knowledge_unit_id=concept.id)
    overview = get_knowledge_overview(session, course_id=COURSE_ID, include=["stats"], full=False)

    assert {node.canonical_name for node in graph.nodes} == {"指针变量", "指针练习"}
    assert {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in graph.edges} == {
        (concept.id, skill.id, "applies_to")
    }
    assert {node.canonical_name for node in subgraph.nodes} == {"指针变量", "指针练习"}
    assert {(edge.source_node_id, edge.target_node_id, edge.edge_type) for edge in subgraph.edges} == {
        (concept.id, skill.id, "applies_to")
    }
    assert page.total == 2
    assert {node.canonical_name for node in page.items} == {"指针变量", "指针练习"}
    assert resource_page.total == 0
    assert resource_page.items == []
    assert legacy_resource_page.total == 0
    assert legacy_resource_page.items == []
    assert overview.stats.node_count == 2
    assert overview.stats.edge_count == 1
    assert [(edge.other_node_name, edge.edge_type) for edge in detail.incident_edges] == [("指针练习", "applies_to")]
    assert {(edge.source_node_name, edge.target_node_name, edge.edge_type) for edge in relations} == {
        ("指针变量", "指针练习", "applies_to")
    }
    with pytest.raises(KnowledgeUnitNotFoundError):
        get_knowledge_unit_detail(session, course_id=COURSE_ID, knowledge_unit_id=resource.id)
    with pytest.raises(KnowledgeUnitNotFoundError):
        get_knowledge_unit_relations(session, course_id=COURSE_ID, knowledge_unit_id=resource.id)
    with pytest.raises(KnowledgeUnitNotFoundError):
        get_knowledge_unit_detail(session, course_id=COURSE_ID, knowledge_unit_id=legacy_resource.id)
    with pytest.raises(KnowledgeUnitNotFoundError):
        get_knowledge_unit_relations(session, course_id=COURSE_ID, knowledge_unit_id=legacy_resource.id)


def test_focus_subgraph_without_center_prefers_high_degree_backbone_late_nodes(session: Session) -> None:
    low_value_units = [
        KnowledgeUnit(
            course_id=COURSE_ID,
            knowledge_unit_type="concept",
            canonical_name=f"低连接节点 {index}",
            normalized_name=sync.normalize_name(f"低连接节点 {index}"),
            summary="低连接节点",
            body_markdown="低连接节点",
            status="active",
        )
        for index in range(18)
    ]
    session.add_all(low_value_units)
    session.commit()

    hub = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="principle",
        canonical_name="核心主干节点",
        normalized_name=sync.normalize_name("核心主干节点"),
        summary="高连接主干",
        body_markdown="高连接主干",
        status="active",
    )
    spokes = [
        KnowledgeUnit(
            course_id=COURSE_ID,
            knowledge_unit_type="concept",
            canonical_name=f"关键相邻节点 {index}",
            normalized_name=sync.normalize_name(f"关键相邻节点 {index}"),
            summary="关键相邻节点",
            body_markdown="关键相邻节点",
            status="active",
        )
        for index in range(6)
    ]
    session.add(hub)
    session.add_all(spokes)
    session.commit()
    session.refresh(hub)
    for spoke in spokes:
        session.refresh(spoke)

    assert hub.id is not None
    session.add_all(
        [
            KnowledgeEdge(
                course_id=COURSE_ID,
                source_node_id=hub.id,
                target_node_id=spoke.id,
                edge_type="prerequisite_for",
                status="active",
            )
            for spoke in spokes
            if spoke.id is not None
        ]
    )
    session.commit()

    subgraph = get_focus_subgraph(session, course_id=COURSE_ID, limit=4)

    names = {node.canonical_name for node in subgraph.nodes}
    assert "核心主干节点" in names
    assert any(name.startswith("关键相邻节点") for name in names)
    assert not names <= {unit.canonical_name for unit in low_value_units[:4]}


def test_docgen_kg_draft_graph_rolls_back_when_publish_fails(session: Session) -> None:
    existing = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="矩阵乘法",
        normalized_name=sync.normalize_name("矩阵乘法"),
        summary="旧摘要",
        body="旧正文",
        body_markdown="旧正文",
        status="active",
        build_revision_no=3,
    )
    session.add(existing)
    session.commit()
    session.refresh(existing)

    metrics = sync.persist_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        build_revision_no=4,
        docgen_kg_draft={
            "quality_ready": True,
            "fast_visible_ready": True,
            "nodes": [
                {
                    "name": "矩阵乘法",
                    "knowledge_unit_type": "concept",
                    "chapter_index": 1,
                    "summary": "新草稿摘要",
                    "source": "docgen_review_refinement",
                },
                {
                    "name": "矩阵乘法维度检查",
                    "knowledge_unit_type": "skill",
                    "chapter_index": 1,
                    "summary": "检查矩阵乘法前后的行列维度是否匹配。",
                    "source": "kg_prefetch_llm",
                },
            ],
            "edges": [{"source_name": "矩阵乘法维度检查", "target_name": "矩阵乘法", "edge_type": "assesses"}],
            "quality_audit": {
                "quality_ready": True,
                "quality_status": "ready",
                "warning_count": 0,
                "missing_chapter_count": 0,
                "edge_endpoint_issue_count": 0,
                "edge_endpoint_ambiguity_count": 0,
                "relation_direction_issue_count": 0,
                "downstream_unit_count": 2,
                "diagnostic_unit_count": 1,
                "valid_relation_edge_count": 1,
                "structure_edge_count": 1,
                "examine_profile_ready": True,
            },
        },
    )
    session.commit()

    assert metrics["created_unit_count"] == 1
    assert metrics["updated_unit_count"] == 1
    assert metrics["created_edge_count"] == 1
    assert metrics["skipped_edge_count"] == 0
    assert session.get(KnowledgeUnit, existing.id).summary == "新草稿摘要"
    assert get_knowledge_units(session, course_id=COURSE_ID, page=1, size=10).total == 2

    rollback_metrics = sync.rollback_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        early_persist_metrics=metrics,
        reason="publish_failed",
    )
    session.commit()

    restored = session.get(KnowledgeUnit, existing.id)
    graph = get_full_graph(session, course_id=COURSE_ID)

    assert rollback_metrics["deleted_unit_count"] == 1
    assert rollback_metrics["restored_unit_count"] == 1
    assert rollback_metrics["deleted_edge_count"] == 1
    assert restored.summary == "旧摘要"
    assert restored.body_markdown == "旧正文"
    assert restored.build_revision_no == 3
    assert {node.canonical_name for node in graph.nodes} == {"矩阵乘法"}
    assert graph.edges == []


def test_docgen_kg_draft_graph_skips_before_publish_when_quality_not_ready(session: Session) -> None:
    metrics = sync.persist_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        docgen_kg_draft={
            "quality_ready": False,
            "nodes": [
                {
                    "name": "孤立节点",
                    "knowledge_unit_type": "concept",
                    "summary": "没有通过质量门。",
                }
            ],
            "quality_audit": {"warning_count": 1},
        },
    )

    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.course_id == COURSE_ID)).all()

    assert metrics["skipped"] is True
    assert metrics["skip_reason"] == "docgen_kg_draft_quality_not_ready"
    assert units == []


def test_docgen_kg_draft_graph_skips_before_publish_without_quality_audit(session: Session) -> None:
    metrics = sync.persist_docgen_kg_draft_graph_early(
        session,
        course_id=COURSE_ID,
        docgen_kg_draft={
            "quality_ready": True,
            "fast_visible_ready": True,
            "nodes": [
                {
                    "name": "看似可用节点",
                    "knowledge_unit_type": "concept",
                    "summary": "缺少质量审计时不能提前发布。",
                }
            ],
        },
    )

    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.course_id == COURSE_ID)).all()

    assert metrics["skipped"] is True
    assert metrics["skip_reason"] == "docgen_kg_draft_quality_not_ready"
    assert metrics["docgen_draft_quality_audit_present"] == 0
    assert units == []


def test_docgen_kg_draft_final_payload_uses_published_context_without_llm() -> None:
    payload = sync.build_docgen_kg_draft_final_payload(
        markdown="# 矩阵基础\n\n正文\n\n# 应用训练\n\n正文",
        structured_context=_quality_ready_draft_context(),
    )

    assert payload is not None
    assert [unit.name for unit in payload.units] == ["矩阵乘法", "矩阵乘法维度检查", "应用题训练"]
    assert payload.units[0].knowledge_document_id == 10
    assert payload.units[2].knowledge_document_id == 20
    assert payload.units[2].source_file_ids == ["file-b"]
    assert [(edge.edge_type, edge.knowledge_document_id) for edge in payload.extracted_edges] == [
        ("assesses", 10),
        ("applies_to", 20),
    ]
    assert payload.diagnostics_totals["docgen_draft_fast_finalize"] == 1
    assert payload.diagnostics_totals["docgen_draft_final_unit_count"] == 3
    assert payload.diagnostics_totals["docgen_draft_final_edge_count"] == 2
    assert payload.diagnostics_totals["docgen_draft_final_skipped_endpoint_count"] == 0
    assert payload.diagnostics_totals["llm_section_count"] == 0


def test_docgen_kg_draft_final_payload_requires_full_chapter_coverage() -> None:
    context = _quality_ready_draft_context()
    draft = context["docgen_manifest"]["docgen_kg_draft"]  # type: ignore[index]
    draft["covered_chapter_indices"] = [1]  # type: ignore[index]

    payload = sync.build_docgen_kg_draft_final_payload(
        markdown="# 矩阵基础\n\n正文\n\n# 应用训练\n\n正文",
        structured_context=context,
    )

    assert payload is None


def test_docgen_kg_draft_final_payload_rejects_stale_quality_flag_without_audit() -> None:
    context = _quality_ready_draft_context()
    draft = context["docgen_manifest"]["docgen_kg_draft"]  # type: ignore[index]
    draft.pop("quality_audit", None)  # type: ignore[attr-defined]

    payload = sync.build_docgen_kg_draft_final_payload(
        markdown="# 矩阵基础\n\n正文\n\n# 应用训练\n\n正文",
        structured_context=context,
    )

    assert payload is None


def test_extract_node_uses_quality_ready_docgen_draft_without_section_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_extract(*args, **kwargs):
        raise AssertionError("section LLM extraction should not run for quality-ready DocGen KG draft")

    monkeypatch.setattr(extract_node_module, "extract_knowledge_graph_items_async", fail_extract)

    state = {
        "course_id": COURSE_ID,
        "markdown": "# 矩阵基础\n\n正文\n\n# 应用训练\n\n正文",
        "structured_context": _quality_ready_draft_context(),
        "sync_run_context": sync.KnowledgeSyncRunContext(
            course_id=COURSE_ID,
            build_revision_no=7,
            sync_run_id=99,
            doc_version_no=7,
            structured_context=_quality_ready_draft_context(),
        ),
        "node_metrics": {},
    }

    result = asyncio.run(extract_node_module.extract_node(state))

    assert result["error"] is None
    assert result["extraction_payload"] is not None
    assert result["node_metrics"]["extract"]["course_context_source"] == "docgen_kg_draft"
    assert result["node_metrics"]["extract"]["docgen_draft_fast_finalize"] == 1
    assert result["node_metrics"]["extract"]["llm_section_count"] == 0


def test_async_section_record_extraction_recovers_failed_llm_with_rule_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert records[1].payload.diagnostics["successful_section_count"] == 1
    assert records[1].payload.diagnostics["failed_section_count"] == 0
    assert records[1].payload.diagnostics["llm_error_count"] == 1
    assert records[1].payload.diagnostics["rule_fallback_attempt_count"] == 1
    assert records[1].payload.diagnostics["rule_fallback_success_count"] == 1
    assert records[1].error == ""
    assert records[1].payload.units[0].source_kind == "rule_fallback_chapter"
    assert diagnostics["prefetch_section_count"] == 2
    assert diagnostics["prefetch_failed_section_count"] == 0
    assert diagnostics["rule_fallback_success_count"] == 1


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
                edge_type="part_of",
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
    assert any(edge.edge_type == "part_of" for edge in edges)
    assert diagnostics["prefetch_reused_section_count"] == 2
    assert diagnostics["prefetch_catchup_section_count"] == 0
    assert diagnostics["total_extracted_node_count"] == 2


def test_rule_fallback_sync_skips_deprecation_of_existing_units(session: Session) -> None:
    stale_item = MarkdownKnowledgeUnit(
        anchor="ku_old_detail",
        name="Old Detail",
        summary="Existing detailed node",
        body_markdown="Old detailed body",
        knowledge_unit_type="concept",
        source_kind="llm_section",
        chapter_index=1,
    )
    stale, _created = sync._upsert_unit(
        session,
        course_id=COURSE_ID,
        item=stale_item,
        build_revision_no=1,
        lookup_cache=sync._build_unit_lookup_cache(session, course_id=COURSE_ID),
    )
    session.commit()

    run_context = sync.initialize_knowledge_graph_sync_run(
        session,
        course_id=COURSE_ID,
        markdown="# Current\n\nCurrent body",
        build_revision_no=2,
        structured_context={"doc_version_no": 2},
    )
    payload = KnowledgeSyncExtractionPayload(
        units=[
            MarkdownKnowledgeUnit(
                anchor="ku_current",
                name="Current",
                summary="Recovered by rule fallback",
                body_markdown="# Current\n\nCurrent body",
                knowledge_unit_type="concept",
                source_kind="rule_fallback_chapter",
                chapter_index=1,
            )
        ],
        extracted_edges=[],
        diagnostics_totals={
            "chapter_count": 1,
            "section_count": 1,
            "successful_section_count": 1,
            "failed_section_count": 0,
            "llm_section_count": 1,
            "llm_error_count": 1,
            "rule_fallback_attempt_count": 1,
            "rule_fallback_success_count": 1,
            "total_extracted_node_count": 1,
            "total_extracted_edge_count": 0,
        },
    )

    report = sync.persist_knowledge_graph_items(session, run_context=run_context, payload=payload)

    assert report.rule_fallback_success_count == 1
    assert report.deprecated_unit_ids == []
    assert session.get(KnowledgeUnit, stale.id).status != "deprecated"


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
        knowledge_unit_type="concept",
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
        edge_type="prerequisite_for",
        description="Matrix comes before Rank",
        build_revision_no=2,
        lookup_cache=edge_cache,
    )
    updated_edge, edge_recreated = sync._upsert_edge(
        session,
        course_id=COURSE_ID,
        source_node_id=int(parent.id or 0),
        target_node_id=int(child.id or 0),
        edge_type="prerequisite_for",
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
        (parent.id, child.id, "prerequisite_for")
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
        "ku_parent": {"name": "Parent", "knowledge_unit_type": "concept", "section_index": 1},
        "ku_child": {
            "name": "Child",
            "knowledge_unit_type": "concept",
            "parent_entity_name": "Parent",
            "section_index": 2,
            "knowledge_document_id": 20,
            "source_file_ids": ["file-a"],
        },
        "ku_practice": {"name": "Practice", "knowledge_unit_type": "skill", "section_index": 3},
        "ku_contrast": {"name": "Contrast", "knowledge_unit_type": "concept", "section_index": 4},
    }
    section_contexts = [
        SectionExtractionContext(
            section_index=1,
            title="Parent",
            header_path="Parent",
            body_markdown="Parent body",
            primary_anchor="ku_parent",
            primary_name="Parent",
            primary_type="concept",
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
            primary_type="skill",
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
            primary_type="concept",
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
        ("Child", "Parent", "part_of")
    ]
    assert sync._infer_relation_from_section_text(body_markdown="", primary_type="concept") is None
    assert sync._infer_relation_from_section_text(body_markdown="需要先掌握 Parent", primary_type="concept") == "prerequisite_for"
    assert sync._infer_relation_from_section_text(body_markdown="由 Parent 推出", primary_type="concept") == "derives_to"
    assert sync._infer_relation_from_section_text(body_markdown="类似 Parent", primary_type="concept") == "similar_to"
    assert {
        (edge.source_name, edge.target_name, edge.edge_type)
        for edge in semantic_edges
    } >= {
        ("Child", "Parent", "part_of"),
        ("Practice", "Parent", "assesses"),
        ("Contrast", "Parent", "confuses_with"),
    }
