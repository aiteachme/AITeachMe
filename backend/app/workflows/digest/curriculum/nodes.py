"""Digest curriculum workflow nodes and routing."""

from __future__ import annotations

from sqlmodel import func as sqlfunc, select
import structlog

from app.workflows.digest.curriculum.services.prereq_dag_builder import derive_prereq_dag
from app.workflows.digest.curriculum.services.theme_tree_builder import derive_theme_tree
from app.workflows.digest.curriculum.services.unit_builder import derive_teaching_units
from app.core.database import managed_session
from app.models.curriculum import CurriculumSnapshot, TeachingUnit
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
from app.workflows.digest.curriculum.state import CurriculumDeriveState


logger = structlog.get_logger()


def workflow_logger(state: CurriculumDeriveState) -> structlog.stdlib.BoundLogger:
    return logger.bind(
        subject=state["subject"],
        graph_job_id=state["graph_job_id"],
        curriculum_job_id=state["curriculum_job_id"],
    )


async def derive_units_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            impact_set = state.get("impact_set")

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=10,
                current_step="derive_units",
            )
            curriculum_repo.update_curriculum_job(session, job_id, status="processing")

            if impact_set is None:
                digest_logger.warning(
                    "curriculum_no_impact_set",
                    impact_changed_nodes=0,
                    impact_affected_units=0,
                )
                return {**state, "derived_unit_ids": [], "error": None}

            units = await derive_teaching_units(
                session,
                subject,
                impact_set,
                curriculum_job_id=job_id,
            )
            derived_unit_ids = [unit.id for unit in units]  # type: ignore[misc]
            digest_logger.info(
                "derive_units_complete",
                units_count=len(derived_unit_ids),
                impact_changed_nodes=len(impact_set.changed_node_ids),
                impact_affected_units=len(impact_set.affected_unit_ids),
            )

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=40,
                current_step="derive_units_done",
            )
            return {**state, "derived_unit_ids": derived_unit_ids, "error": None}
        except Exception as exc:
            digest_logger.error("derive_units_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"derive_units_failed: {exc}"}


async def derive_theme_tree_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            impact_set = state.get("impact_set")

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=50,
                current_step="derive_theme_tree",
            )
            if impact_set is None:
                digest_logger.warning(
                    "theme_tree_no_impact_set",
                    impact_changed_nodes=0,
                    impact_affected_units=0,
                )
                return {**state, "theme_tree_version_id": None}

            previous_tree = curriculum_repo.get_current_theme_tree_version(session, subject)
            tree_version = await derive_theme_tree(
                session,
                subject,
                impact_set,
                curriculum_job_id=job_id,
                prev_tree_version=previous_tree,
            )
            digest_logger.info(
                "derive_theme_tree_complete",
                tree_version_id=tree_version.id,
                impact_changed_nodes=len(impact_set.changed_node_ids),
                impact_affected_units=len(impact_set.affected_unit_ids),
            )

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=70,
                current_step="derive_theme_tree_done",
            )
            return {**state, "theme_tree_version_id": tree_version.id, "error": None}
        except Exception as exc:
            digest_logger.error("derive_theme_tree_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"derive_theme_tree_failed: {exc}"}


async def derive_prereq_dag_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            impact_set = state.get("impact_set")

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=75,
                current_step="derive_prereq_dag",
            )
            if impact_set is None:
                digest_logger.warning(
                    "prereq_dag_no_impact_set",
                    impact_changed_nodes=0,
                    impact_affected_units=0,
                )
                return {**state, "prereq_dag_version_id": None}

            previous_dag = curriculum_repo.get_current_prereq_dag_version(session, subject)
            dag_version = await derive_prereq_dag(
                session,
                subject,
                impact_set,
                curriculum_job_id=job_id,
                prev_dag_version=previous_dag,
            )
            digest_logger.info(
                "derive_prereq_dag_complete",
                dag_version_id=dag_version.id,
                impact_changed_nodes=len(impact_set.changed_node_ids),
                impact_affected_units=len(impact_set.affected_unit_ids),
            )

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=85,
                current_step="derive_prereq_dag_done",
            )
            return {**state, "prereq_dag_version_id": dag_version.id, "error": None}
        except Exception as exc:
            digest_logger.error("derive_prereq_dag_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"derive_prereq_dag_failed: {exc}"}


async def finalize_curriculum_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            impact_set = state.get("impact_set")
            theme_tree_version_id = state.get("theme_tree_version_id")
            prereq_dag_version_id = state.get("prereq_dag_version_id")

            activated = activate_curriculum_entities_by_job(session, job_id=job_id)
            digest_logger.info("curriculum_activated", activated=activated)

            if theme_tree_version_id is not None:
                publish_theme_tree_version(session, version_id=theme_tree_version_id)
                digest_logger.info("tree_version_published", version_id=theme_tree_version_id)

            if prereq_dag_version_id is not None:
                publish_prereq_dag_version(session, version_id=prereq_dag_version_id)
                digest_logger.info("dag_version_published", version_id=prereq_dag_version_id)

            snapshot_id: int | None = None
            if theme_tree_version_id is not None or prereq_dag_version_id is not None:
                max_version_no = session.exec(
                    select(sqlfunc.max(CurriculumSnapshot.version_no)).where(
                        CurriculumSnapshot.subject == subject,
                    )
                ).one()
                snapshot = curriculum_repo.create_curriculum_snapshot(
                    session,
                    CurriculumSnapshot(
                        subject=subject,
                        version_no=(max_version_no or 0) + 1,
                        status="draft",
                        curriculum_job_id=job_id,
                        theme_tree_version_id=theme_tree_version_id,
                        prereq_dag_version_id=prereq_dag_version_id,
                        created_by_job_id=job_id,
                    ),
                )
                snapshot_id = snapshot.id
                publish_curriculum_snapshot(session, snapshot_id=snapshot_id)
                digest_logger.info("curriculum_snapshot_published", snapshot_id=snapshot_id)

            archive_old_versions(
                session,
                subject=subject,
                current_tree_version_id=theme_tree_version_id,
                current_dag_version_id=prereq_dag_version_id,
                current_snapshot_id=snapshot_id,
            )
            session.commit()

            if impact_set and impact_set.affected_unit_ids:
                derived_unit_ids = set(state.get("derived_unit_ids", []))
                for old_unit_id in impact_set.affected_unit_ids:
                    if old_unit_id in derived_unit_ids:
                        continue
                    old_unit = session.get(TeachingUnit, old_unit_id)
                    if old_unit and old_unit.status == "active":
                        old_unit.status = "deprecated"
                        session.add(old_unit)
                session.commit()

            units_added = 0
            units_updated = 0
            for unit_id in state.get("derived_unit_ids", []):
                unit = session.get(TeachingUnit, unit_id)
                if unit and unit.created_by_job_id == job_id:
                    units_added += 1
                else:
                    units_updated += 1

            update_kwargs: dict[str, object] = {
                "status": "completed",
                "units_added": units_added,
                "units_updated": units_updated,
            }
            if theme_tree_version_id is not None:
                update_kwargs["theme_tree_version_id"] = theme_tree_version_id
            if prereq_dag_version_id is not None:
                update_kwargs["prereq_dag_version_id"] = prereq_dag_version_id
            curriculum_repo.update_curriculum_job(session, job_id, **update_kwargs)

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=100,
                current_step="finalize_curriculum",
            )
            digest_logger.info(
                "curriculum_finalize_complete",
                units_added=units_added,
                units_updated=units_updated,
                tree_version_id=theme_tree_version_id,
                dag_version_id=prereq_dag_version_id,
                snapshot_id=snapshot_id,
                impact_changed_nodes=len(impact_set.changed_node_ids) if impact_set else 0,
                impact_affected_units=len(impact_set.affected_unit_ids) if impact_set else 0,
            )
            return {**state, "snapshot_id": snapshot_id, "error": None}
        except Exception as exc:
            digest_logger.error("curriculum_finalize_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"finalize_failed: {exc}"}


async def fail_curriculum_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            error_message = state.get("error", "unknown_error")
            cleanup_pending_by_job(session, job_id=job_id, job_type="curriculum")
            curriculum_repo.update_curriculum_job(
                session,
                job_id,
                status="failed",
                error_message=error_message,
            )
            digest_logger.error("curriculum_workflow_failed", error=error_message)
            return state
        except Exception as exc:
            digest_logger.error("curriculum_fail_node_error", error=str(exc), exc_info=True)
            return state


def route_after_step(state: CurriculumDeriveState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


__all__ = [
    "derive_prereq_dag_node",
    "derive_theme_tree_node",
    "derive_units_node",
    "fail_curriculum_node",
    "finalize_curriculum_node",
    "route_after_step",
]
