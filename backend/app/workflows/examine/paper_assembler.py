"""Paper assembly for exam generation."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import floor

import structlog
from sqlmodel import Session, select

from app.core.exceptions import NoPublishedCurriculumSnapshotError
from app.models import (
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    QuestionTemplate,
    QuestionType,
    ThemeTreeNode,
    is_paper_exam_mode,
    is_web_practice_mode,
    normalize_exam_mode,
)
from app.models.curriculum import CurriculumSnapshot
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow
from app.workflows.examine.context import ExamStyleProfile

logger = structlog.get_logger()

_PAPER_EXAM_SECTION_ORDER = [
    QuestionType.SINGLE_CHOICE.value,
    QuestionType.FILL_BLANK.value,
    QuestionType.SHORT_ANSWER.value,
]
_PAPER_EXAM_SECTION_LABELS = {
    QuestionType.SINGLE_CHOICE.value: "一、单项选择题",
    QuestionType.FILL_BLANK.value: "二、填空题",
    QuestionType.SHORT_ANSWER.value: "三、简答题",
}


@dataclass
class _Selection:
    template: QuestionTemplate
    reason: str
    source_state_id: int | None = None


def _resolve_answer_index(options: list[str], answer: str) -> int:
    if answer in options:
        return options.index(answer)

    normalized_options = [item.strip().lower() for item in options]
    normalized_answer = answer.strip().lower()
    if normalized_answer in normalized_options:
        return normalized_options.index(normalized_answer)

    normalized_label = normalized_answer.upper()
    if len(normalized_label) == 1 and "A" <= normalized_label <= "Z":
        index = ord(normalized_label) - ord("A")
        if 0 <= index < len(options):
            return index

    raise ValueError("answer does not map to options")


def shuffle_single_choice_options(
    options_json: str,
    answer: str,
    *,
    rng: random.Random | None = None,
) -> tuple[str, str]:
    decoded = json.loads(options_json)
    if not isinstance(decoded, list) or len(decoded) < 2:
        raise ValueError("single choice options must contain at least 2 items")

    options = [str(item) for item in decoded]
    answer_index = _resolve_answer_index(options, answer)
    answer_value = options[answer_index]

    shuffled = list(options)
    (rng or random).shuffle(shuffled)
    return json.dumps(shuffled, ensure_ascii=False), answer_value


def _normalize_exam_mode(exam_mode: ExamMode | str) -> str:
    return normalize_exam_mode(exam_mode)


def _is_placeholder_template(template: QuestionTemplate) -> bool:
    stem = (template.stem or "").strip()
    if not stem:
        return True
    bad_markers = ["???", "�", "占位", "placeholder"]
    return any(marker in stem.lower() for marker in [item.lower() for item in bad_markers])


def _build_unit_template_pool(
    session: Session,
    *,
    subject: str,
    unit_filter: set[int] | None = None,
    question_type_filter: set[str] | None = None,
    preferred_difficulty: str | None = None,
    excluded_template_ids: set[int] | None = None,
) -> dict[int, list[QuestionTemplate]]:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.status == "active",
    )
    if unit_filter:
        stmt = stmt.where(QuestionTemplate.teaching_unit_id.in_(unit_filter))
    if question_type_filter:
        stmt = stmt.where(QuestionTemplate.question_type.in_(question_type_filter))

    rows = list(session.exec(stmt.order_by(QuestionTemplate.id)).all())
    excluded = excluded_template_ids or set()
    pool: dict[int, list[QuestionTemplate]] = defaultdict(list)
    for item in rows:
        if item.id is None or item.id in excluded or _is_placeholder_template(item):
            continue
        pool[item.teaching_unit_id].append(item)
    if preferred_difficulty in {"easy", "medium", "hard"}:
        for templates in pool.values():
            templates.sort(
                key=lambda item: (
                    0 if item.difficulty == preferred_difficulty else 1,
                    item.id or 0,
                )
            )
    return pool


def _weighted_split(total: int, ratios: list[float]) -> list[int]:
    raw = [total * ratio for ratio in ratios]
    base = [floor(value) for value in raw]
    remain = total - sum(base)
    remainders = sorted(
        enumerate([value - floor(value) for value in raw]),
        key=lambda item: item[1],
        reverse=True,
    )
    for idx, _ in remainders[:remain]:
        base[idx] += 1
    return base


def _select_round_robin(
    *,
    unit_to_templates: dict[int, list[QuestionTemplate]],
    limit: int,
    used_template_ids: set[int],
    reason: str,
    source_state_by_unit: dict[int, int] | None = None,
) -> list[_Selection]:
    if limit <= 0:
        return []

    unit_ids = sorted(unit_to_templates.keys())
    cursors = {unit_id: 0 for unit_id in unit_ids}
    selections: list[_Selection] = []
    made_progress = True

    while len(selections) < limit and made_progress:
        made_progress = False
        for unit_id in unit_ids:
            templates = unit_to_templates.get(unit_id, [])
            cursor = cursors[unit_id]
            while cursor < len(templates):
                template = templates[cursor]
                cursor += 1
                if template.id is None or template.id in used_template_ids:
                    continue
                used_template_ids.add(template.id)
                selections.append(
                    _Selection(
                        template=template,
                        reason=reason,
                        source_state_id=(source_state_by_unit or {}).get(unit_id),
                    )
                )
                made_progress = True
                break
            cursors[unit_id] = cursor
            if len(selections) >= limit:
                break
    return selections


def _resolve_practice_units(
    session: Session,
    *,
    theme_tree_node_id: int | None,
    teaching_unit_ids: list[int] | None,
) -> set[int]:
    if teaching_unit_ids:
        return {int(item) for item in teaching_unit_ids}
    if theme_tree_node_id is None:
        return set()
    return set(exams_repo.resolve_teaching_units_from_theme_tree_node(session, theme_tree_node_id))


def _build_curriculum_unit_allocation(
    session: Session,
    *,
    snapshot: CurriculumSnapshot,
    num_questions: int,
) -> dict[int, int]:
    if snapshot.id is None:
        return {}

    tree_nodes = list(
        session.exec(
            select(ThemeTreeNode).where(ThemeTreeNode.tree_version_id == snapshot.id)
        ).all()
    )
    if not tree_nodes:
        return {}

    unit_weight: dict[int, int] = defaultdict(int)
    for node in tree_nodes:
        for unit_id in exams_repo.resolve_teaching_units_from_theme_tree_node(session, node.id or 0):
            unit_weight[int(unit_id)] += 1

    total_weight = sum(unit_weight.values())
    if total_weight <= 0:
        return {}

    allocation: dict[int, int] = {}
    remaining = num_questions
    unit_items = sorted(unit_weight.items(), key=lambda item: (-item[1], item[0]))
    for index, (unit_id, weight) in enumerate(unit_items):
        if index == len(unit_items) - 1:
            take = max(0, remaining)
        else:
            take = floor(num_questions * (weight / total_weight))
        allocation[unit_id] = take
        remaining -= take

    cursor = 0
    while remaining > 0 and unit_items:
        unit_id = unit_items[cursor % len(unit_items)][0]
        allocation[unit_id] += 1
        remaining -= 1
        cursor += 1
    return allocation


def _build_selection_reason_map(items: list[ExamPaperItem], selections: list[_Selection]) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for created_item, selection in zip(items, selections):
        if created_item.id is None:
            continue
        payload[str(created_item.id)] = {
            "question_template_id": selection.template.id,
            "reason": selection.reason,
            "source_state_id": selection.source_state_id,
            "question_type": selection.template.question_type,
            "teaching_unit_id": selection.template.teaching_unit_id,
        }
    return payload


def _build_paper_exam_section_plan(selections: list[_Selection]) -> tuple[list[dict[str, object]], list[_Selection]]:
    grouped: dict[str, list[_Selection]] = defaultdict(list)
    for selection in selections:
        grouped[selection.template.question_type].append(selection)

    ordered: list[_Selection] = []
    section_plan: list[dict[str, object]] = []
    cursor = 1
    for question_type in _PAPER_EXAM_SECTION_ORDER:
        section_items = grouped.get(question_type, [])
        if not section_items:
            continue
        section_plan.append(
            {
                "question_type": question_type,
                "label": _PAPER_EXAM_SECTION_LABELS.get(question_type, question_type),
                "start_order": cursor,
                "count": len(section_items),
            }
        )
        cursor += len(section_items)
        ordered.extend(section_items)

    leftovers = [
        selection
        for selection in selections
        if selection.template.question_type not in _PAPER_EXAM_SECTION_ORDER
    ]
    if leftovers:
        section_plan.append(
            {
                "question_type": "other",
                "label": "四、其他题型",
                "start_order": cursor,
                "count": len(leftovers),
            }
        )
        ordered.extend(leftovers)

    return section_plan, ordered if ordered else selections


def _style_metadata(style_profile: ExamStyleProfile | None) -> dict[str, object]:
    return style_profile.to_metadata() if style_profile is not None else {}


def _normalize_preferred_difficulty(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in {"easy", "medium", "hard", "mixed"}:
        return normalized
    return None


def assemble_paper(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_mode: ExamMode | str,
    num_questions: int,
    theme_tree_node_id: int | None = None,
    teaching_unit_ids: list[int] | None = None,
    preferred_question_types: list[str] | None = None,
    preferred_difficulty: str | None = None,
    style_profile: ExamStyleProfile | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    sample_file_uids: list[str] | None = None,
    as_of: datetime | None = None,
) -> ExamPaper:
    mode = _normalize_exam_mode(exam_mode)
    now = as_of or utcnow()
    question_type_filter = {item for item in (preferred_question_types or []) if item}
    resolved_difficulty = _normalize_preferred_difficulty(preferred_difficulty)

    curriculum_version = exams_repo.get_published_curriculum_version(session, subject)
    if curriculum_version is None or curriculum_version.id is None:
        raise NoPublishedCurriculumSnapshotError(subject)

    excluded_ids = set(
        exams_repo.list_recent_exam_template_ids_for_user(
            session,
            user_id,
            subject,
            limit=3,
        )
    )

    used_template_ids: set[int] = set()
    selections: list[_Selection] = []
    context_payload: dict[str, object] = {
        "selection_reasons": {},
        "target_theme_tree_node_id": theme_tree_node_id,
        "weakness_state_ids": [],
        "review_task_ids": [],
        "excluded_template_ids": sorted(excluded_ids),
        "sample_file_uids": list(sample_file_uids or []),
        "user_prompt": user_prompt,
        "focus_prompt": focus_prompt,
        "style_profile": _style_metadata(style_profile),
        "requested_difficulty": resolved_difficulty,
        "resolved_teaching_unit_ids": [],
        "paper_title": (
            style_profile.title_hint
            if style_profile and style_profile.title_hint
            else (f"{subject} 正式考卷" if is_paper_exam_mode(mode) else f"{subject} 在线测验")
        ),
        "section_plan": [],
    }

    if is_web_practice_mode(mode):
        resolved_units: set[int] = set()
        unit_scope = _resolve_practice_units(
            session,
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids=teaching_unit_ids,
        )
        if unit_scope:
            resolved_units.update(unit_scope)
            selections.extend(
                _select_round_robin(
                    unit_to_templates=_build_unit_template_pool(
                        session,
                        subject=subject,
                        unit_filter=unit_scope,
                        question_type_filter=question_type_filter or None,
                        preferred_difficulty=resolved_difficulty,
                        excluded_template_ids=excluded_ids,
                    ),
                    limit=num_questions,
                    used_template_ids=used_template_ids,
                    reason="web_practice_scope",
                )
            )

        due_states = profile_repo.list_due_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            as_of=now,
            target_kind="unit",
        )
        due_units = {
            int(state.teaching_unit_id)
            for state in due_states
            if state.teaching_unit_id is not None
        }
        source_state_by_due_unit = {
            int(state.teaching_unit_id): state.id
            for state in due_states
            if state.id is not None and state.teaching_unit_id is not None
        }
        if len(selections) < num_questions and due_units:
            resolved_units.update(due_units)
            selections.extend(
                _select_round_robin(
                    unit_to_templates=_build_unit_template_pool(
                        session,
                        subject=subject,
                        unit_filter=due_units,
                        question_type_filter=question_type_filter or None,
                        preferred_difficulty=resolved_difficulty,
                        excluded_template_ids=excluded_ids,
                    ),
                    limit=(num_questions - len(selections)),
                    used_template_ids=used_template_ids,
                    reason="review_due",
                    source_state_by_unit=source_state_by_due_unit,
                )
            )

        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            threshold=0.8,
            target_kind="unit",
        )
        weak_units = {
            int(state.teaching_unit_id)
            for state in weak_states
            if state.teaching_unit_id is not None
        }
        source_state_by_unit = {
            int(state.teaching_unit_id): state.id
            for state in weak_states
            if state.id is not None and state.teaching_unit_id is not None
        }
        prereq_units: set[int] = set()
        for unit_id in weak_units:
            prereq_units.update(exams_repo.list_prereq_units(session, unit_id))
        remaining_after_due = max(0, num_questions - len(selections))
        if remaining_after_due > 0 and (weak_units or prereq_units):
            weak_count, prereq_count = _weighted_split(remaining_after_due, [0.75, 0.25])
            selections.extend(
                _select_round_robin(
                    unit_to_templates=_build_unit_template_pool(
                        session,
                        subject=subject,
                        unit_filter=weak_units or None,
                        question_type_filter=question_type_filter or None,
                        preferred_difficulty=resolved_difficulty,
                        excluded_template_ids=excluded_ids,
                    ),
                    limit=weak_count,
                    used_template_ids=used_template_ids,
                    reason="weakpoint_boost",
                    source_state_by_unit=source_state_by_unit,
                )
            )
            selections.extend(
                _select_round_robin(
                    unit_to_templates=_build_unit_template_pool(
                        session,
                        subject=subject,
                        unit_filter=prereq_units or None,
                        question_type_filter=question_type_filter or None,
                        preferred_difficulty=resolved_difficulty,
                        excluded_template_ids=excluded_ids,
                    ),
                    limit=prereq_count,
                    used_template_ids=used_template_ids,
                    reason="prereq_patch",
                    source_state_by_unit=source_state_by_unit,
                )
            )

        pending_review_tasks = profile_repo.list_pending_reviews(session, user_id=user_id, subject=subject)
        context_payload["review_task_ids"] = [task.id for task in pending_review_tasks if task.id is not None]
        context_payload["weakness_state_ids"] = [state.id for state in weak_states if state.id is not None]
        resolved_units.update(weak_units)
        resolved_units.update(prereq_units)
        context_payload["resolved_teaching_unit_ids"] = sorted(resolved_units)
    elif is_paper_exam_mode(mode):
        allocation = _build_curriculum_unit_allocation(
            session,
            snapshot=curriculum_version,
            num_questions=num_questions,
        )
        pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=set(allocation.keys()) or None,
            question_type_filter=question_type_filter or None,
            preferred_difficulty=resolved_difficulty,
            excluded_template_ids=excluded_ids,
        )
        for unit_id, count in allocation.items():
            if count <= 0:
                continue
            selections.extend(
                _select_round_robin(
                    unit_to_templates={unit_id: pool.get(unit_id, [])},
                    limit=count,
                    used_template_ids=used_template_ids,
                    reason="paper_exam_blueprint",
                )
            )
        context_payload["resolved_teaching_unit_ids"] = sorted(allocation.keys())
    else:
        selections.extend(
            _select_round_robin(
                unit_to_templates=_build_unit_template_pool(
                    session,
                    subject=subject,
                    question_type_filter=question_type_filter or None,
                    preferred_difficulty=resolved_difficulty,
                    excluded_template_ids=excluded_ids,
                ),
                limit=num_questions,
                used_template_ids=used_template_ids,
                reason="web_practice_default",
            )
        )

    if len(selections) < num_questions:
        selections.extend(
            _select_round_robin(
                unit_to_templates=_build_unit_template_pool(
                    session,
                    subject=subject,
                    question_type_filter=question_type_filter or None,
                    preferred_difficulty=resolved_difficulty,
                    excluded_template_ids=excluded_ids,
                ),
                limit=(num_questions - len(selections)),
                used_template_ids=used_template_ids,
                reason="fallback_fill",
            )
        )

    if len(selections) < num_questions and excluded_ids:
        selections.extend(
            _select_round_robin(
                unit_to_templates=_build_unit_template_pool(
                    session,
                    subject=subject,
                    question_type_filter=question_type_filter or None,
                    preferred_difficulty=resolved_difficulty,
                    excluded_template_ids=None,
                ),
                limit=(num_questions - len(selections)),
                used_template_ids=used_template_ids,
                reason="fallback_relaxed_exclusion",
            )
        )

    if len(selections) < num_questions and question_type_filter:
        selections.extend(
            _select_round_robin(
                unit_to_templates=_build_unit_template_pool(
                    session,
                    subject=subject,
                    preferred_difficulty=resolved_difficulty,
                    excluded_template_ids=None,
                ),
                limit=(num_questions - len(selections)),
                used_template_ids=used_template_ids,
                reason="fallback_any_type",
            )
        )

    if not selections:
        raise ValueError("自动组卷失败：当前没有可用题目模板。")

    if is_paper_exam_mode(mode):
        section_plan, selections = _build_paper_exam_section_plan(selections)
        context_payload["section_plan"] = section_plan

    paper = exams_repo.create_exam_paper(
        session,
        ExamPaper(
            subject=subject,
            user_id=user_id,
            exam_mode=mode,
            curriculum_version_id=curriculum_version.id,
            status="draft",
            total_items=0,
            selection_context_json="{}",
            created_at=utcnow(),
            updated_at=utcnow(),
        ),
        auto_commit=False,
    )
    if paper.id is None:
        raise ValueError("ExamPaper.id should not be None after persistence.")

    items_to_create: list[ExamPaperItem] = []
    for item_order, selection in enumerate(selections, start=1):
        template = selection.template
        if template.id is None:
            continue

        options_snapshot = template.options_json
        answer_snapshot = template.answer
        if template.question_type == QuestionType.SINGLE_CHOICE.value and template.options_json:
            try:
                options_snapshot, answer_snapshot = shuffle_single_choice_options(
                    template.options_json,
                    template.answer,
                )
            except Exception:
                logger.warning("paper_assembler_shuffle_failed", template_id=template.id)
                options_snapshot = template.options_json
                answer_snapshot = template.answer

        items_to_create.append(
            ExamPaperItem(
                exam_paper_id=paper.id,
                question_template_id=template.id,
                item_order=item_order,
                stem_snapshot=template.stem,
                options_snapshot_json=options_snapshot,
                answer_snapshot=answer_snapshot,
                explanation_snapshot=template.explanation,
                teaching_unit_id=template.teaching_unit_id,
                node_refs_json=template.node_refs_json or "[]",
                difficulty=template.difficulty,
                question_type=template.question_type,
                score=1.0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )

    created_items = exams_repo.create_exam_paper_items(
        session,
        items_to_create,
        auto_commit=False,
    )
    paper.total_items = len(created_items)
    paper.status = "ready"
    paper.updated_at = utcnow()
    paper.selection_context_json = json.dumps(
        {
            **context_payload,
            "selection_reasons": _build_selection_reason_map(created_items, selections),
        },
        ensure_ascii=False,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)

    logger.info(
        "paper_assembled",
        subject=subject,
        user_id=user_id,
        exam_mode=mode,
        exam_paper_id=paper.id,
        total_items=paper.total_items,
    )
    return paper
