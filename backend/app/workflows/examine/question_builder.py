"""Question template builder aligned with digest outputs and profile signals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict

import structlog
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.infra.llm import acompletion_structured
from app.infra.model_router import TaskType
from app.infra.prompt_loader import populate_prompt
from app.infra.tracing import llm_trace_scope
from app.models import Difficulty, QuestionTemplate, QuestionType
from app.repositories import exams_repo
from app.repositories.knowledge import curriculum_repo
from app.schemas.llm import SYSTEM
from app.utils.time import utcnow
from app.workflows.examine.context import (
    ExamStyleProfile,
    NodeExamContext,
    TemplateSelectionHints,
    UnitExamContext,
    build_unit_exam_contexts,
    summarize_hint_text,
    template_matches_request_context,
    truncate_text,
)
from app.workflows.examine.prompts import SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT

logger = structlog.get_logger()

_MAX_CONCURRENT_TEMPLATE_CALLS = 12


class _GeneratedTemplateItem(BaseModel):
    question_type: str
    difficulty: str
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_node_id: int | None = None


class _GeneratedTemplatePayload(BaseModel):
    questions: list[_GeneratedTemplateItem] = Field(min_length=1)


def _stem_hash(stem: str) -> str:
    return hashlib.sha256(stem.strip().encode("utf-8")).hexdigest()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _normalize_options(options: list[str] | None) -> str | None:
    if not options:
        return None
    cleaned = [_clean_text(item) for item in options if _clean_text(item)]
    if len(cleaned) < 2:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def _normalize_question_type(value: str, *, preferred_question_types: list[str]) -> str:
    normalized = (value or "").strip().lower()
    aliases = {
        "choice": QuestionType.SINGLE_CHOICE.value,
        "multiple_choice": QuestionType.SINGLE_CHOICE.value,
        "single": QuestionType.SINGLE_CHOICE.value,
        "blank": QuestionType.FILL_BLANK.value,
        "fill": QuestionType.FILL_BLANK.value,
        "fill_in_blank": QuestionType.FILL_BLANK.value,
        "essay": QuestionType.SHORT_ANSWER.value,
        "qa": QuestionType.SHORT_ANSWER.value,
        "short": QuestionType.SHORT_ANSWER.value,
    }
    normalized = aliases.get(normalized, normalized)
    valid = {item.value for item in QuestionType}
    if normalized in valid:
        return normalized
    if preferred_question_types:
        return preferred_question_types[0]
    return QuestionType.SINGLE_CHOICE.value


def _normalize_difficulty(value: str) -> str:
    normalized = (value or "").strip().lower()
    aliases = {
        "simple": Difficulty.EASY.value,
        "basic": Difficulty.EASY.value,
        "normal": Difficulty.MEDIUM.value,
        "moderate": Difficulty.MEDIUM.value,
        "challenging": Difficulty.HARD.value,
    }
    normalized = aliases.get(normalized, normalized)
    valid = {item.value for item in Difficulty}
    return normalized if normalized in valid else Difficulty.MEDIUM.value


def validate_single_choice_options(options_json: str | None) -> bool:
    if not options_json:
        return False
    try:
        decoded = json.loads(options_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(decoded, list) or len(decoded) < 2:
        return False
    return len({_clean_text(str(item)).lower() for item in decoded if _clean_text(str(item))}) >= 2


def _pick_reference_sentence(context: UnitExamContext, node: NodeExamContext) -> str:
    source = "\n".join(
        part for part in [node.summary, node.body, context.doc_excerpt, context.unit_summary] if part.strip()
    )
    sentences = [_clean_text(item) for item in re.split(r"[。！？!?\n]+", source) if _clean_text(item)]
    if not sentences:
        return node.node_name
    scored = sorted(
        sentences,
        key=lambda item: (
            0 if 18 <= len(item) <= 90 else 1,
            abs(len(item) - 48),
            0 if node.node_name in item else 1,
        ),
    )
    return truncate_text(scored[0], max_chars=120)


def _pick_question_type_sequence(
    *,
    preferred_question_types: list[str],
    questions_per_unit: int,
    style_profile: ExamStyleProfile,
) -> list[str]:
    if preferred_question_types:
        base = preferred_question_types
    elif style_profile.preferred_question_types:
        base = style_profile.preferred_question_types
    else:
        base = [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.FILL_BLANK.value,
            QuestionType.SHORT_ANSWER.value,
        ]
    sequence: list[str] = []
    while len(sequence) < max(1, questions_per_unit):
        sequence.extend(base)
    return sequence[: max(1, questions_per_unit)]


def _build_single_choice_template(
    context: UnitExamContext,
    node: NodeExamContext,
    *,
    difficulty: str,
) -> _GeneratedTemplateItem:
    reference = _pick_reference_sentence(context, node)
    distractors = [item.node_name for item in context.node_contexts if item.node_id != node.node_id]
    options = [
        f"最符合资料表述的是：{reference}",
        f"它主要讨论的是 {distractors[0]}。" if distractors else "它只是与本单元无关的背景信息。",
        "它表示只要记住结论，不需要理解概念之间的关系。",
        "它意味着所有同类题都可以不看条件直接套用。",
    ]
    return _GeneratedTemplateItem(
        question_type=QuestionType.SINGLE_CHOICE.value,
        difficulty=difficulty,
        stem=f"关于“{node.node_name}”，下列哪一项最符合当前知识资料的表述？",
        options=options,
        answer=options[0],
        explanation=f"依据知识文档与图谱锚点，{node.node_name} 的核心信息可概括为：{reference}",
        knowledge_node_id=node.node_id,
    )


def _build_fill_blank_template(
    context: UnitExamContext,
    node: NodeExamContext,
    *,
    difficulty: str,
) -> _GeneratedTemplateItem:
    reference = _pick_reference_sentence(context, node)
    if node.node_name and node.node_name in reference and len(node.node_name) >= 2:
        stem = reference.replace(node.node_name, "____", 1)
        answer = node.node_name
    else:
        stem = f"请根据本单元资料补全关键概念：{reference}，其中最核心的知识点是 ____。"
        answer = node.node_name
    return _GeneratedTemplateItem(
        question_type=QuestionType.FILL_BLANK.value,
        difficulty=difficulty,
        stem=stem,
        answer=answer,
        explanation=f"空缺处对应的核心知识点是 {node.node_name}。",
        knowledge_node_id=node.node_id,
    )


def _build_short_answer_template(
    context: UnitExamContext,
    node: NodeExamContext,
    *,
    difficulty: str,
) -> _GeneratedTemplateItem:
    reference = _pick_reference_sentence(context, node)
    compare_target = next(
        (item.node_name for item in context.node_contexts if item.node_id != node.node_id),
        "相关知识点",
    )
    return _GeneratedTemplateItem(
        question_type=QuestionType.SHORT_ANSWER.value,
        difficulty=difficulty,
        stem=(
            f"请结合当前知识资料，说明“{node.node_name}”的核心含义，并指出它与“{compare_target}”"
            "之间最值得注意的一点区别或联系。"
        ),
        answer=(
            f"作答时应先概括 {node.node_name} 的定义或关键机制，再结合资料说明它与 {compare_target} 的"
            f"联系、区别或使用场景。参考线索：{reference}"
        ),
        explanation="评分关注三个点：概念是否准确、关系是否说清、是否结合资料中的关键线索。",
        knowledge_node_id=node.node_id,
    )


def _pick_difficulty_sequence(style_profile: ExamStyleProfile) -> list[str]:
    focus = (style_profile.difficulty_focus or "").strip().lower()
    if focus == Difficulty.EASY.value:
        return [Difficulty.EASY.value, Difficulty.EASY.value, Difficulty.MEDIUM.value]
    if focus == Difficulty.HARD.value:
        return [Difficulty.MEDIUM.value, Difficulty.HARD.value, Difficulty.HARD.value]
    if focus == "mixed":
        return [Difficulty.EASY.value, Difficulty.MEDIUM.value, Difficulty.HARD.value]
    return [Difficulty.MEDIUM.value, Difficulty.EASY.value, Difficulty.HARD.value]


def _build_deterministic_templates(
    context: UnitExamContext,
    *,
    questions_per_unit: int,
) -> list[_GeneratedTemplateItem]:
    if not context.node_contexts:
        return []
    type_sequence = _pick_question_type_sequence(
        preferred_question_types=context.preferred_question_types,
        questions_per_unit=questions_per_unit,
        style_profile=context.style_profile,
    )
    difficulties = _pick_difficulty_sequence(context.style_profile)
    drafts: list[_GeneratedTemplateItem] = []
    for index, question_type in enumerate(type_sequence):
        node = context.node_contexts[index % len(context.node_contexts)]
        difficulty = difficulties[index % len(difficulties)]
        if question_type == QuestionType.FILL_BLANK.value:
            drafts.append(_build_fill_blank_template(context, node, difficulty=difficulty))
        elif question_type == QuestionType.SHORT_ANSWER.value:
            drafts.append(_build_short_answer_template(context, node, difficulty=difficulty))
        else:
            drafts.append(_build_single_choice_template(context, node, difficulty=difficulty))
    return drafts


async def _try_llm_generate_templates(
    context: UnitExamContext,
    *,
    questions_per_unit: int,
    semaphore: asyncio.Semaphore,
) -> list[_GeneratedTemplateItem] | None:
    prompt = populate_prompt(
        SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
        subject=context.subject,
        num_questions=questions_per_unit,
        question_types=", ".join(context.preferred_question_types or [item.value for item in QuestionType]),
        difficulties=", ".join(item.value for item in Difficulty),
        knowledge_packet=context.prompt_block(),
    )

    try:
        async with semaphore:
            with llm_trace_scope(
                subject=context.subject,
                workflow="examine.generate",
                lane="question_build",
                node=f"unit_{context.unit_id}",
            ):
                payload = await acompletion_structured(
                    response_model=_GeneratedTemplatePayload,
                    messages=[{"role": SYSTEM, "content": prompt}],
                    task_type=TaskType.GENERATE,
                )
        return payload.questions
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "question_builder_llm_failed",
            subject=context.subject,
            unit_id=context.unit_id,
            unit_name=context.unit_name,
            error=str(exc),
        )
        return None


def _find_node_context(
    node_contexts: list[NodeExamContext],
    node_id: int | None,
) -> NodeExamContext | None:
    if node_id is None:
        return None
    return next((item for item in node_contexts if item.node_id == node_id), None)


def _pick_secondary_node_contexts(
    context: UnitExamContext,
    *,
    primary_node_id: int,
    text: str,
) -> list[NodeExamContext]:
    normalized_text = _clean_text(text).lower()
    if not normalized_text:
        return []

    matched_nodes: list[tuple[int, float, NodeExamContext]] = []
    for node_context in context.node_contexts:
        if node_context.node_id == primary_node_id:
            continue
        normalized_name = _clean_text(node_context.node_name).lower()
        if len(normalized_name) < 2 or normalized_name not in normalized_text:
            continue
        matched_nodes.append(
            (
                normalized_text.find(normalized_name),
                -max(0.0, node_context.coverage_weight),
                node_context,
            )
        )

    return [item[2] for item in sorted(matched_nodes)[:2]]


def _build_weighted_node_refs(node_contexts: list[NodeExamContext]) -> str:
    if not node_contexts:
        return "[]"

    if len(node_contexts) == 1:
        return json.dumps(
            [
                {
                    "knowledge_node_id": node_contexts[0].node_id,
                    "coverage_weight": 1.0,
                    "role": "primary",
                }
            ],
            ensure_ascii=False,
        )

    secondary_count = len(node_contexts) - 1
    secondary_total_weight = 0.3
    primary_weight = 1.0 - secondary_total_weight
    secondary_weight = secondary_total_weight / secondary_count
    raw_weights = [primary_weight] + [secondary_weight] * secondary_count

    payload: list[dict[str, object]] = []
    running_weight = 0.0
    for index, (node_context, raw_weight) in enumerate(zip(node_contexts, raw_weights, strict=False)):
        normalized_weight = round(raw_weight, 4)
        if index == len(node_contexts) - 1:
            normalized_weight = round(max(0.0, 1.0 - running_weight), 4)
        payload.append(
            {
                "knowledge_node_id": node_context.node_id,
                "coverage_weight": normalized_weight,
                "role": ("primary" if index == 0 else "related"),
            }
        )
        running_weight += normalized_weight
    return json.dumps(payload, ensure_ascii=False)


def _build_node_refs_json(
    context: UnitExamContext,
    *,
    preferred_node_id: int | None,
    fallback_node_id: int | None,
    stem: str,
    answer: str,
    explanation: str,
) -> str:
    primary_node = _find_node_context(context.node_contexts, preferred_node_id)
    if primary_node is None:
        primary_node = _find_node_context(context.node_contexts, fallback_node_id)
    if primary_node is None and context.node_contexts:
        primary_node = context.node_contexts[0]
    if primary_node is None:
        return "[]"

    secondary_nodes = _pick_secondary_node_contexts(
        context,
        primary_node_id=primary_node.node_id,
        text="\n".join([stem, answer, explanation]),
    )
    return _build_weighted_node_refs([primary_node, *secondary_nodes[:2]])


def _build_selection_hints_json(
    context: UnitExamContext,
    *,
    preferred_node_id: int | None,
    context_signature: str | None,
    context_locked: bool,
    scope_locked: bool,
    focus_teaching_unit_ids: list[int],
    focus_node_ids: list[int],
) -> str:
    payload = TemplateSelectionHints(
        exam_mode=context.exam_mode,
        preferred_question_types=list(context.preferred_question_types),
        unit_mastery_score=context.unit_mastery_score,
        weak_node_names=list(context.weak_node_names),
        learning_objectives=list(context.learning_objectives[:5]),
        preferred_node_id=preferred_node_id,
        style_profile=context.style_profile.to_metadata(),
        focus_prompt=context.focus_prompt,
        user_prompt=context.user_prompt,
        context_signature=context_signature,
        context_locked=context_locked,
        scope_locked=scope_locked,
        focus_teaching_unit_ids=sorted({int(item) for item in focus_teaching_unit_ids if int(item) > 0}),
        focus_node_ids=sorted({int(item) for item in focus_node_ids if int(item) > 0}),
        style_prompt_summary=summarize_hint_text(context.style_profile.style_prompt),
        focus_prompt_summary=summarize_hint_text(context.focus_prompt or context.style_profile.focus_prompt),
    )
    return json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False)


def _load_existing_hashes(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
) -> dict[int, set[str]]:
    if not unit_ids:
        return {}
    rows = session.exec(
        select(QuestionTemplate.teaching_unit_id, QuestionTemplate.stem_hash).where(
            QuestionTemplate.subject == subject,
            QuestionTemplate.teaching_unit_id.in_(unit_ids),
        )
    ).all()
    result: dict[int, set[str]] = defaultdict(set)
    for unit_id, stem_hash in rows:
        if unit_id is None or not stem_hash:
            continue
        result[int(unit_id)].add(str(stem_hash))
    return result


def _load_existing_template_counts(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
    preferred_question_types: list[str],
    difficulty_focus: str | None,
    curriculum_version_id: int | None,
    context_signature: str | None,
    context_locked: bool,
) -> dict[int, int]:
    if not unit_ids:
        return {}

    candidate_templates = exams_repo.list_active_question_templates(
        session,
        subject=subject,
        curriculum_version_id=curriculum_version_id,
        unit_ids=set(unit_ids),
        question_types=set(preferred_question_types) if preferred_question_types else None,
        difficulty=(
            difficulty_focus
            if difficulty_focus in {Difficulty.EASY.value, Difficulty.MEDIUM.value, Difficulty.HARD.value}
            else None
        ),
    )

    counts_by_unit: dict[int, int] = defaultdict(int)
    for template in candidate_templates:
        if not template_matches_request_context(
            template.selection_hints_json,
            requested_context_signature=context_signature,
            context_locked=context_locked,
        ):
            continue
        counts_by_unit[int(template.teaching_unit_id)] += 1
    return counts_by_unit


def _prepare_template_drafts(
    context: UnitExamContext,
    *,
    generated_items: list[_GeneratedTemplateItem],
    existing_hashes: set[str],
    curriculum_version_id: int | None,
    context_signature: str | None,
    context_locked: bool,
    scope_locked: bool,
    focus_teaching_unit_ids: list[int],
    focus_node_ids: list[int],
) -> list[QuestionTemplate]:
    prepared: list[QuestionTemplate] = []
    now = utcnow()

    for index, draft in enumerate(generated_items):
        question_type = _normalize_question_type(
            draft.question_type,
            preferred_question_types=context.preferred_question_types,
        )
        difficulty = _normalize_difficulty(draft.difficulty)

        stem = _clean_text(draft.stem)
        answer = _clean_text(draft.answer)
        explanation = _clean_text(draft.explanation)
        if not stem or not answer or not explanation:
            continue

        options_json = _normalize_options(draft.options)
        if question_type == QuestionType.SINGLE_CHOICE.value and not validate_single_choice_options(options_json):
            continue

        stem_hash = _stem_hash(stem)
        if stem_hash in existing_hashes:
            continue
        existing_hashes.add(stem_hash)

        fallback_node_id = context.node_contexts[index % len(context.node_contexts)].node_id if context.node_contexts else None
        preferred_node_id = draft.knowledge_node_id if draft.knowledge_node_id is not None else fallback_node_id
        prepared.append(
            QuestionTemplate(
                subject=context.subject,
                teaching_unit_id=context.unit_id,
                question_type=question_type,
                difficulty=difficulty,
                stem=stem,
                stem_hash=stem_hash,
                options_json=options_json,
                answer=answer,
                explanation=explanation,
                node_refs_json=_build_node_refs_json(
                    context,
                    preferred_node_id=preferred_node_id,
                    fallback_node_id=fallback_node_id,
                    stem=stem,
                    answer=answer,
                    explanation=explanation,
                ),
                selection_hints_json=_build_selection_hints_json(
                    context,
                    preferred_node_id=preferred_node_id,
                    context_signature=context_signature,
                    context_locked=context_locked,
                    scope_locked=scope_locked,
                    focus_teaching_unit_ids=focus_teaching_unit_ids,
                    focus_node_ids=focus_node_ids,
                ),
                status="active",
                curriculum_version_id=curriculum_version_id,
                created_at=now,
                updated_at=now,
            )
        )
    return prepared


async def build_question_templates(
    session: Session,
    *,
    subject: str,
    user_id: str,
    unit_ids: list[int],
    questions_per_unit: int = 9,
    exam_mode: str = "web_practice",
    preferred_question_types: list[str] | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    style_profile: ExamStyleProfile | None = None,
    curriculum_version_id: int | None = None,
    template_context_signature: str | None = None,
    context_locked: bool = False,
    scope_locked: bool = False,
    focus_teaching_unit_ids: list[int] | None = None,
    focus_node_ids: list[int] | None = None,
) -> list[QuestionTemplate]:
    """Build question templates by teaching units using digest and profile context."""

    contexts = build_unit_exam_contexts(
        session,
        subject=subject,
        user_id=user_id,
        unit_ids=unit_ids,
        questions_per_unit=questions_per_unit,
        exam_mode=exam_mode,
        preferred_question_types=preferred_question_types,
        user_prompt=user_prompt,
        focus_prompt=focus_prompt,
        style_profile=style_profile,
    )
    if not contexts:
        logger.warning("question_builder_no_generation_context", subject=subject)
        return []

    effective_question_types = list(
        preferred_question_types
        or (style_profile.preferred_question_types if style_profile is not None else [])
    )
    difficulty_focus = style_profile.difficulty_focus if style_profile is not None else None
    resolved_curriculum_version_id = curriculum_version_id
    if resolved_curriculum_version_id is None:
        current_curriculum = curriculum_repo.get_current_curriculum_snapshot(session, subject)
        resolved_curriculum_version_id = current_curriculum.id if current_curriculum is not None else None
    resolved_focus_teaching_unit_ids = list(
        focus_teaching_unit_ids
        or (style_profile.focus_teaching_unit_ids if style_profile is not None else [])
    )
    resolved_focus_node_ids = list(
        focus_node_ids
        or (style_profile.focus_node_ids if style_profile is not None else [])
    )
    existing_count_by_unit = _load_existing_template_counts(
        session,
        subject=subject,
        unit_ids=[context.unit_id for context in contexts],
        preferred_question_types=effective_question_types,
        difficulty_focus=difficulty_focus,
        curriculum_version_id=resolved_curriculum_version_id,
        context_signature=template_context_signature,
        context_locked=context_locked,
    )
    pending_contexts = [
        context
        for context in contexts
        if existing_count_by_unit.get(context.unit_id, 0) < questions_per_unit
    ]
    if not pending_contexts:
        logger.info(
            "question_builder_skip_existing_inventory",
            subject=subject,
            unit_count=len(contexts),
            questions_per_unit=questions_per_unit,
            difficulty_focus=difficulty_focus,
        )
        return []

    logger.info(
        "question_builder_contexts_prepared",
        subject=subject,
        unit_count=len(contexts),
        pending_unit_count=len(pending_contexts),
        questions_per_unit=questions_per_unit,
        exam_mode=exam_mode,
    )

    semaphore = asyncio.Semaphore(min(_MAX_CONCURRENT_TEMPLATE_CALLS, max(1, len(pending_contexts))))
    generated_results = await asyncio.gather(
        *[
            _try_llm_generate_templates(
                context,
                questions_per_unit=questions_per_unit,
                semaphore=semaphore,
            )
            for context in pending_contexts
        ],
        return_exceptions=True,
    )

    existing_hashes_by_unit = _load_existing_hashes(
        session,
        subject=subject,
        unit_ids=[context.unit_id for context in pending_contexts],
    )

    templates_to_create: list[QuestionTemplate] = []
    llm_generated_unit_count = 0
    fallback_unit_count = 0
    for context, result in zip(pending_contexts, generated_results):
        if isinstance(result, Exception) or result is None:
            fallback_unit_count += 1
            generated_items = _build_deterministic_templates(
                context,
                questions_per_unit=questions_per_unit,
            )
        else:
            llm_generated_unit_count += 1
            generated_items = result

        templates_to_create.extend(
            _prepare_template_drafts(
                context,
                generated_items=generated_items,
                existing_hashes=existing_hashes_by_unit.setdefault(context.unit_id, set()),
                curriculum_version_id=resolved_curriculum_version_id,
                context_signature=template_context_signature,
                context_locked=context_locked,
                scope_locked=scope_locked,
                focus_teaching_unit_ids=resolved_focus_teaching_unit_ids,
                focus_node_ids=resolved_focus_node_ids,
            )
        )

    if not templates_to_create:
        logger.warning("question_builder_zero_templates", subject=subject)
        return []

    for template in templates_to_create:
        session.add(template)
    session.flush()
    session.commit()
    for template in templates_to_create:
        session.refresh(template)

    logger.info(
        "question_builder_persist_complete",
        subject=subject,
        created_count=len(templates_to_create),
        llm_generated_unit_count=llm_generated_unit_count,
        fallback_unit_count=fallback_unit_count,
    )
    return templates_to_create
