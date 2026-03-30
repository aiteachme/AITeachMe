"""Theme tree derivation built on the compressed curriculum schema."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models.curriculum import (
    TaxonomyAnchor,
    TeachingUnit,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitTreeMembership,
)
from app.models.knowledge_graph import KnowledgeNode
from app.repositories import curriculum_repo, kg_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.prompts import (
    SYSTEM_PROMPT_KG_THEME_TREE,
    USER_PROMPT_KG_THEME_TREE,
)

logger = structlog.get_logger(__name__)

_WORD_RE = re.compile(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}")
_STABILITY_THRESHOLD = 0.08
_MEMBERSHIP_THRESHOLD = 0.15


@dataclass(slots=True)
class AnchorSkeleton:
    anchor: TaxonomyAnchor
    children: list["AnchorSkeleton"] = field(default_factory=list)


@dataclass(slots=True)
class UnitInfo:
    unit_id: int
    title: str
    summary: str
    taxonomy_hints: list[str] = field(default_factory=list)


class ChapterSpec(BaseModel):
    title: str = PydanticField(description="章节标题")
    order: int = PydanticField(description="章节顺序")


class ModuleSpec(BaseModel):
    title: str = PydanticField(description="模块标题")
    order: int = PydanticField(description="模块顺序")
    chapters: list[ChapterSpec] = PydanticField(description="模块下章节")


class ThemeTreeStructure(BaseModel):
    modules: list[ModuleSpec] = PydanticField(description="主题树结构")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(text)}


def _load_json_list(raw: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _text_overlap_score(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def _load_unit_infos(session: Session, units: list[TeachingUnit]) -> dict[int, UnitInfo]:
    member_node_ids_by_unit: dict[int, list[int]] = {}
    all_member_node_ids: set[int] = set()
    for unit in units:
        unit_id = unit.id
        if unit_id is None:
            continue
        member_node_ids: list[int] = []
        for item in _load_json_list(unit.member_node_refs_json):
            raw_node_id = item.get("knowledge_node_id")
            if isinstance(raw_node_id, int):
                member_node_ids.append(raw_node_id)
        member_node_ids_by_unit[unit_id] = member_node_ids
        all_member_node_ids.update(member_node_ids)

    taxonomy_hints_by_node_id: dict[int, list[str]] = {}
    if all_member_node_ids:
        nodes = list(
            session.exec(
                select(KnowledgeNode).where(KnowledgeNode.id.in_(all_member_node_ids))
            ).all()
        )
        for node in nodes:
            if node.id is None:
                continue
            hints = [
                str(item.get("quote_text", "")).strip()
                for item in _load_json_list(node.evidence_refs_json)
                if bool(item.get("is_active", True))
                and str(item.get("evidence_role", "")) == "taxonomy_hint"
                and str(item.get("quote_text", "")).strip()
            ]
            if hints:
                taxonomy_hints_by_node_id[node.id] = hints

    infos: dict[int, UnitInfo] = {}
    for unit in units:
        unit_id = unit.id
        if unit_id is None:
            continue
        taxonomy_hints: list[str] = []
        for node_id in member_node_ids_by_unit.get(unit_id, []):
            taxonomy_hints.extend(taxonomy_hints_by_node_id.get(node_id, []))
        infos[unit_id] = UnitInfo(
            unit_id=unit_id,
            title=unit.canonical_name,
            summary=unit.summary,
            taxonomy_hints=list(dict.fromkeys(taxonomy_hints)),
        )
    return infos


async def _auto_generate_anchors(
    session: Session,
    subject: str,
    units: list[TeachingUnit],
) -> None:
    if not units:
        curriculum_repo.get_uncategorized_anchor(session, subject)
        return

    unit_summaries = [
        {
            "name": unit.canonical_name,
            "summary": unit.summary or unit.canonical_name,
        }
        for unit in units[:80]
    ]
    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_THEME_TREE},
        {
            "role": USER,
            "content": populate_prompt(
                USER_PROMPT_KG_THEME_TREE,
                subject=subject,
                units=unit_summaries,
            ),
        },
    ]

    try:
        structure = await acompletion_structured(
            response_model=ThemeTreeStructure,
            messages=messages,
        )
    except Exception:
        logger.warning("theme_tree_auto_generate_failed", subject=subject, exc_info=True)
        curriculum_repo.get_uncategorized_anchor(session, subject)
        return

    created_any = False
    for module in sorted(structure.modules, key=lambda item: item.order):
        module_anchor = curriculum_repo.create_taxonomy_anchor(
            session,
            TaxonomyAnchor(
                subject=subject,
                anchor_type="graph_discovered",
                title=module.title,
                normalized_title=_normalize_text(module.title),
                parent_anchor_id=None,
                order_index=module.order,
                confidence=0.8,
                is_system=False,
                status="active",
            ),
            auto_commit=False,
        )
        created_any = True
        for chapter in sorted(module.chapters, key=lambda item: item.order):
            curriculum_repo.create_taxonomy_anchor(
                session,
                TaxonomyAnchor(
                    subject=subject,
                    anchor_type="graph_discovered",
                    title=chapter.title,
                    normalized_title=_normalize_text(chapter.title),
                    parent_anchor_id=module_anchor.id,
                    order_index=chapter.order,
                    confidence=0.8,
                    is_system=False,
                    status="active",
                ),
                auto_commit=False,
            )

    if not created_any:
        curriculum_repo.get_uncategorized_anchor(session, subject)
    else:
        session.commit()


def _build_anchor_skeleton(session: Session, subject: str) -> list[AnchorSkeleton]:
    anchors = curriculum_repo.list_anchors_by_subject(session, subject)
    if not anchors:
        curriculum_repo.get_uncategorized_anchor(session, subject)
        anchors = curriculum_repo.list_anchors_by_subject(session, subject)

    children_by_parent: dict[int | None, list[TaxonomyAnchor]] = {}
    for anchor in anchors:
        children_by_parent.setdefault(anchor.parent_anchor_id, []).append(anchor)
    for children in children_by_parent.values():
        children.sort(key=lambda anchor: (anchor.order_index, anchor.title))

    def _build(parent_id: int | None) -> list[AnchorSkeleton]:
        return [
            AnchorSkeleton(anchor=anchor, children=_build(anchor.id))
            for anchor in children_by_parent.get(parent_id, [])
        ]

    return _build(None)


def _materialize_skeleton(
    session: Session,
    subject: str,
    tree_version_id: int,
    skeletons: list[AnchorSkeleton],
    parent_tree_node_id: int | None = None,
) -> list[tuple[int, int | None, list[str]]]:
    leaf_nodes: list[tuple[int, int | None, list[str]]] = []

    def _walk(children: list[AnchorSkeleton], parent_id: int | None, path: list[str]) -> None:
        for order_index, skeleton in enumerate(children):
            anchor = skeleton.anchor
            is_leaf = not skeleton.children
            node = curriculum_repo.create_theme_tree_node(
                session,
                ThemeTreeNode(
                    subject=subject,
                    tree_version_id=tree_version_id,
                    anchor_id=anchor.id,
                    parent_tree_node_id=parent_id,
                    title=anchor.title,
                    node_type=("theme" if is_leaf else ("chapter" if parent_id is None else "section")),
                    order_index=order_index,
                    summary="",
                ),
                auto_commit=False,
            )
            current_path = [*path, anchor.title]
            if is_leaf and node.id is not None:
                leaf_nodes.append((node.id, anchor.id, current_path))
                continue
            _walk(skeleton.children, node.id, current_path)

    _walk(skeletons, parent_tree_node_id, [])
    return leaf_nodes


def _ensure_uncategorized_node(
    session: Session,
    subject: str,
    tree_version_id: int,
    leaf_nodes: list[tuple[int, int | None, list[str]]],
) -> int:
    for node_id, _anchor_id, path in leaf_nodes:
        if path and path[-1] == "未归类":
            return node_id

    node = curriculum_repo.create_theme_tree_node(
        session,
        ThemeTreeNode(
            subject=subject,
            tree_version_id=tree_version_id,
            anchor_id=None,
            parent_tree_node_id=None,
            title="未归类",
            node_type="uncategorized",
            order_index=9999,
            summary="",
        ),
        auto_commit=False,
    )
    leaf_nodes.append((node.id or 0, None, ["未归类"]))
    return node.id or 0


def _get_prev_primary_memberships(
    session: Session,
    prev_tree_version: ThemeTreeVersion | None,
) -> dict[int, int]:
    if prev_tree_version is None or prev_tree_version.id is None:
        return {}
    return {
        membership.teaching_unit_id: membership.tree_node_id
        for membership in curriculum_repo.list_unit_memberships_by_version(session, prev_tree_version.id)
        if membership.membership_role == "primary"
    }


def _get_human_fixed_memberships(
    session: Session,
    prev_tree_version: ThemeTreeVersion | None,
) -> dict[int, int]:
    if prev_tree_version is None or prev_tree_version.id is None:
        return {}

    tree_nodes = curriculum_repo.list_tree_nodes_by_version(session, prev_tree_version.id)
    anchor_by_tree_node_id = {
        node.id: node.anchor_id
        for node in tree_nodes
        if node.id is not None
    }
    return {
        membership.teaching_unit_id: anchor_by_tree_node_id.get(membership.tree_node_id) or 0
        for membership in curriculum_repo.list_unit_memberships_by_version(session, prev_tree_version.id)
        if membership.membership_role == "primary"
        and membership.membership_source == "human_fixed"
        and anchor_by_tree_node_id.get(membership.tree_node_id) is not None
    }


def _score_unit_to_leaf(unit: UnitInfo, path_titles: list[str]) -> float:
    path_text = " ".join(path_titles)
    base = _text_overlap_score(f"{unit.title} {unit.summary}", path_text)
    hint_score = max((_text_overlap_score(hint, path_text) for hint in unit.taxonomy_hints), default=0.0)
    return base + 0.5 * hint_score


def _select_leaf_node(
    unit: UnitInfo,
    leaf_nodes: list[tuple[int, int | None, list[str]]],
    prev_primary_node_id: int | None,
    human_fixed_node_id: int | None,
    uncategorized_node_id: int,
) -> tuple[int, str, float]:
    if human_fixed_node_id is not None:
        return human_fixed_node_id, "human_fixed", 1.0

    scored = [
        (node_id, _score_unit_to_leaf(unit, path_titles))
        for node_id, _anchor_id, path_titles in leaf_nodes
        if node_id != uncategorized_node_id
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored:
        return uncategorized_node_id, "auto", 0.0

    best_node_id, best_score = scored[0]
    if best_score < _MEMBERSHIP_THRESHOLD:
        return uncategorized_node_id, "auto", 0.0

    if prev_primary_node_id is not None and len(scored) >= 2:
        second_score = scored[1][1]
        if best_score - second_score < _STABILITY_THRESHOLD:
            for node_id, score in scored:
                if node_id == prev_primary_node_id:
                    return node_id, "auto", score

    return best_node_id, "auto", best_score


async def derive_theme_tree(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
    prev_tree_version: ThemeTreeVersion | None = None,
) -> ThemeTreeVersion:
    """Derive a new draft theme tree from anchors and teaching units."""

    del impact_set, curriculum_job_id

    skeletons = _build_anchor_skeleton(session, subject)
    has_real_anchor = any(skeleton.anchor.anchor_type != "system" for skeleton in skeletons)
    if not has_real_anchor:
        active_units, _ = curriculum_repo.list_units_by_subject(session, subject, status="active", limit=10000, offset=0)
        pending_units, _ = curriculum_repo.list_units_by_subject(session, subject, status="pending", limit=10000, offset=0)
        await _auto_generate_anchors(session, subject, [*active_units, *pending_units])
        skeletons = _build_anchor_skeleton(session, subject)

    if prev_tree_version is None:
        prev_tree_version = curriculum_repo.get_current_theme_tree_version(session, subject)
    prev_version_no = prev_tree_version.version_no if prev_tree_version is not None else 0
    tree_version = curriculum_repo.create_theme_tree_version_with_optimistic_lock(
        session,
        subject,
        expected_prev_version_no=prev_version_no,
    )
    leaf_nodes = _materialize_skeleton(session, subject, tree_version.id or 0, skeletons)
    uncategorized_node_id = _ensure_uncategorized_node(session, subject, tree_version.id or 0, leaf_nodes)

    active_units, _ = curriculum_repo.list_units_by_subject(session, subject, status="active", limit=10000, offset=0)
    pending_units, _ = curriculum_repo.list_units_by_subject(session, subject, status="pending", limit=10000, offset=0)
    all_units = [*active_units, *pending_units]
    if not all_units:
        session.commit()
        return tree_version

    unit_infos = _load_unit_infos(session, all_units)
    prev_primary_memberships = _get_prev_primary_memberships(session, prev_tree_version)
    human_fixed_by_anchor = _get_human_fixed_memberships(session, prev_tree_version)
    anchor_to_new_node = {
        anchor_id: node_id
        for node_id, anchor_id, _path_titles in leaf_nodes
        if anchor_id is not None
    }

    for unit_id, unit in unit_infos.items():
        prev_primary_node_id = prev_primary_memberships.get(unit_id)
        human_fixed_node_id = None
        human_fixed_anchor_id = human_fixed_by_anchor.get(unit_id)
        if human_fixed_anchor_id is not None:
            human_fixed_node_id = anchor_to_new_node.get(human_fixed_anchor_id)

        target_node_id, source, score = _select_leaf_node(
            unit,
            leaf_nodes,
            prev_primary_node_id=prev_primary_node_id,
            human_fixed_node_id=human_fixed_node_id,
            uncategorized_node_id=uncategorized_node_id,
        )
        curriculum_repo.create_unit_tree_membership(
            session,
            UnitTreeMembership(
                tree_version_id=tree_version.id or 0,
                tree_node_id=target_node_id,
                teaching_unit_id=unit_id,
                membership_role="primary",
                membership_source=source,
                score=score,
            ),
            auto_commit=False,
        )

    session.commit()
    logger.info(
        "derive_theme_tree_complete",
        subject=subject,
        tree_version_id=tree_version.id,
        version_no=tree_version.version_no,
        mounted_units=len(unit_infos),
    )
    return tree_version


__all__ = ["derive_theme_tree"]
