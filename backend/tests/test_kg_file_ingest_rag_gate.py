from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.digest.kg_file_ingest.nodes.resolve_nodes_node import (
    ExistingNodeRecord,
    ResolutionIndex,
    _match_primary_candidate,
)


def test_match_primary_candidate_requires_rag_before_semantic_merge():
    record = ExistingNodeRecord()
    record.node = KnowledgeUnit(
        id=1,
        subject="math",
        knowledge_unit_type="theorem",
        canonical_name="勾股定理",
        normalized_name="勾股定理",
        summary="直角三角形两直角边平方和等于斜边平方",
        status="active",
    )
    record.summary = "直角三角形两直角边平方和等于斜边平方"
    record.embedding = [1.0, 0.0]
    index = ResolutionIndex(
        subject="math",
        records_by_type={"theorem": [record]},
    )

    no_rag_result = _match_primary_candidate(
        "直角三角形斜边定理",
        "theorem",
        "直角三角形两直角边平方和等于斜边平方",
        [1.0, 0.0],
        index,
        allow_semantic_match=False,
    )
    rag_result = _match_primary_candidate(
        "直角三角形斜边定理",
        "theorem",
        "直角三角形两直角边平方和等于斜边平方",
        [1.0, 0.0],
        index,
        allow_semantic_match=True,
    )

    assert no_rag_result.decision == "no_match"
    assert rag_result.decision == "exact"
    assert rag_result.matched_node_id == 1
