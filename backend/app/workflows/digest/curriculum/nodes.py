"""Digest curriculum workflow nodes for the flattened schema."""

from __future__ import annotations

import json

import structlog
from sqlmodel import select

from app.core.database import managed_session
from app.models import (
    CurriculumDependency,
    CurriculumTreeNode,
    CurriculumUnitLink,
    CurriculumVersion,
    KnowledgeEdge,
    KnowledgeNode,
    Subject,
    TeachingUnit,
    TeachingUnitMembership,
)
from app.utils.job_helpers import (
    activate_curriculum_entities_by_job,
    archive_old_versions,
    cleanup_pending_by_job,
    update_job_progress,
)
from app.utils.time import utcnow
from app.workflows.digest.curriculum.state import CurriculumDeriveState

logger = structlog.get_logger()


def workflow_logger(state: CurriculumDeriveState) -> structlog.stdlib.BoundLogger:
    return logger.bind(
        subject=state["subject"],
        graph_job_id=state["graph_job_id"],
        curriculum_job_id=state["curriculum_job_id"],
    )


def _get_subject_record(subject: str):
    with managed_session() as session:
        return session.exec(select(Subject).where(Subject.slug == subject)).first()


def _get_or_create_draft_curriculum_version(session, *, subject_record: Subject) -> CurriculumVersion:
    subject_id = int(subject_record.id or 0)
    draft = session.exec(
        select(CurriculumVersion)
        .where(CurriculumVersion.subject_id == subject_id, CurriculumVersion.status == "draft")
        .order_by(CurriculumVersion.version_no.desc())  # type: ignore[union-attr]
    ).first()
    if draft is not None:
        return draft

    latest = session.exec(
        select(CurriculumVersion)
        .where(CurriculumVersion.subject_id == subject_id)
        .order_by(CurriculumVersion.version_no.desc())  # type: ignore[union-attr]
    ).first()
    version = CurriculumVersion(
        user_id=subject_record.user_id,
        subject_id=subject_id,
        version_no=(latest.version_no if latest is not None else 0) + 1,
        status="draft",
        summary="",
        metadata_json="{}",
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _select_curriculum_seed_nodes(session, *, subject_id: int, impact_set) -> list[KnowledgeNode]:
    stmt = select(KnowledgeNode).where(
        KnowledgeNode.subject_id == subject_id,
        KnowledgeNode.status.in_(["active", "pending"]),  # type: ignore[union-attr]
    )
    if impact_set and impact_set.changed_node_ids:
        stmt = stmt.where(KnowledgeNode.id.in_(impact_set.changed_node_ids))  # type: ignore[union-attr]
    nodes = list(session.exec(stmt).all())
    primary = [node for node in nodes if node.node_type in {"Topic", "Concept", "Method"}]
    if primary:
        return primary
    return nodes


async def derive_units_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            impact_set = state.get("impact_set")
            subject_record = session.exec(select(Subject).where(Subject.slug == subject)).first()
            if subject_record is None or subject_record.id is None:
                return {**state, "error": f"derive_units_failed: unknown subject `{subject}`"}

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=10,
                current_step="derive_units",
            )

            seed_nodes = _select_curriculum_seed_nodes(
                session,
                subject_id=int(subject_record.id),
                impact_set=impact_set,
            )
            if not seed_nodes:
                return {**state, "derived_unit_ids": [], "error": None}

            node_ids = [int(node.id) for node in seed_nodes if node.id is not None]
            edges = list(
                session.exec(
                    select(KnowledgeEdge).where(
                        KnowledgeEdge.subject_id == int(subject_record.id),
                        KnowledgeEdge.status.in_(["active", "pending"]),  # type: ignore[union-attr]
                    )
                ).all()
            )
            child_node_ids = {
                edge.target_node_id
                for edge in edges
                if edge.source_node_id in node_ids and edge.edge_type in {"defined_by", "illustrated_by", "part_of"}
            }
            child_nodes = {
                int(node.id): node
                for node in session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.id.in_(child_node_ids))  # type: ignore[union-attr]
                ).all()
                if node.id is not None
            }

            derived_unit_ids: list[int] = []
            for index, node in enumerate(sorted(seed_nodes, key=lambda item: item.canonical_name), start=1):
                node_id = int(node.id or 0)
                member_signature = f"node:{node_id}"
                unit = session.exec(
                    select(TeachingUnit).where(
                        TeachingUnit.subject_id == int(subject_record.id),
                        TeachingUnit.member_signature == member_signature,
                    )
                ).first()
                if unit is None:
                    unit = TeachingUnit(
                        user_id=subject_record.user_id,
                        subject_id=int(subject_record.id),
                        canonical_name=node.canonical_name,
                        normalized_name=node.normalized_name,
                        member_signature=member_signature,
                        summary=node.summary,
                        learning_objectives_json=json.dumps(
                            [node.summary] if node.summary.strip() else [],
                            ensure_ascii=False,
                        ),
                        status="pending",
                        confidence=max(node.confidence, 0.6),
                    )
                    session.add(unit)
                    session.commit()
                    session.refresh(unit)
                else:
                    unit.canonical_name = node.canonical_name
                    unit.normalized_name = node.normalized_name
                    unit.summary = node.summary
                    unit.learning_objectives_json = json.dumps(
                        [node.summary] if node.summary.strip() else [],
                        ensure_ascii=False,
                    )
                    unit.updated_at = utcnow()
                    session.add(unit)
                    session.commit()

                memberships = list(
                    session.exec(
                        select(TeachingUnitMembership).where(TeachingUnitMembership.unit_id == int(unit.id or 0))
                    ).all()
                )
                for membership in memberships:
                    session.delete(membership)
                session.commit()

                session.add(
                    TeachingUnitMembership(
                        unit_id=int(unit.id or 0),
                        knowledge_node_id=node_id,
                        role="core",
                        score=1.0,
                    )
                )
                related_edges = [edge for edge in edges if edge.source_node_id == node_id]
                for edge in related_edges:
                    child = child_nodes.get(edge.target_node_id)
                    if child is None:
                        continue
                    role = "support"
                    if edge.edge_type == "illustrated_by":
                        role = "example"
                    session.add(
                        TeachingUnitMembership(
                            unit_id=int(unit.id or 0),
                            knowledge_node_id=int(child.id or 0),
                            role=role,
                            score=0.8 if role == "support" else 0.6,
                        )
                    )
                session.commit()
                derived_unit_ids.append(int(unit.id or 0))

            digest_logger.info(
                "derive_units_complete",
                units_count=len(derived_unit_ids),
                seed_node_count=len(seed_nodes),
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
            derived_unit_ids = state.get("derived_unit_ids", [])
            subject_record = session.exec(select(Subject).where(Subject.slug == subject)).first()
            if subject_record is None or subject_record.id is None:
                return {**state, "error": f"derive_theme_tree_failed: unknown subject `{subject}`"}

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=50,
                current_step="derive_theme_tree",
            )
            version = _get_or_create_draft_curriculum_version(session, subject_record=subject_record)

            for row in session.exec(
                select(CurriculumUnitLink).where(CurriculumUnitLink.curriculum_version_id == int(version.id or 0))
            ).all():
                session.delete(row)
            for row in session.exec(
                select(CurriculumTreeNode).where(CurriculumTreeNode.curriculum_version_id == int(version.id or 0))
            ).all():
                session.delete(row)
            session.commit()

            root_title = subject_record.name or subject
            root_node = CurriculumTreeNode(
                curriculum_version_id=int(version.id or 0),
                parent_tree_node_id=None,
                title=root_title,
                normalized_title=root_title.strip().lower(),
                node_type="chapter",
                anchor_type="system",
                confidence=1.0,
                is_system=True,
                order_index=0,
                summary=f"{root_title} 的知识结构",
            )
            session.add(root_node)
            session.commit()
            session.refresh(root_node)

            units = {
                int(unit.id): unit
                for unit in session.exec(
                    select(TeachingUnit).where(TeachingUnit.id.in_(derived_unit_ids))  # type: ignore[union-attr]
                ).all()
                if unit.id is not None
            }
            ordered_units = sorted(units.values(), key=lambda item: item.canonical_name)
            for index, unit in enumerate(ordered_units, start=1):
                node = CurriculumTreeNode(
                    curriculum_version_id=int(version.id or 0),
                    parent_tree_node_id=int(root_node.id or 0),
                    title=unit.canonical_name,
                    normalized_title=unit.normalized_name,
                    node_type="theme",
                    anchor_type="graph_discovered",
                    confidence=max(unit.confidence, 0.6),
                    is_system=False,
                    order_index=index,
                    summary=unit.summary,
                )
                session.add(node)
                session.commit()
                session.refresh(node)
                session.add(
                    CurriculumUnitLink(
                        curriculum_version_id=int(version.id or 0),
                        tree_node_id=int(node.id or 0),
                        teaching_unit_id=int(unit.id or 0),
                        membership_role="primary",
                        membership_source="auto",
                        score=1.0,
                    )
                )
                session.commit()

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=70,
                current_step="derive_theme_tree_done",
            )
            digest_logger.info(
                "derive_theme_tree_complete",
                version_id=int(version.id or 0),
                node_count=len(ordered_units) + 1,
            )
            return {**state, "theme_tree_version_id": int(version.id or 0), "error": None}
        except Exception as exc:
            digest_logger.error("derive_theme_tree_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"derive_theme_tree_failed: {exc}"}


async def derive_prereq_dag_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            derived_unit_ids = state.get("derived_unit_ids", [])
            subject_record = session.exec(select(Subject).where(Subject.slug == subject)).first()
            if subject_record is None or subject_record.id is None:
                return {**state, "error": f"derive_prereq_dag_failed: unknown subject `{subject}`"}

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=75,
                current_step="derive_prereq_dag",
            )
            version = _get_or_create_draft_curriculum_version(session, subject_record=subject_record)

            for row in session.exec(
                select(CurriculumDependency).where(CurriculumDependency.curriculum_version_id == int(version.id or 0))
            ).all():
                session.delete(row)
            session.commit()

            core_memberships = list(
                session.exec(
                    select(TeachingUnitMembership).where(
                        TeachingUnitMembership.unit_id.in_(derived_unit_ids),  # type: ignore[union-attr]
                        TeachingUnitMembership.role == "core",
                    )
                ).all()
            )
            unit_by_node_id = {
                membership.knowledge_node_id: int(membership.unit_id)
                for membership in core_memberships
            }

            edges = list(
                session.exec(
                    select(KnowledgeEdge).where(
                        KnowledgeEdge.subject_id == int(subject_record.id),
                        KnowledgeEdge.status.in_(["active", "pending"]),  # type: ignore[union-attr]
                        KnowledgeEdge.edge_type.in_(["prerequisite_of", "part_of"]),  # type: ignore[union-attr]
                    )
                ).all()
            )
            created_pairs: set[tuple[int, int, str]] = set()
            for edge in edges:
                source_unit_id = unit_by_node_id.get(edge.source_node_id)
                target_unit_id = unit_by_node_id.get(edge.target_node_id)
                if source_unit_id is None or target_unit_id is None or source_unit_id == target_unit_id:
                    continue
                pair = (source_unit_id, target_unit_id, "prerequisite")
                if pair in created_pairs:
                    continue
                created_pairs.add(pair)
                session.add(
                    CurriculumDependency(
                        curriculum_version_id=int(version.id or 0),
                        source_unit_id=source_unit_id,
                        target_unit_id=target_unit_id,
                        dependency_type="prerequisite",
                        confidence=edge.confidence,
                        supporting_edge_count=1,
                        derivation_metadata_json=json.dumps(
                            {"knowledge_edge_id": int(edge.id or 0)},
                            ensure_ascii=False,
                        ),
                    )
                )
            session.commit()

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=85,
                current_step="derive_prereq_dag_done",
            )
            digest_logger.info(
                "derive_prereq_dag_complete",
                version_id=int(version.id or 0),
                dependency_count=len(created_pairs),
            )
            return {**state, "prereq_dag_version_id": int(version.id or 0), "error": None}
        except Exception as exc:
            digest_logger.error("derive_prereq_dag_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"derive_prereq_dag_failed: {exc}"}


async def finalize_curriculum_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["curriculum_job_id"]
            subject = state["subject"]
            version_id = state.get("theme_tree_version_id") or state.get("prereq_dag_version_id")
            if version_id is None:
                return {**state, "snapshot_id": None, "error": None}

            activated = activate_curriculum_entities_by_job(
                session,
                job_id=job_id,
                subject=subject,
            )
            version = session.get(CurriculumVersion, int(version_id))
            if version is None:
                return {**state, "error": f"finalize_failed: missing curriculum version `{version_id}`"}

            version.status = "published"
            version.published_at = utcnow()
            version.updated_at = utcnow()
            version.summary = version.summary or "Auto-derived curriculum"
            session.add(version)
            archive_old_versions(
                session,
                subject=subject,
                current_snapshot_id=int(version.id or 0),
            )
            session.commit()

            update_job_progress(
                session,
                job_id=job_id,
                job_type="curriculum",
                progress=100,
                current_step="finalize_curriculum",
            )
            digest_logger.info(
                "curriculum_finalize_complete",
                activated=activated,
                version_id=int(version.id or 0),
                derived_unit_count=len(state.get("derived_unit_ids", [])),
            )
            return {
                **state,
                "theme_tree_version_id": int(version.id or 0),
                "prereq_dag_version_id": int(version.id or 0),
                "snapshot_id": int(version.id or 0),
                "error": None,
            }
        except Exception as exc:
            digest_logger.error("curriculum_finalize_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"finalize_failed: {exc}"}


async def fail_curriculum_node(state: CurriculumDeriveState) -> CurriculumDeriveState:
    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            cleanup_pending_by_job(
                session,
                job_id=state["curriculum_job_id"],
                job_type="curriculum",
                subject=state["subject"],
            )
            digest_logger.error("curriculum_workflow_failed", error=state.get("error", "unknown_error"))
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
