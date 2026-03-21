"""Pure ingest workflow diagram definitions."""

from app.workflows.common.topology import (
    TERMINAL_NODE,
    WorkflowConditionalEdgeSpec,
    WorkflowDiagramSpec,
    WorkflowEdgeSpec,
)

INGEST_PARSE_DIAGRAM = WorkflowDiagramSpec(
    key="ingest_parse",
    title="Ingest File Parse Workflow",
    description="文件解析、落盘和进入 digest 前状态收敛的 LangGraph 工作流。",
    entry_point="load_raw_file",
    nodes=(
        "load_raw_file",
        "compute_fingerprint",
        "classify_file",
        "parse_file",
        "finalize_success",
        "finalize_failure",
    ),
    conditional_edges=(
        WorkflowConditionalEdgeSpec(
            source="load_raw_file",
            mapping={"continue": "compute_fingerprint", "fail": "finalize_failure"},
        ),
        WorkflowConditionalEdgeSpec(
            source="compute_fingerprint",
            mapping={"continue": "classify_file", "fail": "finalize_failure"},
        ),
        WorkflowConditionalEdgeSpec(
            source="classify_file",
            mapping={"continue": "parse_file", "fail": "finalize_failure"},
        ),
        WorkflowConditionalEdgeSpec(
            source="parse_file",
            mapping={"continue": "finalize_success", "fail": "finalize_failure"},
        ),
        WorkflowConditionalEdgeSpec(
            source="finalize_success",
            mapping={"continue": TERMINAL_NODE, "fail": "finalize_failure"},
        ),
    ),
    edges=(
        WorkflowEdgeSpec(source="finalize_failure", target=TERMINAL_NODE),
    ),
)

WORKFLOW_DIAGRAMS = (INGEST_PARSE_DIAGRAM,)
