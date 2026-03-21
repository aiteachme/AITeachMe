"""DocGen LangGraph 图定义。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.nodes.cleanse_node import build_cleanse_node
from app.workflows.digest.docs.nodes.draft_node import build_draft_node
from app.workflows.digest.docs.nodes.finalize_node import build_finalize_node
from app.workflows.digest.docs.nodes.outline_node import build_outline_node
from app.workflows.digest.docs.state import DocGenState


def _route_after_step(state: DocGenState) -> str:
    """节点完成后路由：有错误则跳到失败终点，否则继续。"""

    if state.get("error"):
        return "fail"
    return "continue"


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """构建 DocGen 知识文档生成工作流。

    流水线：cleanse → outline → draft → finalize → END
              ↘         ↘        ↘        ↘
                          fail → END
    """

    workflow = StateGraph(DocGenState)

    # 注册节点
    workflow.add_node("cleanse", build_cleanse_node(context=context))
    workflow.add_node("outline", build_outline_node(context=context))
    workflow.add_node("draft", build_draft_node(context=context))
    workflow.add_node("finalize", build_finalize_node(context=context))

    # 设置入口
    workflow.set_entry_point("cleanse")

    # 条件边：每步完成后检查是否有错误
    workflow.add_conditional_edges(
        "cleanse",
        _route_after_step,
        {"continue": "outline", "fail": END},
    )
    workflow.add_conditional_edges(
        "outline",
        _route_after_step,
        {"continue": "draft", "fail": END},
    )
    workflow.add_conditional_edges(
        "draft",
        _route_after_step,
        {"continue": "finalize", "fail": END},
    )
    workflow.add_edge("finalize", END)

    return workflow


def create_docgen_initial_state(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
) -> DocGenState:
    """创建 DocGen 工作流初始状态。"""

    return DocGenState(
        subject=subject,
        job_id=job_id,
        file_ids=file_ids,
        error=None,
    )


__all__ = ["build_docgen_graph", "create_docgen_initial_state"]
