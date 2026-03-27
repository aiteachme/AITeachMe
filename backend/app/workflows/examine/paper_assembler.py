"""组卷器：Phase B 组卷 + 快照。

Reads DB: ``question_template*``, ``curriculum_snapshot``, ``user_knowledge_state``,
``review_task`` and related curriculum memberships.
Writes DB: ``exam_paper`` and ``exam_paper_item``.
Writes FS: none.
Idempotency: each generate call assembles one paper snapshot rather than mutating historical papers
in place.
"""

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
)
from app.models.curriculum import CurriculumSnapshot
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow

logger = structlog.get_logger()


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
    """打乱单选题选项并保持答案语义不变。"""

    decoded = json.loads(options_json)
    if not isinstance(decoded, list):
        raise ValueError("options_json must decode to list")
    if len(decoded) < 2:
        raise ValueError("single choice options must contain at least 2 items")

    options = [str(item) for item in decoded]
    answer_index = _resolve_answer_index(options, answer)
    answer_value = options[answer_index]

    shuffled = list(options)
    (rng or random).shuffle(shuffled)

    return json.dumps(shuffled, ensure_ascii=False), answer_value


@dataclass
class _Selection:
    template: QuestionTemplate
    reason: str
    source_state_id: int | None = None


def _normalize_exam_mode(exam_mode: ExamMode | str) -> str:
    if isinstance(exam_mode, ExamMode):
        return exam_mode.value
    return str(exam_mode).strip().lower()


def _is_placeholder_template(template: QuestionTemplate) -> bool:
    stem = (template.stem or "").strip()
    if not stem:
        return True

    # Legacy fallback stem pattern: "【xxx】(easy) 题目 1"
    if stem.startswith("【") and "题目" in stem and ")" in stem:
        return True

    bad_tokens = ("正确概念", "常见误区", "错误迁移", "无关选项")
    if sum(token in stem for token in bad_tokens) >= 2:
        return True

    if template.options_json:
        try:
            opts = json.loads(template.options_json)
        except json.JSONDecodeError:
            opts = None
        if isinstance(opts, list):
            joined = " ".join(str(item) for item in opts)
            if all(token in joined for token in bad_tokens):
                return True
    return False


def _build_unit_template_pool(
    session: Session,
    *,
    subject: str,
    unit_filter: set[int] | None = None,
    question_type_filter: set[str] | None = None,
    excluded_template_ids: set[int] | None = None,
) -> dict[int, list[QuestionTemplate]]:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.status == "active",
    )
    if unit_filter:
        stmt = stmt.where(QuestionTemplate.teaching_unit_id.in_(unit_filter))  # type: ignore[union-attr]
    if question_type_filter:
        stmt = stmt.where(QuestionTemplate.question_type.in_(question_type_filter))  # type: ignore[union-attr]

    rows = list(session.exec(stmt.order_by(QuestionTemplate.id)).all())
    pool: dict[int, list[QuestionTemplate]] = defaultdict(list)
    excluded = excluded_template_ids or set()
    for item in rows:
        if item.id is None:
            continue
        if item.id in excluded:
            continue
        if _is_placeholder_template(item):
            continue
        pool[item.teaching_unit_id].append(item)
    return pool


def _weighted_split(total: int, ratios: list[float]) -> list[int]:
    raw = [total * ratio for ratio in ratios]
    base = [floor(value) for value in raw]
    remain = total - sum(base)
    remainders = sorted(
        enumerate([value - floor(value) for value in raw]),
        key=lambda x: x[1],
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
            templates = unit_to_templates[unit_id]
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
    return set(
        exams_repo.resolve_teaching_units_from_theme_tree_node(
            session,
            theme_tree_node_id,
        )
    )


def _build_mock_final_unit_allocation(
    session: Session,
    *,
    snapshot: CurriculumSnapshot,
    num_questions: int,
) -> dict[int, int]:
    if snapshot.theme_tree_version_id is None:
        return {}

    tree_nodes = list(
        session.exec(
            select(ThemeTreeNode).where(
                ThemeTreeNode.tree_version_id == snapshot.theme_tree_version_id
            )
        ).all()
    )
    if not tree_nodes:
        return {}

    unit_weight: dict[int, int] = defaultdict(int)
    for node in tree_nodes:
        for unit_id in exams_repo.resolve_teaching_units_from_theme_tree_node(
            session,
            node.id or 0,
        ):
            unit_weight[int(unit_id)] += 1

    total_weight = sum(unit_weight.values())
    if total_weight <= 0:
        return {}

    allocation: dict[int, int] = {}
    remaining = num_questions
    unit_items = sorted(unit_weight.items(), key=lambda x: (-x[1], x[0]))
    for idx, (unit_id, weight) in enumerate(unit_items):
        if idx == len(unit_items) - 1:
            take = max(0, remaining)
        else:
            take = floor(num_questions * (weight / total_weight))
        allocation[unit_id] = take
        remaining -= take

    i = 0
    while remaining > 0 and unit_items:
        uid = unit_items[i % len(unit_items)][0]
        allocation[uid] += 1
        remaining -= 1
        i += 1
    return allocation


def _serialize_node_refs_json(session: Session, template_id: int) -> str:
    links = exams_repo.find_node_links_by_template(session, template_id)
    payload = [
        {
            "knowledge_node_id": int(link.get("knowledge_node_id", 0)),
            "coverage_weight": float(link.get("coverage_weight", 0.0)),
            "role": str(link.get("role", "primary")),
        }
        for link in links
        if int(link.get("knowledge_node_id", 0)) > 0
    ]
    return json.dumps(payload, ensure_ascii=False)


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
    as_of: datetime | None = None,
) -> ExamPaper:
    """根据考试模式和学习状态组装试卷。"""

    mode = _normalize_exam_mode(exam_mode)
    now = as_of or utcnow()
    question_type_filter = set(item for item in (preferred_question_types or []) if item)

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
    }

    if mode == ExamMode.PRACTICE.value:
        unit_scope = _resolve_practice_units(
            session,
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids=teaching_unit_ids,
        )
        pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=unit_scope or None,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=pool,
                limit=num_questions,
                used_template_ids=used_template_ids,
                reason="practice_context",
            )
        )
    elif mode == ExamMode.WEAKPOINT_BOOST.value:
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            threshold=0.8,
            target_kind="unit",
        )
        weak_units = {int(state.teaching_unit_id) for state in weak_states if state.teaching_unit_id is not None}
        source_state_by_unit = {
            int(state.teaching_unit_id): state.id
            for state in weak_states
            if state.id is not None and state.teaching_unit_id is not None
        }
        prereq_units: set[int] = set()
        for unit_id in weak_units:
            prereq_units.update(exams_repo.list_prereq_units(session, unit_id))
        transfer_units = set(
            uid
            for uid in _build_unit_template_pool(
                session,
                subject=subject,
                question_type_filter=question_type_filter or None,
                excluded_template_ids=excluded_ids,
            ).keys()
            if uid not in weak_units and uid not in prereq_units
        )
        counts = _weighted_split(num_questions, [0.7, 0.2, 0.1])

        weak_pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=weak_units or None,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        prereq_pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=prereq_units or None,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        transfer_pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=transfer_units or None,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )

        selections.extend(
            _select_round_robin(
                unit_to_templates=weak_pool,
                limit=counts[0],
                used_template_ids=used_template_ids,
                reason="weakpoint_boost",
                source_state_by_unit=source_state_by_unit,
            )
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=prereq_pool,
                limit=counts[1],
                used_template_ids=used_template_ids,
                reason="prereq_patch",
                source_state_by_unit=source_state_by_unit,
            )
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=transfer_pool,
                limit=counts[2],
                used_template_ids=used_template_ids,
                reason="transfer_expand",
                source_state_by_unit=source_state_by_unit,
            )
        )

        context_payload["weakness_state_ids"] = [state.id for state in weak_states if state.id is not None]
    elif mode == ExamMode.REVIEW.value:
        due_states = profile_repo.list_due_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            as_of=now,
            target_kind="unit",
        )
        due_units = {int(state.teaching_unit_id) for state in due_states if state.teaching_unit_id is not None}
        source_state_by_unit = {
            int(state.teaching_unit_id): state.id
            for state in due_states
            if state.id is not None and state.teaching_unit_id is not None
        }
        due_pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=due_units or None,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=due_pool,
                limit=num_questions,
                used_template_ids=used_template_ids,
                reason="review_due",
                source_state_by_unit=source_state_by_unit,
            )
        )
        pending_review_tasks = profile_repo.list_pending_reviews(session, user_id=user_id, subject=subject)
        context_payload["review_task_ids"] = [task.id for task in pending_review_tasks if task.id is not None]
    elif mode == ExamMode.MOCK_FINAL.value:
        allocation = _build_mock_final_unit_allocation(
            session,
            snapshot=curriculum_version,
            num_questions=num_questions,
        )
        pool = _build_unit_template_pool(
            session,
            subject=subject,
            unit_filter=set(allocation.keys()) or None,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        for unit_id, count in allocation.items():
            if count <= 0:
                continue
            unit_templates = {unit_id: pool.get(unit_id, [])}
            selections.extend(
                _select_round_robin(
                    unit_to_templates=unit_templates,
                    limit=count,
                    used_template_ids=used_template_ids,
                    reason="mock_final_proportional",
                )
            )
    else:
        # diagnostic 默认策略：尽量扩大教学单元覆盖
        pool = _build_unit_template_pool(
            session,
            subject=subject,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=pool,
                limit=num_questions,
                used_template_ids=used_template_ids,
                reason="diagnostic_coverage",
            )
        )

    # 若主策略不足，按全量模板回填
    if len(selections) < num_questions:
        fallback_pool = _build_unit_template_pool(
            session,
            subject=subject,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=excluded_ids,
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=fallback_pool,
                limit=(num_questions - len(selections)),
                used_template_ids=used_template_ids,
                reason="fallback_fill",
            )
        )

    # 若因最近试卷去重导致无题可选，则放宽去重策略补题。
    if len(selections) < num_questions and excluded_ids:
        relaxed_pool = _build_unit_template_pool(
            session,
            subject=subject,
            question_type_filter=question_type_filter or None,
            excluded_template_ids=None,
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=relaxed_pool,
                limit=(num_questions - len(selections)),
                used_template_ids=used_template_ids,
                reason="fallback_relaxed_exclusion",
            )
        )

    if len(selections) < num_questions and question_type_filter:
        any_type_pool = _build_unit_template_pool(
            session,
            subject=subject,
            excluded_template_ids=None,
        )
        selections.extend(
            _select_round_robin(
                unit_to_templates=any_type_pool,
                limit=(num_questions - len(selections)),
                used_template_ids=used_template_ids,
                reason="fallback_any_type",
            )
        )

    # 避免创建空试卷：若仍无题，直接失败让上层返回 failed job。
    if not selections:
        raise ValueError("当前科目暂无可用题目模板，系统自动构题失败，请稍后重试。")

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
    )
    if paper.id is None:
        raise ValueError("ExamPaper.id should not be None after persistence.")

    items_to_create: list[ExamPaperItem] = []
    for item_order, selection in enumerate(selections, start=1):
        template = selection.template
        options_snapshot = template.options_json
        answer_snapshot = template.answer
        if (
            template.question_type == QuestionType.SINGLE_CHOICE.value
            and template.options_json is not None
        ):
            try:
                options_snapshot, answer_snapshot = shuffle_single_choice_options(
                    template.options_json,
                    template.answer,
                )
            except Exception:
                # 选项异常时保底使用原始快照，避免整卷失败
                logger.warning("paper_assembler_shuffle_failed", template_id=template.id)
                options_snapshot = template.options_json
                answer_snapshot = template.answer

        template_id = template.id
        if template_id is None:
            continue
        items_to_create.append(
            ExamPaperItem(
                exam_paper_id=paper.id,
                question_template_id=template_id,
                item_order=item_order,
                stem_snapshot=template.stem,
                options_snapshot_json=options_snapshot,
                answer_snapshot=answer_snapshot,
                explanation_snapshot=template.explanation,
                teaching_unit_id=template.teaching_unit_id,
                node_refs_json=_serialize_node_refs_json(session, template_id),
                difficulty=template.difficulty,
                question_type=template.question_type,
                score=1.0,
                created_at=utcnow(),
            )
        )

    created_items = exams_repo.create_exam_paper_items(session, items_to_create)
    paper.total_items = len(created_items)
    paper.status = "ready"
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)

    selection_reason_map: dict[str, dict[str, object]] = {}
    for created_item, selection in zip(created_items, selections):
        if created_item.id is None:
            continue
        selection_reason_map[str(created_item.id)] = {
            "question_template_id": selection.template.id,
            "reason": selection.reason,
            "source_state_id": selection.source_state_id,
        }

    context_payload["selection_reasons"] = selection_reason_map
    paper.selection_context_json = json.dumps(context_payload, ensure_ascii=False)
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper
