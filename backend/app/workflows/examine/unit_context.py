"""Unit exam context builder and batch DB loaders."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import (
    KnowledgeUnit,
    TeachingUnit,
    UserKnowledgeState,
    exam_mode_value,
)
from app.repositories import profile_repo
from app.repositories.knowledge import curriculum_repo, knowledge_unit_repo
from app.workflows.examine.context_helpers import (
    _extract_doc_excerpt,
    _format_mastery,
    _parse_json_list,
    read_knowledge_doc_text,
    truncate_text,
)
from app.workflows.examine.style_profile import (
    ExamStyleProfile,
    build_exam_style_profile,
)


@dataclass(frozen=True)
class NodeExamContext:
    node_id: int
    node_name: str
    summary: str
    body: str
    role: str
    coverage_weight: float
    mastery_score: float | None = None
    is_weak: bool = False

    @property
    def content(self) -> str:
        return "\n".join(part for part in [self.summary.strip(), self.body.strip()] if part)


@dataclass(frozen=True)
class UnitExamContext:
    subject: str
    unit_id: int
    unit_name: str
    unit_summary: str
    unit_body: str
    learning_objectives: list[str]
    doc_excerpt: str
    node_contexts: list[NodeExamContext]
    unit_mastery_score: float | None
    recent_mistakes: list[dict[str, str]]
    weak_node_names: list[str]
    style_profile: ExamStyleProfile
    exam_mode: str
    preferred_question_types: list[str]
    requested_question_count: int
    user_prompt: str | None = None
    focus_prompt: str | None = None

    def prompt_block(self) -> str:
        objective_lines = [f"- {item}" for item in self.learning_objectives[:5]]
        node_lines = [
            (
                f"- {item.node_name} | role={item.role} | mastery={_format_mastery(item.mastery_score)} | "
                f"weak={'yes' if item.is_weak else 'no'}\n"
                f"  {truncate_text(item.content, max_chars=320)}"
            )
            for item in self.node_contexts[:6]
        ]
        mistake_lines = [
            f"- Wrong before: {truncate_text(item.get('question_stem', ''), max_chars=100)}"
            for item in self.recent_mistakes[:3]
        ]
        parts = [
            f"Subject: {self.subject}",
            f"Unit: {self.unit_name}",
            f"Unit mastery: {_format_mastery(self.unit_mastery_score)}",
            f"Exam mode: {self.exam_mode}",
            f"Preferred question types: {', '.join(self.preferred_question_types) or 'auto'}",
        ]
        if self.learning_objectives:
            parts.append("Learning objectives:\n" + "\n".join(objective_lines))
        if self.unit_summary.strip():
            parts.append("Unit summary:\n" + truncate_text(self.unit_summary, max_chars=500))
        if self.unit_body.strip():
            parts.append("Unit body hints:\n" + truncate_text(self.unit_body, max_chars=650))
        if self.doc_excerpt.strip():
            parts.append("Knowledge document excerpt:\n" + truncate_text(self.doc_excerpt, max_chars=900))
        if node_lines:
            parts.append("Knowledge graph anchors:\n" + "\n".join(node_lines))
        if self.weak_node_names:
            parts.append(f"Weak nodes: {', '.join(self.weak_node_names[:8])}")
        if mistake_lines:
            parts.append("Recent mistakes:\n" + "\n".join(mistake_lines))
        style_block = self.style_profile.to_prompt_block()
        if style_block:
            parts.append("Paper style profile:\n" + style_block)
        if self.focus_prompt:
            parts.append(f"Focus prompt: {self.focus_prompt}")
        if self.user_prompt:
            parts.append(f"General user prompt: {self.user_prompt}")
        return "\n\n".join(part for part in parts if part.strip())


# 鈹€鈹€ Batch DB loaders 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def _resolve_node_content(session: Session, node_id: int) -> tuple[KnowledgeUnit | None, str, str]:
    resolved = knowledge_unit_repo.get_knowledge_unit_with_current_revision(session, node_id)
    if resolved is None:
        node = session.get(KnowledgeUnit, node_id)
        if node is None:
            return None, "", ""
        return node, node.summary or "", node.body_markdown or node.body or ""

    node, revision = resolved
    summary = revision.summary or node.summary or ""
    body = revision.body or node.body_markdown or node.body or ""
    return node, summary, body


def _load_teaching_units_by_id(
    session: Session,
    *,
    unit_ids: list[int],
) -> dict[int, TeachingUnit]:
    unique_ids = sorted({int(unit_id) for unit_id in unit_ids if int(unit_id) > 0})
    if not unique_ids:
        return {}

    rows = list(session.exec(select(TeachingUnit).where(TeachingUnit.id.in_(unique_ids))).all())
    return {int(unit.id): unit for unit in rows if unit.id is not None}


def _load_unit_memberships(
    units: list[TeachingUnit],
) -> dict[int, list[tuple[int, str, float]]]:
    memberships_by_unit: dict[int, list[tuple[int, str, float]]] = {}
    for unit in units:
        if unit.id is None:
            continue

        memberships: list[tuple[int, str, float]] = []
        for item in _parse_json_list(unit.member_knowledge_unit_refs_json):
            if not isinstance(item, dict):
                continue
            raw_node_id = item.get("knowledge_unit_id")
            if not isinstance(raw_node_id, int) or raw_node_id <= 0:
                continue
            memberships.append(
                (
                    raw_node_id,
                    str(item.get("role", "primary")),
                    float(item.get("score", 0.0) or 0.0),
                )
            )
        memberships_by_unit[int(unit.id)] = memberships
    return memberships_by_unit


def _load_knowledge_units_by_id(
    session: Session,
    *,
    node_ids: list[int],
) -> dict[int, KnowledgeUnit]:
    unique_ids = sorted({int(node_id) for node_id in node_ids if int(node_id) > 0})
    if not unique_ids:
        return {}

    rows = list(session.exec(select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unique_ids))).all())
    return {int(node.id): node for node in rows if node.id is not None}


def _load_node_content_map(
    session: Session,
    *,
    node_ids: list[int],
) -> dict[int, tuple[str, str]]:
    content_by_id: dict[int, tuple[str, str]] = {}
    for node_id in sorted({int(item) for item in node_ids if int(item) > 0}):
        _, summary, body = _resolve_node_content(session, node_id)
        content_by_id[node_id] = (summary, body)
    return content_by_id


def _load_unit_state_map(
    session: Session,
    *,
    user_id: str,
    subject: str,
    unit_ids: list[int],
) -> dict[int, UserKnowledgeState]:
    unique_ids = sorted({int(unit_id) for unit_id in unit_ids if int(unit_id) > 0})
    if not unique_ids:
        return {}

    rows = list(
        session.exec(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.subject == subject,
                UserKnowledgeState.teaching_unit_id.in_(unique_ids),
                UserKnowledgeState.knowledge_unit_id.is_(None),
            )
        ).all()
    )
    return {
        int(state.teaching_unit_id): state
        for state in rows
        if state.teaching_unit_id is not None
    }


def _load_node_state_map(
    session: Session,
    *,
    user_id: str,
    subject: str,
    node_ids: list[int],
) -> dict[int, UserKnowledgeState]:
    unique_ids = sorted({int(node_id) for node_id in node_ids if int(node_id) > 0})
    if not unique_ids:
        return {}

    rows = list(
        session.exec(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.subject == subject,
                UserKnowledgeState.knowledge_unit_id.in_(unique_ids),
                UserKnowledgeState.teaching_unit_id.is_(None),
            )
        ).all()
    )
    return {
        int(state.knowledge_unit_id): state
        for state in rows
        if state.knowledge_unit_id is not None
    }


def _build_node_contexts_for_unit(
    *,
    unit_id: int,
    memberships_by_unit: dict[int, list[tuple[int, str, float]]],
    node_by_id: dict[int, KnowledgeUnit],
    node_content_by_id: dict[int, tuple[str, str]],
    node_state_by_id: dict[int, UserKnowledgeState],
    weak_node_ids: set[int],
) -> list[NodeExamContext]:
    contexts: list[NodeExamContext] = []
    for node_id, role, score in memberships_by_unit.get(unit_id, []):
        node = node_by_id.get(node_id)
        if node is None:
            continue

        mastery_state = node_state_by_id.get(node_id)
        summary, body = node_content_by_id.get(
            node_id,
            (node.summary or "", node.body_markdown or node.body or ""),
        )
        contexts.append(
            NodeExamContext(
                node_id=node_id,
                node_name=node.canonical_name,
                summary=summary,
                body=body,
                role=role,
                coverage_weight=score or 1.0,
                mastery_score=(mastery_state.mastery_score if mastery_state is not None else None),
                is_weak=node_id in weak_node_ids,
            )
        )
    return contexts


def build_unit_exam_contexts(
    session: Session,
    *,
    subject: str,
    user_id: str,
    unit_ids: list[int],
    questions_per_unit: int,
    exam_mode: str,
    preferred_question_types: list[str] | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    style_profile: ExamStyleProfile | None = None,
) -> list[UnitExamContext]:
    mode = exam_mode_value(exam_mode)
    doc_text = read_knowledge_doc_text(subject)
    style = style_profile or build_exam_style_profile(
        session,
        subject=subject,
        user_id=user_id,
        focus_prompt=focus_prompt,
        user_prompt=user_prompt,
        exam_mode=mode,
    )
    weak_node_ids = {
        int(state.knowledge_unit_id)
        for state in profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            threshold=0.8,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }
    units_by_id = _load_teaching_units_by_id(session, unit_ids=unit_ids)
    ordered_units = [
        units_by_id[int(unit_id)]
        for unit_id in unit_ids
        if int(unit_id) in units_by_id and units_by_id[int(unit_id)].id is not None
    ]
    memberships_by_unit = _load_unit_memberships(ordered_units)
    all_node_ids = [
        node_id
        for memberships in memberships_by_unit.values()
        for node_id, _, _ in memberships
    ]
    node_by_id = _load_knowledge_units_by_id(session, node_ids=all_node_ids)
    node_content_by_id = _load_node_content_map(session, node_ids=all_node_ids)
    unit_state_by_id = _load_unit_state_map(
        session,
        user_id=user_id,
        subject=subject,
        unit_ids=[int(unit.id) for unit in ordered_units if unit.id is not None],
    )
    node_state_by_id = _load_node_state_map(
        session,
        user_id=user_id,
        subject=subject,
        node_ids=all_node_ids,
    )

    contexts: list[UnitExamContext] = []
    for unit in ordered_units:
        if unit.id is None:
            continue

        node_contexts = _build_node_contexts_for_unit(
            unit_id=int(unit.id),
            memberships_by_unit=memberships_by_unit,
            node_by_id=node_by_id,
            node_content_by_id=node_content_by_id,
            node_state_by_id=node_state_by_id,
            weak_node_ids=weak_node_ids,
        )
        learning_objectives = [
            str(item).strip()
            for item in _parse_json_list(unit.learning_objectives_json)
            if str(item).strip()
        ]
        unit_state = unit_state_by_id.get(int(unit.id))
        search_terms = [unit.canonical_name, unit.title] + [item.node_name for item in node_contexts]
        doc_excerpt = _extract_doc_excerpt(doc_text, search_terms)
        weak_node_names = [item.node_name for item in node_contexts if item.is_weak]
        recent_mistakes = profile_repo.list_recent_wrong_attempt_summaries(
            session,
            user_id=user_id,
            subject=subject,
            teaching_unit_id=int(unit.id),
            knowledge_unit_ids=[item.node_id for item in node_contexts],
            limit=3,
        )
        contexts.append(
            UnitExamContext(
                subject=subject,
                unit_id=int(unit.id),
                unit_name=unit.canonical_name,
                unit_summary=unit.summary,
                unit_body=unit.body_markdown,
                learning_objectives=learning_objectives,
                doc_excerpt=doc_excerpt,
                node_contexts=node_contexts,
                unit_mastery_score=(unit_state.mastery_score if unit_state is not None else None),
                recent_mistakes=recent_mistakes,
                weak_node_names=weak_node_names,
                style_profile=style,
                exam_mode=mode,
                preferred_question_types=list(preferred_question_types or style.preferred_question_types),
                requested_question_count=max(1, int(questions_per_unit)),
                user_prompt=(user_prompt or "").strip() or None,
                focus_prompt=(focus_prompt or "").strip() or None,
            )
        )
    return contexts


__all__ = [
    "NodeExamContext",
    "UnitExamContext",
    "build_unit_exam_contexts",
]
