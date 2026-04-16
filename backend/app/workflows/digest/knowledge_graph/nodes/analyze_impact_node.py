"""Knowledge graph analyze-impact node."""


from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter

from sqlmodel import select

from app.shared.infra.database import managed_session
from app.shared.infra.embedding import aembed_texts
from app.models.knowledge_relation import EdgeRevision, KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.utils.job_helpers import update_job_progress
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.knowledge_graph.mutations import (
    create_alias_if_new,
    create_edge_evidence,
    create_node_evidence,
    create_updated_revision,
)
from app.workflows.digest.knowledge_graph.lib.candidate_identity import (
    build_candidate_name_key,
    candidate_lookup_keys,
    normalize_scope_name,
)
from app.workflows.digest.knowledge_graph.lib.embedding_cache import (
    compute_embedding_text_hash,
    load_subject_embedding_cache,
    write_subject_embedding_cache,
)
from app.workflows.digest.knowledge_graph.lib.impact_analyzer import analyze_impact
from app.workflows.digest.knowledge_graph.lib.resolver import (
    ResolveResult,
    compute_edge_confidence,
    resolve_edge,
)
from app.workflows.digest.knowledge_graph.state import KnowledgeDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger

async def analyze_impact_node(state: KnowledgeDigestState) -> KnowledgeDigestState:
    """Compute graph-local impact scope from graph changes."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            impact = analyze_impact(
                session,
                state["subject"],
                new_node_ids=state.get("new_node_ids", []),
                updated_node_ids=state.get("updated_node_ids", []),
                merged_node_ids=state.get("merged_node_ids", []),
                split_node_ids=[],
            )
            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=85,
                current_step="analyze_impact",
            )
            digest_logger.info(
                "knowledge_workflow_impact_complete",
                changed_nodes=len(impact.changed_node_ids),
                affected_edges=len(impact.affected_edge_ids),
            )
            return {**state, "impact_set": impact}
        except Exception as exc:
            digest_logger.error("knowledge_workflow_analyze_impact_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"analyze_impact_failed: {exc}"}

__all__ = ["analyze_impact_node"]



