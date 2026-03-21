"""DocGen LangGraph 图定义（Fan-Out 版本）。

图结构：
    load_files → cleanse → outline_map → outline_reduce
                                              │
                               ← Send(每章一个) →
                         ┌──────┬──────┬──────┐
                       ch_1  ch_2  ...  ch_N    ← draft_chapter (Fan-Out)
                         └──────┴──────┴──────┘
                                  │ Fan-In（operator.add）
                           collect_drafts
                                  │
                         ┌──────┬──────┬──────┐
                       rv_1  rv_2  ...  rv_N    ← review_chapter (Fan-Out)
                         └──────┴──────┴──────┘
                                  │ Fan-In
                          collect_reviews
                                  │
                         ┌──────┬──────┬──────┐
                       mt_1  mt_2  ...  mt_N    ← extract_metadata (Fan-Out)
                         └──────┴──────┴──────┘
                                  │ Fan-In
                         finalize_assemble → END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.nodes.cleanse_node import build_cleanse_node
from app.workflows.digest.docs.nodes.draft_node import build_draft_chapter_node
from app.workflows.digest.docs.nodes.finalize_node import build_finalize_assemble_node
from app.workflows.digest.docs.nodes.load_files_node import build_load_files_node
from app.workflows.digest.docs.nodes.metadata_node import build_extract_metadata_node
from app.workflows.digest.docs.nodes.outline_map_node import build_outline_map_node
from app.workflows.digest.docs.nodes.outline_reduce_node import build_outline_reduce_node
from app.workflows.digest.docs.nodes.review_node import build_review_chapter_node
from app.workflows.digest.docs.state import DocGenState


# ── 路由函数 ──


def _route_after_step(state: DocGenState) -> str:
    """有 error 则跳终点。"""
    if state.get("error"):
        return "fail"
    return "continue"


def _fan_out_to_draft(state: DocGenState) -> list[Send]:
    """outline_reduce 完成后，为每章发送一个 draft_chapter 任务。"""
    assignments = state.get("chapter_assignments", [])
    outline_tree = state.get("outline_tree", {})
    total = len(assignments)

    sends: list[Send] = []
    for idx, chapter in enumerate(assignments):
        # 上一章：截取前 400 字真实素材内容
        prev_summary = ""
        if idx > 0:
            prev_ch = assignments[idx - 1]
            prev_src = "\n".join(prev_ch.get("source_contents", []))[:400]
            prev_summary = f"上一章「{prev_ch['title']}」的内容概要：\n{prev_src}"

        next_preview = ""
        if idx < total - 1:
            next_ch = assignments[idx + 1]
            next_preview = f"下一章「{next_ch['title']}」将讨论后续主题。"

        sends.append(Send("draft_chapter", {
            "chapter": chapter,
            "job_id": state["job_id"],
            "subject": state["subject"],
            "outline_tree": outline_tree,
            "total_chapters": total,
            "prev_summary": prev_summary,
            "next_preview": next_preview,
        }))
    return sends


def _fan_out_to_review(state: DocGenState) -> list[Send]:
    """collect_drafts 后，为每章发送一个 review_chapter 任务。"""
    drafts = state.get("chapter_drafts", [])
    outline_tree = state.get("outline_tree", {})
    total = len(drafts)

    return [
        Send("review_chapter", {
            "draft": draft,
            "outline_tree": outline_tree,
            "total_chapters": total,
        })
        for draft in drafts
    ]


def _fan_out_to_metadata(state: DocGenState) -> list[Send]:
    """collect_reviews 后，为每章发送一个 extract_metadata 任务。"""
    reviews = state.get("chapter_reviews", [])
    assignments = state.get("chapter_assignments", [])

    sends: list[Send] = []
    for reviewed in reviews:
        ch_idx = reviewed.get("chapter_index", 0)
        source_file_ids: list[int] = []
        for a in assignments:
            if a.get("chapter_index") == ch_idx:
                source_file_ids = a.get("source_file_ids", [])
                break
        sends.append(Send("extract_metadata", {
            "reviewed": {**reviewed, "source_file_ids": source_file_ids},
        }))
    return sends


# ── Collector 节点（Fan-In 聚合点） ──


async def _collect_drafts(state: DocGenState) -> dict:
    """Fan-In 收集所有 draft 结果（operator.add 已自动合并）。

    此节点仅用作聚合边界，不做额外处理。
    """
    return {}  # chapter_drafts 已在 state 中自动汇聚


async def _collect_reviews(state: DocGenState) -> dict:
    """Fan-In 收集所有 review 结果。"""
    return {}  # chapter_reviews 已在 state 中自动汇聚


# ── 图构建 ──


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """构建 DocGen Fan-Out 知识文档生成工作流。"""

    wf = StateGraph(DocGenState)

    # ── 主干节点 ──
    wf.add_node("load_files", build_load_files_node(context=context))
    wf.add_node("cleanse", build_cleanse_node(context=context))
    wf.add_node("outline_map", build_outline_map_node(context=context))
    wf.add_node("outline_reduce", build_outline_reduce_node(context=context))

    # ── Fan-Out 子节点 ──
    wf.add_node("draft_chapter", build_draft_chapter_node(context=context))
    wf.add_node("collect_drafts", _collect_drafts)
    wf.add_node("review_chapter", build_review_chapter_node(context=context))
    wf.add_node("collect_reviews", _collect_reviews)
    wf.add_node("extract_metadata", build_extract_metadata_node(context=context))
    wf.add_node("finalize_assemble", build_finalize_assemble_node(context=context))

    # ── 入口 ──
    wf.set_entry_point("load_files")

    # ── 线性边（带 error 检查） ──
    wf.add_conditional_edges("load_files", _route_after_step, {"continue": "cleanse", "fail": END})
    wf.add_conditional_edges("cleanse", _route_after_step, {"continue": "outline_map", "fail": END})
    wf.add_edge("outline_map", "outline_reduce")

    # ── Fan-Out #1：outline_reduce → draft_chapter ×N → collect_drafts ──
    wf.add_conditional_edges("outline_reduce", _fan_out_to_draft)
    wf.add_edge("draft_chapter", "collect_drafts")

    # ── Fan-Out #2：collect_drafts → review_chapter ×N → collect_reviews ──
    wf.add_conditional_edges("collect_drafts", _fan_out_to_review)
    wf.add_edge("review_chapter", "collect_reviews")

    # ── Fan-Out #3：collect_reviews → extract_metadata ×N → finalize_assemble ──
    wf.add_conditional_edges("collect_reviews", _fan_out_to_metadata)
    wf.add_edge("extract_metadata", "finalize_assemble")

    wf.add_edge("finalize_assemble", END)

    return wf


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
