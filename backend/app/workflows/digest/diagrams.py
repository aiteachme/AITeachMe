"""Pure digest workflow diagram definitions."""

from app.workflows.common.topology import (
    TERMINAL_NODE,
    WorkflowConditionalEdgeSpec,
    WorkflowDiagramSpec,
    WorkflowEdgeSpec,
)

KG_DIGEST_DIAGRAM = WorkflowDiagramSpec(
    key="digest_graph",
    title="Digest Graph Workflow",
    description="增量知识图谱构建的 LangGraph 工作流。",
    entry_point="acquire_lock",
    nodes=(
        "acquire_lock",
        "prepare",
        "extract",
        "cluster",
        "resolve_nodes",
        "resolve_edges",
        "analyze_impact",
        "finalize_graph",
        "fail",
    ),
    conditional_edges=(
        WorkflowConditionalEdgeSpec(
            source="acquire_lock",
            mapping={"prepare": "prepare", "fail": "fail"},
        ),
        WorkflowConditionalEdgeSpec(
            source="prepare",
            mapping={
                "extract": "extract",
                "finalize_graph": "finalize_graph",
                "fail": "fail",
            },
        ),
        WorkflowConditionalEdgeSpec(
            source="extract",
            mapping={"continue": "cluster", "fail": "fail"},
        ),
        WorkflowConditionalEdgeSpec(
            source="cluster",
            mapping={"continue": "resolve_nodes", "fail": "fail"},
        ),
        WorkflowConditionalEdgeSpec(
            source="resolve_nodes",
            mapping={"continue": "resolve_edges", "fail": "fail"},
        ),
        WorkflowConditionalEdgeSpec(
            source="resolve_edges",
            mapping={"continue": "analyze_impact", "fail": "fail"},
        ),
        WorkflowConditionalEdgeSpec(
            source="analyze_impact",
            mapping={"continue": "finalize_graph", "fail": "fail"},
        ),
    ),
    edges=(
        WorkflowEdgeSpec(source="finalize_graph", target=TERMINAL_NODE),
        WorkflowEdgeSpec(source="fail", target=TERMINAL_NODE),
    ),
)

CURRICULUM_DERIVE_DIAGRAM = WorkflowDiagramSpec(
    key="digest_curriculum",
    title="Digest Curriculum Workflow",
    description="课程结构派生的 LangGraph 工作流。",
    entry_point="derive_units",
    nodes=(
        "derive_units",
        "derive_theme_tree",
        "derive_prereq_dag",
        "finalize_curriculum",
        "fail_curriculum",
    ),
    conditional_edges=(
        WorkflowConditionalEdgeSpec(
            source="derive_units",
            mapping={"continue": "derive_theme_tree", "fail": "fail_curriculum"},
        ),
        WorkflowConditionalEdgeSpec(
            source="derive_theme_tree",
            mapping={"continue": "derive_prereq_dag", "fail": "fail_curriculum"},
        ),
        WorkflowConditionalEdgeSpec(
            source="derive_prereq_dag",
            mapping={"continue": "finalize_curriculum", "fail": "fail_curriculum"},
        ),
    ),
    edges=(
        WorkflowEdgeSpec(source="finalize_curriculum", target=TERMINAL_NODE),
        WorkflowEdgeSpec(source="fail_curriculum", target=TERMINAL_NODE),
    ),
)

WORKFLOW_DIAGRAMS = (KG_DIGEST_DIAGRAM, CURRICULUM_DERIVE_DIAGRAM)
