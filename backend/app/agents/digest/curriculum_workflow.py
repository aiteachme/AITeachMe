"""CurriculumDeriveJob 工作流状态机 v3：LangGraph StateGraph 实现。

v3 实现教学单元派生 + 主题树派生 + 先修 DAG 派生。

节点流程：
  derive_units → derive_theme_tree → derive_prereq_dag
  → finalize_curriculum → END

失败路径：
  任意节点异常 → fail_curriculum → END

finalize_curriculum_node v3：
  1. activate_curriculum_entities_by_job 批量激活 pending 单元
  2. publish tree version（draft → published）
  3. publish dag version（draft → published）
  4. 创建 CurriculumSnapshot（含 tree version + dag version）
  5. 归档旧 tree version + 旧 dag version + 旧 snapshot
  6. 标记受影响范围内未被保留的旧 active unit 为 deprecated
  7. 更新 job 状态为 completed
"""

from __future__ import annotations

import traceback
from typing import TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session, func as sqlfunc, select

from app.agents.digest.kg_impact_analyzer import ImpactSet
from app.agents.digest.prereq_dag_builder import derive_prereq_dag
from app.agents.digest.theme_tree_builder import derive_theme_tree
from app.agents.digest.unit_builder import derive_teaching_units
from app.core.database import get_session
from app.models.curriculum import (
    CurriculumDeriveJob,
    CurriculumSnapshot,
    PrereqDagVersion,
    TeachingUnit,
)
from app.repositories import curriculum_repo
from app.utils.job_helpers import (
    activate_curriculum_entities_by_job,
    archive_old_versions,
    cleanup_pending_by_job,
    publish_curriculum_snapshot,
    publish_prereq_dag_version,
    publish_theme_tree_version,
    update_job_progress,
)

logger = structlog.get_logger()


# ── State 定义 ────────────────────────────────────────────────


class CurriculumDeriveState(TypedDict, total=False):
    subject: str
    graph_job_id: int
    curriculum_job_id: int
    impact_set: ImpactSet | None
    derived_unit_ids: list[int]
    theme_tree_version_id: int | None
    prereq_dag_version_id: int | None
    snapshot_id: int | None  # v1 恒为 None，v2/v3 使用
    error: str | None


# ── 工作流节点 ────────────────────────────────────────────────


async def derive_units_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    """教学单元派生：从影响集中受影响的知识节点生成/更新教学单元。"""
    session = get_session()
    try:
        job_id = state["curriculum_job_id"]
        subject = state["subject"]
        impact_set = state.get("impact_set")

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=10, current_step="derive_units",
        )

        # 更新 job 状态为 processing
        curriculum_repo.update_curriculum_job(session, job_id, status="processing")

        if impact_set is None:
            logger.warning("curriculum_no_impact_set", job_id=job_id)
            return {**state, "derived_unit_ids": [], "error": None}

        units = await derive_teaching_units(
            session, subject, impact_set, curriculum_job_id=job_id,
        )

        derived_ids = [u.id for u in units]  # type: ignore[misc]
        logger.info(
            "derive_units_complete",
            job_id=job_id,
            units_count=len(derived_ids),
        )

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=40, current_step="derive_units_done",
        )

        return {**state, "derived_unit_ids": derived_ids, "error": None}
    except Exception as exc:
        logger.error("derive_units_failed", error=str(exc), exc_info=True)
        return {**state, "error": f"derive_units_failed: {exc}"}
    finally:
        session.close()


async def derive_theme_tree_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    """主题树派生：基于 Anchor 软约束 + 教学单元生成主题树 draft 版本。"""
    session = get_session()
    try:
        job_id = state["curriculum_job_id"]
        subject = state["subject"]
        impact_set = state.get("impact_set")

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=50, current_step="derive_theme_tree",
        )

        if impact_set is None:
            logger.warning("theme_tree_no_impact_set", job_id=job_id)
            return {**state, "theme_tree_version_id": None}

        prev_tree = curriculum_repo.get_current_theme_tree_version(session, subject)

        tree_version = await derive_theme_tree(
            session, subject, impact_set,
            curriculum_job_id=job_id,
            prev_tree_version=prev_tree,
        )

        logger.info(
            "derive_theme_tree_complete",
            job_id=job_id,
            tree_version_id=tree_version.id,
        )

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=70, current_step="derive_theme_tree_done",
        )

        return {**state, "theme_tree_version_id": tree_version.id, "error": None}
    except Exception as exc:
        logger.error("derive_theme_tree_failed", error=str(exc), exc_info=True)
        return {**state, "error": f"derive_theme_tree_failed: {exc}"}
    finally:
        session.close()


async def derive_prereq_dag_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    """先修 DAG 派生：从知识图谱依赖边聚合出教学单元级别的先修 DAG。"""
    session = get_session()
    try:
        job_id = state["curriculum_job_id"]
        subject = state["subject"]
        impact_set = state.get("impact_set")

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=75, current_step="derive_prereq_dag",
        )

        if impact_set is None:
            logger.warning("prereq_dag_no_impact_set", job_id=job_id)
            return {**state, "prereq_dag_version_id": None}

        prev_dag = curriculum_repo.get_current_prereq_dag_version(session, subject)

        dag_version = await derive_prereq_dag(
            session, subject, impact_set,
            curriculum_job_id=job_id,
            prev_dag_version=prev_dag,
        )

        logger.info(
            "derive_prereq_dag_complete",
            job_id=job_id,
            dag_version_id=dag_version.id,
        )

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=85, current_step="derive_prereq_dag_done",
        )

        return {**state, "prereq_dag_version_id": dag_version.id, "error": None}
    except Exception as exc:
        logger.error("derive_prereq_dag_failed", error=str(exc), exc_info=True)
        return {**state, "error": f"derive_prereq_dag_failed: {exc}"}
    finally:
        session.close()


async def finalize_curriculum_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    """v3 finalize：激活 pending → publish tree → publish dag → 创建 snapshot → 归档旧版本 → deprecate 旧 unit → 更新 job。

    publish/archive 操作仅在此函数中执行，builder 只产出 draft/pending。
    """
    session = get_session()
    try:
        job_id = state["curriculum_job_id"]
        subject = state["subject"]
        impact_set = state.get("impact_set")
        tree_version_id = state.get("theme_tree_version_id")
        dag_version_id = state.get("prereq_dag_version_id")

        # 1. 批量激活 pending → active
        activated = activate_curriculum_entities_by_job(session, job_id=job_id)
        logger.info("curriculum_activated", job_id=job_id, activated=activated)

        # 2. publish tree version（draft → published）
        if tree_version_id is not None:
            publish_theme_tree_version(session, version_id=tree_version_id)
            logger.info("tree_version_published", version_id=tree_version_id)

        # 3. publish dag version（draft → published）
        if dag_version_id is not None:
            publish_prereq_dag_version(session, version_id=dag_version_id)
            logger.info("dag_version_published", version_id=dag_version_id)

        # 4. 创建 CurriculumSnapshot（含 tree version + dag version）
        snapshot_id: int | None = None
        if tree_version_id is not None or dag_version_id is not None:
            # 计算下一个 snapshot version_no
            max_vno_stmt = select(sqlfunc.max(CurriculumSnapshot.version_no)).where(
                CurriculumSnapshot.subject == subject,
            )
            current_max: int | None = session.exec(max_vno_stmt).one()
            next_vno = (current_max or 0) + 1

            snapshot = CurriculumSnapshot(
                subject=subject,
                version_no=next_vno,
                status="draft",
                curriculum_job_id=job_id,
                theme_tree_version_id=tree_version_id,
                prereq_dag_version_id=dag_version_id,
                created_by_job_id=job_id,
            )
            snapshot = curriculum_repo.create_curriculum_snapshot(session, snapshot)
            snapshot_id = snapshot.id

            # publish snapshot
            publish_curriculum_snapshot(session, snapshot_id=snapshot_id)
            logger.info("curriculum_snapshot_published", snapshot_id=snapshot_id)

        # 5. 归档旧 tree version + 旧 dag version + 旧 snapshot
        archive_old_versions(
            session,
            subject=subject,
            current_tree_version_id=tree_version_id,
            current_dag_version_id=dag_version_id,
            current_snapshot_id=snapshot_id,
        )
        session.commit()

        # 6. 标记受影响范围内未被新结果保留的旧 active unit 为 deprecated
        if impact_set and impact_set.affected_unit_ids:
            derived_ids = set(state.get("derived_unit_ids", []))
            for old_unit_id in impact_set.affected_unit_ids:
                if old_unit_id not in derived_ids:
                    old_unit = session.get(TeachingUnit, old_unit_id)
                    if old_unit and old_unit.status == "active":
                        old_unit.status = "deprecated"
                        session.add(old_unit)
            session.commit()

        # 7. 统计 units_added / units_updated
        derived_ids_list = state.get("derived_unit_ids", [])
        units_added = 0
        units_updated = 0
        for uid in derived_ids_list:
            unit = session.get(TeachingUnit, uid)
            if unit and unit.created_by_job_id == job_id:
                units_added += 1
            else:
                units_updated += 1

        # 8. 更新 job 状态
        update_kwargs: dict[str, object] = {
            "status": "completed",
            "units_added": units_added,
            "units_updated": units_updated,
        }
        if tree_version_id is not None:
            update_kwargs["theme_tree_version_id"] = tree_version_id
        if dag_version_id is not None:
            update_kwargs["prereq_dag_version_id"] = dag_version_id
        curriculum_repo.update_curriculum_job(session, job_id, **update_kwargs)

        update_job_progress(
            session, job_id=job_id, job_type="curriculum",
            progress=100, current_step="finalize_curriculum",
        )

        logger.info(
            "curriculum_finalize_complete",
            job_id=job_id,
            units_added=units_added,
            units_updated=units_updated,
            tree_version_id=tree_version_id,
            dag_version_id=dag_version_id,
            snapshot_id=snapshot_id,
        )
        return {**state, "snapshot_id": snapshot_id, "error": None}
    except Exception as exc:
        logger.error("curriculum_finalize_failed", error=str(exc), exc_info=True)
        return {**state, "error": f"finalize_failed: {exc}"}
    finally:
        session.close()


async def fail_curriculum_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    """失败处理：清理 pending 数据 + 更新 job 状态。"""
    session = get_session()
    try:
        job_id = state["curriculum_job_id"]
        error_msg = state.get("error", "unknown_error")

        # 清理 pending 数据（按 created_by_job_id 精确清理）
        cleanup_pending_by_job(session, job_id=job_id, job_type="curriculum")

        # 更新 job 状态
        curriculum_repo.update_curriculum_job(
            session, job_id,
            status="failed",
            error_message=error_msg,
        )

        logger.error("curriculum_workflow_failed", job_id=job_id, error=error_msg)
        return state
    except Exception as exc:
        logger.error("curriculum_fail_node_error", error=str(exc), exc_info=True)
        return state
    finally:
        session.close()


# ── 路由函数 ──────────────────────────────────────────────────


def _route_after_step(state: CurriculumDeriveState) -> str:
    """通用步骤后路由：有 error → fail_curriculum，否则继续。"""
    if state.get("error"):
        return "fail"
    return "continue"


# ── 构建 LangGraph StateGraph ────────────────────────────────


def build_curriculum_derive_graph() -> StateGraph:
    """构建 CurriculumDeriveJob 工作流状态图。"""
    workflow = StateGraph(CurriculumDeriveState)

    # 添加节点
    workflow.add_node("derive_units", derive_units_node)
    workflow.add_node("derive_theme_tree", derive_theme_tree_node)
    workflow.add_node("derive_prereq_dag", derive_prereq_dag_node)
    workflow.add_node("finalize_curriculum", finalize_curriculum_node)
    workflow.add_node("fail_curriculum", fail_curriculum_node)

    # 入口
    workflow.set_entry_point("derive_units")

    # 条件分支
    workflow.add_conditional_edges(
        "derive_units",
        _route_after_step,
        {"continue": "derive_theme_tree", "fail": "fail_curriculum"},
    )
    workflow.add_conditional_edges(
        "derive_theme_tree",
        _route_after_step,
        {"continue": "derive_prereq_dag", "fail": "fail_curriculum"},
    )
    workflow.add_conditional_edges(
        "derive_prereq_dag",
        _route_after_step,
        {"continue": "finalize_curriculum", "fail": "fail_curriculum"},
    )

    # 终止边
    workflow.add_edge("finalize_curriculum", END)
    workflow.add_edge("fail_curriculum", END)

    return workflow


# ── 工作流入口 ────────────────────────────────────────────────


async def run_curriculum_derive_workflow(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    impact_set: ImpactSet | None,
) -> CurriculumDeriveState:
    """执行 CurriculumDeriveJob 工作流。

    Args:
        subject: 学科标识。
        graph_job_id: 关联的 GraphDigestJob ID。
        curriculum_job_id: CurriculumDeriveJob ID。
        impact_set: 图谱增量构建产出的影响集。

    Returns:
        最终工作流状态。
    """
    graph = build_curriculum_derive_graph()
    compiled = graph.compile()

    initial_state: CurriculumDeriveState = {
        "subject": subject,
        "graph_job_id": graph_job_id,
        "curriculum_job_id": curriculum_job_id,
        "impact_set": impact_set,
        "derived_unit_ids": [],
        "theme_tree_version_id": None,
        "prereq_dag_version_id": None,
        "snapshot_id": None,
        "error": None,
    }

    result = await compiled.ainvoke(initial_state)
    return result  # type: ignore[return-value]
