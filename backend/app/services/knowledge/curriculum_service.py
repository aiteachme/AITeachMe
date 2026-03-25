"""Curriculum read/write helpers backed by the new schema."""

from __future__ import annotations

import json
import shutil

from sqlmodel import Session, select

from app.core.exceptions import (
    NoPublishedCurriculumSnapshotError,
    NoPublishedDagError,
    NoPublishedTreeError,
    TeachingUnitNotFoundError,
)
from app.models import (
    CurriculumDependency,
    CurriculumTreeNode,
    CurriculumUnitLink,
    CurriculumVersion,
    ExamPaper,
    ExamPaperItem,
    KnowledgeAlias,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeEvidence,
    KnowledgeNode,
    QuestionTemplate,
    QuestionTemplateNodeLink,
    RetrievalChunk,
    ReviewTask,
    Subject,
    TeachingUnit,
    TeachingUnitMembership,
    UserAnswerAttempt,
    UserKnowledgeState,
)
from app.repositories.knowledge.knowledge_repo import delete_embeddings_by_chunk_ids
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.knowledge import (
    CurriculumSnapshotResponse,
    PrereqDagResponse,
    TaxonomyAnchorResponse,
    TeachingUnitDetailResponse,
    TeachingUnitResponse,
    ThemeTreeNodeResponse,
    ThemeTreeResponse,
    TreeUnitItem,
    UnitDependencyItem,
    UnitMembershipItem,
    UnitRevisionItem,
)
from app.services.knowledge.docgen_store import clear_docgen_staging, clear_published_knowledge_docs_files
from app.services.upload_support import build_knowledge_markdown_dir
from app.utils.time import utcnow


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    return []


def _parse_json_dict(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _get_subject_record(session: Session, subject: str) -> Subject | None:
    return session.exec(select(Subject).where(Subject.slug == subject)).first()


def _get_current_curriculum_version(
    session: Session,
    *,
    subject_id: int,
    status: str = "published",
) -> CurriculumVersion | None:
    return session.exec(
        select(CurriculumVersion)
        .where(CurriculumVersion.subject_id == subject_id, CurriculumVersion.status == status)
        .order_by(CurriculumVersion.version_no.desc())  # type: ignore[union-attr]
    ).first()


def _get_or_create_draft_curriculum_version(
    session: Session,
    *,
    subject_record: Subject,
) -> CurriculumVersion:
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
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _build_teaching_unit_response(subject: str, unit: TeachingUnit) -> TeachingUnitResponse:
    return TeachingUnitResponse(
        id=int(unit.id or 0),
        subject=subject,
        canonical_name=unit.canonical_name,
        status=unit.status,
        confidence=unit.confidence,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )


def get_teaching_units(
    session: Session,
    *,
    subject: str,
    status: str | None = "active",
    page: int = 1,
    size: int = 20,
) -> PaginatedData[TeachingUnitResponse]:
    """Return paginated teaching units."""

    subject_record = _get_subject_record(session, subject)
    if subject_record is None or subject_record.id is None:
        return build_paginated_data(items=[], page=page, size=size, total=0)

    offset = (page - 1) * size
    stmt = select(TeachingUnit).where(TeachingUnit.subject_id == subject_record.id)
    count_stmt = select(TeachingUnit).where(TeachingUnit.subject_id == subject_record.id)
    if status is not None:
        stmt = stmt.where(TeachingUnit.status == status)
        count_stmt = count_stmt.where(TeachingUnit.status == status)

    total = len(list(session.exec(count_stmt).all()))
    rows = list(
        session.exec(
            stmt.order_by(TeachingUnit.updated_at.desc()).offset(offset).limit(size)  # type: ignore[union-attr]
        ).all()
    )
    return build_paginated_data(
        items=[_build_teaching_unit_response(subject, unit) for unit in rows],
        page=page,
        size=size,
        total=total,
    )


def get_teaching_unit_detail(
    session: Session,
    *,
    subject: str,
    unit_id: int,
) -> TeachingUnitDetailResponse:
    """Return detail for one teaching unit."""

    subject_record = _get_subject_record(session, subject)
    unit = session.get(TeachingUnit, unit_id)
    if subject_record is None or subject_record.id is None or unit is None or unit.subject_id != subject_record.id:
        raise TeachingUnitNotFoundError(unit_id)

    memberships = list(
        session.exec(
            select(TeachingUnitMembership)
            .where(TeachingUnitMembership.unit_id == unit_id)
            .order_by(TeachingUnitMembership.score.desc(), TeachingUnitMembership.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    node_ids = [membership.knowledge_node_id for membership in memberships]
    node_map = {
        int(node.id): node
        for node in session.exec(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))  # type: ignore[union-attr]
        ).all()
        if node.id is not None
    }
    members = [
        UnitMembershipItem(
            id=int(membership.id or 0),
            knowledge_node_id=membership.knowledge_node_id,
            node_canonical_name=node_map[membership.knowledge_node_id].canonical_name
            if membership.knowledge_node_id in node_map
            else f"node#{membership.knowledge_node_id}",
            node_type=node_map[membership.knowledge_node_id].node_type
            if membership.knowledge_node_id in node_map
            else "unknown",
            role=membership.role,
            score=membership.score,
        )
        for membership in memberships
    ]

    return TeachingUnitDetailResponse(
        id=int(unit.id or 0),
        subject=subject,
        canonical_name=unit.canonical_name,
        normalized_name=unit.normalized_name,
        member_signature=unit.member_signature,
        status=unit.status,
        confidence=unit.confidence,
        current_revision=UnitRevisionItem(
            title=unit.canonical_name,
            summary=unit.summary,
            learning_objectives=_parse_json_list(unit.learning_objectives_json),
        ),
        members=members,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )


def _build_theme_tree(
    session: Session,
    *,
    subject: str,
    version: CurriculumVersion,
) -> ThemeTreeResponse:
    nodes = list(
        session.exec(
            select(CurriculumTreeNode)
            .where(CurriculumTreeNode.curriculum_version_id == int(version.id or 0))
            .order_by(CurriculumTreeNode.order_index.asc(), CurriculumTreeNode.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    links = list(
        session.exec(
            select(CurriculumUnitLink)
            .where(CurriculumUnitLink.curriculum_version_id == int(version.id or 0))
            .order_by(CurriculumUnitLink.score.desc(), CurriculumUnitLink.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    unit_ids = [link.teaching_unit_id for link in links]
    unit_map = {
        int(unit.id): unit
        for unit in session.exec(
            select(TeachingUnit).where(TeachingUnit.id.in_(unit_ids))  # type: ignore[union-attr]
        ).all()
        if unit.id is not None
    }
    units_by_node: dict[int, list[TreeUnitItem]] = {}
    for link in links:
        unit = unit_map.get(link.teaching_unit_id)
        if unit is None:
            continue
        units_by_node.setdefault(link.tree_node_id, []).append(
            TreeUnitItem(
                teaching_unit_id=link.teaching_unit_id,
                canonical_name=unit.canonical_name,
                membership_role=link.membership_role,
                membership_source=link.membership_source,
                score=link.score,
            )
        )

    payloads: dict[int, ThemeTreeNodeResponse] = {}
    for node in nodes:
        payloads[int(node.id or 0)] = ThemeTreeNodeResponse(
            id=int(node.id or 0),
            tree_version_id=int(version.id or 0),
            anchor_id=int(node.id or 0),
            parent_tree_node_id=node.parent_tree_node_id,
            title=node.title,
            node_type=node.node_type,
            order_index=node.order_index,
            summary=node.summary,
            children=[],
            units=units_by_node.get(int(node.id or 0), []),
        )

    roots: list[ThemeTreeNodeResponse] = []
    for node in nodes:
        payload = payloads[int(node.id or 0)]
        if node.parent_tree_node_id and node.parent_tree_node_id in payloads:
            payloads[node.parent_tree_node_id].children.append(payload)
        else:
            roots.append(payload)

    return ThemeTreeResponse(
        version_id=int(version.id or 0),
        version_no=version.version_no,
        subject=subject,
        status=version.status,
        created_at=version.created_at,
        tree=roots,
    )


def get_current_theme_tree(session: Session, *, subject: str) -> ThemeTreeResponse:
    """Return the current published curriculum tree."""

    subject_record = _get_subject_record(session, subject)
    if subject_record is None or subject_record.id is None:
        raise NoPublishedTreeError(subject)
    version = _get_current_curriculum_version(session, subject_id=subject_record.id, status="published")
    if version is None:
        raise NoPublishedTreeError(subject)
    return _build_theme_tree(session, subject=subject, version=version)


def get_current_prereq_dag(session: Session, *, subject: str) -> PrereqDagResponse:
    """Return dependencies from the current published curriculum version."""

    subject_record = _get_subject_record(session, subject)
    if subject_record is None or subject_record.id is None:
        raise NoPublishedDagError(subject)
    version = _get_current_curriculum_version(session, subject_id=subject_record.id, status="published")
    if version is None:
        raise NoPublishedDagError(subject)

    dependencies = list(
        session.exec(
            select(CurriculumDependency)
            .where(CurriculumDependency.curriculum_version_id == int(version.id or 0))
            .order_by(CurriculumDependency.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    unit_ids = {item.source_unit_id for item in dependencies} | {item.target_unit_id for item in dependencies}
    unit_map = {
        int(unit.id): unit
        for unit in session.exec(
            select(TeachingUnit).where(TeachingUnit.id.in_(unit_ids))  # type: ignore[union-attr]
        ).all()
        if unit.id is not None
    }
    return PrereqDagResponse(
        version_id=int(version.id or 0),
        version_no=version.version_no,
        subject=subject,
        status=version.status,
        created_at=version.created_at,
        dependencies=[
            UnitDependencyItem(
                id=int(item.id or 0),
                source_unit_id=item.source_unit_id,
                source_unit_name=unit_map[item.source_unit_id].canonical_name
                if item.source_unit_id in unit_map
                else f"unit#{item.source_unit_id}",
                target_unit_id=item.target_unit_id,
                target_unit_name=unit_map[item.target_unit_id].canonical_name
                if item.target_unit_id in unit_map
                else f"unit#{item.target_unit_id}",
                dependency_type=item.dependency_type,
                confidence=item.confidence,
                supporting_edge_count=item.supporting_edge_count,
            )
            for item in dependencies
        ],
    )


def get_current_curriculum_snapshot(session: Session, *, subject: str) -> CurriculumSnapshotResponse:
    """Return the published curriculum version mapped into the snapshot schema."""

    subject_record = _get_subject_record(session, subject)
    if subject_record is None or subject_record.id is None:
        raise NoPublishedCurriculumSnapshotError(subject)
    version = _get_current_curriculum_version(session, subject_id=subject_record.id, status="published")
    if version is None:
        raise NoPublishedCurriculumSnapshotError(subject)

    metadata = _parse_json_dict(version.metadata_json)
    syllabus_version_id = metadata.get("syllabus_version_id")
    return CurriculumSnapshotResponse(
        id=int(version.id or 0),
        subject=subject,
        version_no=version.version_no,
        status=version.status,
        theme_tree_version_id=int(version.id or 0),
        prereq_dag_version_id=int(version.id or 0),
        syllabus_version_id=int(syllabus_version_id) if isinstance(syllabus_version_id, int) else None,
        created_at=version.created_at,
    )


def _build_anchor_response(
    *,
    subject: str,
    version: CurriculumVersion,
    node: CurriculumTreeNode,
) -> TaxonomyAnchorResponse:
    return TaxonomyAnchorResponse(
        id=int(node.id or 0),
        subject=subject,
        anchor_type=node.anchor_type,
        title=node.title,
        parent_anchor_id=node.parent_tree_node_id,
        order_index=node.order_index,
        confidence=node.confidence,
        is_system=node.is_system,
        status=version.status,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def _collect_subtree_ids(session: Session, *, root_id: int) -> list[int]:
    pending = [root_id]
    collected: list[int] = []
    while pending:
        current_id = pending.pop()
        collected.append(current_id)
        child_ids = list(
            session.exec(select(CurriculumTreeNode.id).where(CurriculumTreeNode.parent_tree_node_id == current_id)).all()
        )
        pending.extend(int(child_id) for child_id in child_ids if child_id is not None)
    return collected


def manage_taxonomy_anchors(
    session: Session,
    *,
    subject: str,
    action: str,
    anchor_id: int | None = None,
    title: str | None = None,
    anchor_type: str | None = None,
    parent_anchor_id: int | None = None,
    order_index: int | None = None,
) -> list[TaxonomyAnchorResponse]:
    """Manage anchor-like tree nodes using the unified curriculum tree table."""

    subject_record = _get_subject_record(session, subject)
    if subject_record is None or subject_record.id is None:
        return []

    normalized_action = (action or "list").strip().lower()
    version = _get_or_create_draft_curriculum_version(session, subject_record=subject_record)

    if normalized_action == "create":
        if title:
            session.add(
                CurriculumTreeNode(
                    curriculum_version_id=int(version.id or 0),
                    parent_tree_node_id=parent_anchor_id,
                    title=title,
                    normalized_title=title.strip().lower(),
                    node_type="theme",
                    anchor_type=anchor_type or "teacher_defined",
                    order_index=order_index or 0,
                )
            )
            session.commit()
    elif normalized_action == "update" and anchor_id is not None:
        node = session.get(CurriculumTreeNode, anchor_id)
        if node is not None and node.curriculum_version_id == int(version.id or 0):
            if title is not None:
                node.title = title
                node.normalized_title = title.strip().lower()
            if anchor_type is not None:
                node.anchor_type = anchor_type
            node.parent_tree_node_id = parent_anchor_id
            if order_index is not None:
                node.order_index = order_index
            node.updated_at = utcnow()
            session.add(node)
            session.commit()
    elif normalized_action == "delete" and anchor_id is not None:
        subtree_ids = _collect_subtree_ids(session, root_id=anchor_id)
        links = list(
            session.exec(
                select(CurriculumUnitLink).where(CurriculumUnitLink.tree_node_id.in_(subtree_ids))  # type: ignore[union-attr]
            ).all()
        )
        for link in links:
            session.delete(link)
        nodes = list(
            session.exec(
                select(CurriculumTreeNode).where(CurriculumTreeNode.id.in_(subtree_ids))  # type: ignore[union-attr]
            ).all()
        )
        for node in nodes:
            session.delete(node)
        session.commit()

    rows = list(
        session.exec(
            select(CurriculumTreeNode)
            .where(CurriculumTreeNode.curriculum_version_id == int(version.id or 0))
            .order_by(CurriculumTreeNode.order_index.asc(), CurriculumTreeNode.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    return [_build_anchor_response(subject=subject, version=version, node=row) for row in rows]


def clear_subject_knowledge(session: Session, *, subject: str) -> dict[str, int]:
    """Delete derived knowledge data for one subject without touching raw uploads."""

    subject_record = _get_subject_record(session, subject)
    if subject_record is None or subject_record.id is None:
        return {}

    subject_id = int(subject_record.id)
    chunk_ids = [
        int(item.id)
        for item in session.exec(select(RetrievalChunk.id).where(RetrievalChunk.subject_id == subject_id)).all()
        if item is not None
    ]
    if chunk_ids:
        delete_embeddings_by_chunk_ids(session, chunk_ids)

    question_template_ids = [
        int(item.id)
        for item in session.exec(select(QuestionTemplate.id).where(QuestionTemplate.subject_id == subject_id)).all()
        if item is not None
    ]
    exam_paper_ids = [
        int(item.id)
        for item in session.exec(select(ExamPaper.id).where(ExamPaper.subject_id == subject_id)).all()
        if item is not None
    ]
    exam_item_ids = [
        int(item.id)
        for item in session.exec(
            select(ExamPaperItem.id).where(ExamPaperItem.exam_paper_id.in_(exam_paper_ids))  # type: ignore[union-attr]
        ).all()
        if item is not None
    ]
    knowledge_node_ids = [
        int(item.id)
        for item in session.exec(select(KnowledgeNode.id).where(KnowledgeNode.subject_id == subject_id)).all()
        if item is not None
    ]
    teaching_unit_ids = [
        int(item.id)
        for item in session.exec(select(TeachingUnit.id).where(TeachingUnit.subject_id == subject_id)).all()
        if item is not None
    ]
    curriculum_version_ids = [
        int(item.id)
        for item in session.exec(select(CurriculumVersion.id).where(CurriculumVersion.subject_id == subject_id)).all()
        if item is not None
    ]

    deletion_queries: list[tuple[str, object]] = [
        (
            "user_answer_attempt",
            select(UserAnswerAttempt).where(UserAnswerAttempt.exam_paper_item_id.in_(exam_item_ids)),  # type: ignore[union-attr]
        ),
        (
            "exam_paper_item",
            select(ExamPaperItem).where(ExamPaperItem.exam_paper_id.in_(exam_paper_ids)),  # type: ignore[union-attr]
        ),
        ("exam_paper", select(ExamPaper).where(ExamPaper.subject_id == subject_id)),
        ("review_task", select(ReviewTask).where(ReviewTask.subject_id == subject_id)),
        ("user_knowledge_state", select(UserKnowledgeState).where(UserKnowledgeState.subject_id == subject_id)),
        (
            "question_template_node_link",
            select(QuestionTemplateNodeLink).where(
                QuestionTemplateNodeLink.question_template_id.in_(question_template_ids)  # type: ignore[union-attr]
            ),
        ),
        ("question_template", select(QuestionTemplate).where(QuestionTemplate.subject_id == subject_id)),
        ("knowledge_evidence", select(KnowledgeEvidence).where(KnowledgeEvidence.subject_id == subject_id)),
        ("knowledge_edge", select(KnowledgeEdge).where(KnowledgeEdge.subject_id == subject_id)),
        ("knowledge_alias", select(KnowledgeAlias).where(KnowledgeAlias.node_id.in_(knowledge_node_ids))),  # type: ignore[union-attr]
        (
            "teaching_unit_membership",
            select(TeachingUnitMembership).where(TeachingUnitMembership.unit_id.in_(teaching_unit_ids)),  # type: ignore[union-attr]
        ),
        (
            "curriculum_unit_link",
            select(CurriculumUnitLink).where(CurriculumUnitLink.curriculum_version_id.in_(curriculum_version_ids)),  # type: ignore[union-attr]
        ),
        (
            "curriculum_dependency",
            select(CurriculumDependency).where(
                CurriculumDependency.curriculum_version_id.in_(curriculum_version_ids)  # type: ignore[union-attr]
            ),
        ),
        (
            "curriculum_tree_node",
            select(CurriculumTreeNode).where(CurriculumTreeNode.curriculum_version_id.in_(curriculum_version_ids)),  # type: ignore[union-attr]
        ),
        ("curriculum_version", select(CurriculumVersion).where(CurriculumVersion.subject_id == subject_id)),
        ("knowledge_node", select(KnowledgeNode).where(KnowledgeNode.subject_id == subject_id)),
        ("teaching_unit", select(TeachingUnit).where(TeachingUnit.subject_id == subject_id)),
        ("knowledge_document", select(KnowledgeDocument).where(KnowledgeDocument.subject_id == subject_id)),
        ("retrieval_chunk", select(RetrievalChunk).where(RetrievalChunk.subject_id == subject_id)),
    ]

    counts: dict[str, int] = {}
    for key, stmt in deletion_queries:
        rows = list(session.exec(stmt).all())
        counts[key] = len(rows)
        for row in rows:
            session.delete(row)
    session.commit()

    clear_docgen_staging(subject)
    clear_published_knowledge_docs_files(subject)
    knowledge_dir = build_knowledge_markdown_dir(subject)
    for extra_file in ("manifest.json", ".build.lock"):
        (knowledge_dir / extra_file).unlink(missing_ok=True)
    build_dir = knowledge_dir / "_build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)

    return counts


__all__ = [
    "clear_subject_knowledge",
    "get_current_curriculum_snapshot",
    "get_current_prereq_dag",
    "get_current_theme_tree",
    "get_teaching_unit_detail",
    "get_teaching_units",
    "manage_taxonomy_anchors",
]
