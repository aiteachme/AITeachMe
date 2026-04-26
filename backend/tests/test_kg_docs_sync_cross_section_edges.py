from sqlmodel import SQLModel, Session, create_engine, select

from app.models.knowledge_relation import KnowledgeEdge
from app.workflows.support.knowledge_graph.extraction import (
    CandidateExtractionDiagnostics,
    CandidateNode,
    ChunkExtractionResult,
)
import app.workflows.support.knowledge_graph.incremental_sync as incremental_sync
from app.workflows.support.knowledge_graph.incremental_sync import (
    sync_markdown_knowledge_graph,
)


async def _empty_search_knowledge(*args, **kwargs):
    return []


def test_sync_markdown_knowledge_graph_builds_cross_section_hint_edges(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        if kwargs["chunk_title"] == "导数":
            return (
                ChunkExtractionResult(
                    nodes=[
                        CandidateNode(
                            name="导数",
                            knowledge_unit_type="concept",
                            local_summary="导数描述变化率。",
                            taxonomy_hint="导数",
                        )
                    ],
                    edges=[],
                ),
                CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=0),
            )
        return (
            ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="切线方程",
                        knowledge_unit_type="method",
                        local_summary="切线方程可以由导数求出。",
                        taxonomy_hint="导数",
                    )
                ],
                edges=[],
            ),
            CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=0),
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates_with_diagnostics", fake_extract_candidates_with_diagnostics)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# 导数 <!-- ATM_KU: ku_derivative -->

导数描述函数的变化率。

# 切线方程 <!-- ATM_KU: ku_tangent-line -->

利用导数可以写出曲线的切线方程。
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = session.exec(select(KnowledgeEdge)).all()

    assert report.unit_change_count == 2
    assert report.edge_change_count >= 1
    assert any(edge.edge_type == "derivation" for edge in edges)
