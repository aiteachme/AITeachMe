from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.utils.docgen_store import (
    KnowledgeBuildRuntimeEnvelope,
    KnowledgeBuildRuntimeStatus,
    build_aggregate_knowledge_build_status,
)


def _dt() -> datetime:
    return datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)


def test_aggregate_runtime_marks_graph_skip_as_completed() -> None:
    envelope = KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-1",
        docgen_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-1",
            build_kind="docgen",
            status="completed",
            stage="completed",
            progress_pct=100,
        ),
        graph_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-1",
            build_kind="graph",
            status="skipped",
            stage="disabled",
            current_stage_description="Auto graph sync is disabled.",
        ),
    )

    aggregate = build_aggregate_knowledge_build_status(envelope)

    assert aggregate is not None
    assert aggregate.status == "completed"
    assert aggregate.stage == "completed"
    assert aggregate.build_group_id == "group-1"


def test_aggregate_runtime_marks_graph_failure_as_partial_failed() -> None:
    envelope = KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-2",
        docgen_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-2",
            build_kind="docgen",
            status="completed",
            stage="completed",
            progress_pct=100,
        ),
        graph_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-2",
            build_kind="graph",
            status="failed",
            stage="failed",
            error_message="graph_crashed",
        ),
    )

    aggregate = build_aggregate_knowledge_build_status(envelope)

    assert aggregate is not None
    assert aggregate.status == "partial_failed"
    assert aggregate.error_message == "graph_crashed"


def test_aggregate_runtime_keeps_graph_partial_failed_terminal() -> None:
    envelope = KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-2b",
        docgen_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-2b",
            build_kind="docgen",
            status="completed",
            stage="completed",
            progress_pct=100,
        ),
        graph_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-2b",
            build_kind="graph",
            status="partial_failed",
            stage="partial_failed",
            error_message="kg_doc_sync_partial_failed",
            current_stage_description="知识图谱已部分同步完成。",
        ),
    )

    aggregate = build_aggregate_knowledge_build_status(envelope)

    assert aggregate is not None
    assert aggregate.status == "partial_failed"
    assert aggregate.error_message == "kg_doc_sync_partial_failed"


def test_aggregate_runtime_supports_graph_only_builds() -> None:
    envelope = KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-3",
        graph_runtime=KnowledgeBuildRuntimeStatus(
            requested_at=_dt(),
            build_group_id="group-3",
            build_kind="graph",
            status="running",
            stage="graph_docs_sync",
            progress_pct=42,
        ),
    )

    aggregate = build_aggregate_knowledge_build_status(envelope)

    assert aggregate is not None
    assert aggregate.status == "running"
    assert aggregate.stage == "graph_docs_sync"
    assert aggregate.progress_pct >= 42


def test_langgraph_config_uses_current_digest_graph_entries() -> None:
    config_path = Path(__file__).resolve().parents[1] / "langgraph.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    graphs = payload.get("graphs", {})

    assert "digest_kg" not in graphs
    assert "kg_file_ingest" not in graphs
    assert graphs["kg_doc_sync"]["path"].endswith(
        "app/workflows/digest/kg_doc_sync/graph.py:get_langgraph_dev_kg_doc_sync_graph"
    )
