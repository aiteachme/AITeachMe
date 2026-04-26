import json

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_graph_sync import KnowledgeGraphSourceRef, KnowledgeGraphSyncRun
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.digest.kg_doc_sync.lib.candidate_quality import is_low_quality_docs_unit_name
from app.workflows.digest.kg_doc_sync.lib.extraction import CandidateNode, ChunkExtractionResult
import app.workflows.digest.kg_doc_sync.lib.incremental_sync as incremental_sync
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import sync_markdown_knowledge_graph
from app.workflows.digest.kg_doc_sync.lib.query import get_knowledge_unit_detail


async def _empty_search_knowledge(*args, **kwargs):
    return []


def _docgen_context(*, doc_version_no: int = 3) -> dict[str, object]:
    return {
        "doc_version_no": doc_version_no,
        "chapters": [
            {
                "knowledge_document_id": 11,
                "chapter_index": 1,
                "title": "Derivative",
                "summary": "Derivative basics.",
                "source_file_ids": [7],
            }
        ],
        "docgen_manifest": {
            "document_backbone_snapshot": {
                "canonical_glossary": [
                    {
                        "term": "Gradient",
                        "definition": "Gradient is the local slope direction.",
                        "target_chapters": [1],
                    }
                ],
                "concept_dependency_graph": [
                    {
                        "from_concept": "Derivative",
                        "to_concept": "Gradient",
                        "relation": "chapter_order",
                        "reason": "Derivative is learned before gradient.",
                    }
                ],
            }
        },
    }


def test_docs_sync_rejects_outline_titles_and_speedrun_wrappers():
    assert is_low_quality_docs_unit_name(
        "一、 一元一次方程建模路径与速判技巧",
        node_type="example",
    )
    assert is_low_quality_docs_unit_name("速判技巧", node_type="method")
    assert is_low_quality_docs_unit_name("找已知边角关系", node_type="method")
    assert is_low_quality_docs_unit_name(
        "力学、热学、光学、电学与磁学的主干划分",
        node_type="concept",
    )
    assert is_low_quality_docs_unit_name(
        "各模块在考试中的权重与认知难度排序",
        node_type="concept",
    )
    assert is_low_quality_docs_unit_name(
        "实验设计与现象解释的对应关系",
        node_type="concept",
    )
    assert is_low_quality_docs_unit_name(
        "从现象观察到原理的完整推导链条",
        node_type="concept",
    )
    assert not is_low_quality_docs_unit_name("重力", node_type="concept")
    assert not is_low_quality_docs_unit_name("权重", node_type="concept")
    assert not is_low_quality_docs_unit_name("优先级队列", node_type="concept")
    assert not is_low_quality_docs_unit_name("W = F s cosθ", node_type="formula")


def test_docs_sync_uses_docgen_backbone_and_source_refs(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="Derivative",
                    knowledge_unit_type="concept",
                    local_summary="Derivative is the rate of change.",
                    taxonomy_hint="Derivative",
                )
            ],
            edges=[],
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = "# Derivative\n\nDerivative describes change rate.\n"

    with Session(engine) as session:
        session.add(
            KnowledgeDocument(
                id=11,
                subject="math",
                chapter_index=1,
                title="Derivative",
                summary="Derivative basics.",
                source_file_ids="[7]",
                version_no=3,
            )
        )
        session.commit()

        report = sync_markdown_knowledge_graph(
            session,
            subject="math",
            markdown=markdown,
            structured_context=_docgen_context(doc_version_no=3),
            build_session_id="build-1",
        )

        units = list(session.exec(select(KnowledgeUnit)).all())
        edges = list(session.exec(select(KnowledgeEdge)).all())
        source_refs = list(session.exec(select(KnowledgeGraphSourceRef)).all())
        sync_run = session.exec(select(KnowledgeGraphSyncRun)).one()
        gradient = next(unit for unit in units if unit.canonical_name == "Gradient")
        detail = get_knowledge_unit_detail(
            session,
            subject="math",
            knowledge_unit_id=gradient.id or 0,
        )

    assert report.backbone_unit_count == 1
    assert report.backbone_edge_count == 1
    assert report.source_ref_count >= 2
    assert report.doc_version_no == 3
    assert sync_run.doc_version_no == 3
    assert sync_run.graph_revision_no == report.build_revision_no
    assert sync_run.status == "completed"
    assert {unit.canonical_name for unit in units} >= {"Derivative", "Gradient"}
    assert any(edge.edge_type == "prerequisite" for edge in edges)

    gradient_refs = [
        ref
        for ref in source_refs
        if ref.entity_type == "unit" and ref.entity_id == gradient.id
    ]
    assert gradient_refs
    assert gradient_refs[0].knowledge_document_id == 11
    assert gradient_refs[0].chapter_index == 1
    assert gradient_refs[0].source_kind == "docgen_backbone"
    assert json.loads(gradient_refs[0].source_file_ids_json) == [7]
    assert detail is not None
    assert detail.source_refs[0].chapter_title == "Derivative"
    assert detail.source_refs[0].doc_version_no == 3
    assert detail.source_refs[0].source_file_ids == [7]


def test_docs_sync_backbone_only_fills_missing_units(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="Derivative",
                    knowledge_unit_type="definition",
                    local_summary="Derivative is the rate of change.",
                    taxonomy_hint="Derivative",
                ),
                CandidateNode(
                    name="Gradient",
                    knowledge_unit_type="concept",
                    local_summary="Gradient is the local slope direction.",
                    taxonomy_hint="Derivative",
                ),
            ],
            edges=[],
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = "# Derivative\n\nDerivative describes change rate and gradient.\n"

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(
            session,
            subject="math",
            markdown=markdown,
            structured_context=_docgen_context(doc_version_no=3),
            build_session_id="build-1",
        )

        units = list(session.exec(select(KnowledgeUnit)).all())

    assert report.backbone_unit_count == 0
    assert [unit.canonical_name for unit in units].count("Gradient") == 1


def test_docs_sync_keeps_unit_identity_across_doc_versions(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="Derivative",
                    knowledge_unit_type="concept",
                    local_summary="Derivative is the rate of change.",
                    taxonomy_hint="Derivative",
                )
            ],
            edges=[],
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = "# Derivative\n\nDerivative describes change rate.\n"

    with Session(engine) as session:
        session.add(
            KnowledgeDocument(
                id=11,
                subject="math",
                chapter_index=1,
                title="Derivative",
                summary="Derivative basics.",
                source_file_ids="[7]",
                version_no=3,
            )
        )
        session.commit()

        sync_markdown_knowledge_graph(
            session,
            subject="math",
            markdown=markdown,
            structured_context=_docgen_context(doc_version_no=3),
            build_session_id="build-1",
        )
        gradient_id = session.exec(
            select(KnowledgeUnit.id).where(KnowledgeUnit.canonical_name == "Gradient")
        ).one()

        sync_markdown_knowledge_graph(
            session,
            subject="math",
            markdown=markdown,
            structured_context=_docgen_context(doc_version_no=4),
            build_session_id="build-2",
        )
        rebuilt_gradient_id = session.exec(
            select(KnowledgeUnit.id).where(KnowledgeUnit.canonical_name == "Gradient")
        ).one()
        sync_runs = list(session.exec(select(KnowledgeGraphSyncRun).order_by(KnowledgeGraphSyncRun.id)).all())

    assert rebuilt_gradient_id == gradient_id
    assert [run.doc_version_no for run in sync_runs] == [3, 4]
