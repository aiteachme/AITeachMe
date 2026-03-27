"""Question template builder.

Reads DB: ``teaching_unit_membership`` plus graph / curriculum context used to build prompts.
Writes DB: ``question_template`` and ``question_template_node_link``.
Writes FS: none.
Idempotency: template creation is best-effort deduplicated by content hashing, but reruns may still
produce additional templates for the same unit when the source context changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

import structlog
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.llm import acompletion_structured
from app.core.model_router import TaskType
from app.core.prompt_loader import populate_prompt
from app.models import Difficulty, QuestionTemplate, QuestionTemplateNodeLink, QuestionType
from app.models.curriculum import TeachingUnitMembership
from app.repositories import exams_repo
from app.repositories.knowledge import curriculum_repo, kg_repo
from app.schemas.llm import SYSTEM
from app.utils.time import utcnow
from app.workflows.examine.prompts import SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT

logger = structlog.get_logger()


def _stem_hash(stem: str) -> str:
    return hashlib.sha256(stem.strip().encode("utf-8")).hexdigest()


def _normalize_options(options: list[str] | None) -> str | None:
    if not options:
        return None
    return json.dumps([str(item) for item in options], ensure_ascii=False)


def validate_single_choice_options(options_json: str | None) -> bool:
    """Validate single-choice options is a JSON list with at least 2 items."""

    if not options_json:
        return False
    try:
        value = json.loads(options_json)
    except json.JSONDecodeError:
        return False
    return isinstance(value, list) and len(value) >= 2


@dataclass
class _NodeContext:
    node_id: int
    node_name: str
    content: str


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


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _pick_reference_sentence(node: _NodeContext) -> str:
    raw = _clean_text(node.content)
    if not raw:
        return f"该知识点围绕“{node.node_name}”的定义、条件与应用。"

    candidates = [
        _clean_text(part)
        for part in re.split(r"[。！？!?;\n]+", raw)
        if _clean_text(part)
    ]
    # Prefer medium-length informative sentence.
    scored = sorted(
        candidates,
        key=lambda s: (
            0 if 18 <= len(s) <= 90 else 1,
            abs(len(s) - 48),
        ),
    )
    if not scored:
        return f"该知识点围绕“{node.node_name}”的定义、条件与应用。"
    picked = scored[0]
    if len(picked) > 120:
        picked = picked[:120].rstrip("，,；;:：") + "..."
    return picked


def _build_fill_blank_stem(node_name: str, reference: str) -> tuple[str, str]:
    if node_name and node_name in reference and len(node_name) >= 2:
        cloze = reference.replace(node_name, "____", 1)
        return f"【填空】请补全与该知识点相关的关键表述：{cloze}", node_name
    return f"【填空】根据知识点说明：{reference}（关键词：____）", node_name or "核心概念"


def _build_deterministic_templates(
    *,
    node_contexts: list[_NodeContext],
    questions_per_unit: int,
) -> list[_GeneratedTemplateItem]:
    """Fallback template generator when LLM is unavailable."""

    if not node_contexts:
        return []

    matrix: list[tuple[str, str]] = [
        (QuestionType.SINGLE_CHOICE.value, Difficulty.EASY.value),
        (QuestionType.SINGLE_CHOICE.value, Difficulty.MEDIUM.value),
        (QuestionType.SINGLE_CHOICE.value, Difficulty.HARD.value),
        (QuestionType.FILL_BLANK.value, Difficulty.EASY.value),
        (QuestionType.FILL_BLANK.value, Difficulty.MEDIUM.value),
        (QuestionType.FILL_BLANK.value, Difficulty.HARD.value),
        (QuestionType.SHORT_ANSWER.value, Difficulty.EASY.value),
        (QuestionType.SHORT_ANSWER.value, Difficulty.MEDIUM.value),
        (QuestionType.SHORT_ANSWER.value, Difficulty.HARD.value),
    ]

    questions: list[_GeneratedTemplateItem] = []
    for idx in range(max(1, questions_per_unit)):
        qtype, difficulty = matrix[idx % len(matrix)]
        node = node_contexts[idx % len(node_contexts)]
        reference = _pick_reference_sentence(node)

        if qtype == QuestionType.SINGLE_CHOICE.value:
            stem = f"【单选】关于知识点「{node.node_name}」，以下哪一项最恰当？"
            options = [
                f"强调“{node.node_name}”的核心含义，并结合条件理解：{reference}",
                f"把“{node.node_name}”当作不需要条件即可套用的结论",
                f"只背结果，不需要理解“{node.node_name}”的适用场景",
                "选择与该知识点无关的描述",
            ]
            answer = options[0]
            explanation = (
                f"正确思路是回到“{node.node_name}”的定义与条件，再结合题目情境判断。"
            )
        elif qtype == QuestionType.FILL_BLANK.value:
            stem, answer = _build_fill_blank_stem(node.node_name, reference)
            options = None
            explanation = f"填空围绕“{node.node_name}”的关键词与核心结论。"
        else:
            stem = (
                f"【简答】请用 2-3 句话说明「{node.node_name}」的核心概念，"
                "并给出一个简短应用步骤。"
            )
            options = None
            answer = (
                f"示例要点：先说明“{node.node_name}”的定义，再写明适用条件，"
                "最后给出一步应用。"
            )
            explanation = f"简答题重点考查你是否真正理解并会应用“{node.node_name}”。"

        questions.append(
            _GeneratedTemplateItem(
                question_type=qtype,
                difficulty=difficulty,
                stem=stem,
                options=options,
                answer=answer,
                explanation=explanation,
                knowledge_node_id=node.node_id,
            )
        )
    return questions


async def _try_llm_generate_templates(
    *,
    subject: str,
    node_contexts: list[_NodeContext],
    questions_per_unit: int,
) -> list[_GeneratedTemplateItem] | None:
    if not node_contexts:
        return []

    joined_knowledge = "\n\n".join(
        f"## {item.node_name}\n{item.content[:1200]}"
        for item in node_contexts
    )
    prompt = populate_prompt(
        SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
        subject=subject,
        num_questions=questions_per_unit,
        knowledge_text=joined_knowledge,
        question_types=", ".join(item.value for item in QuestionType),
        difficulties=", ".join(item.value for item in Difficulty),
    )

    try:
        payload = await acompletion_structured(
            response_model=_GeneratedTemplatePayload,
            messages=[{"role": SYSTEM, "content": prompt}],
            task_type=TaskType.GENERATE,
        )
        return payload.questions
    except Exception as exc:  # noqa: BLE001
        logger.warning("question_builder_llm_failed", error=str(exc))
        return None


def _load_unit_node_contexts(session: Session, unit_id: int) -> list[_NodeContext]:
    memberships: list[TeachingUnitMembership] = curriculum_repo.list_memberships_by_unit(session, unit_id)
    contexts: list[_NodeContext] = []
    for membership in memberships:
        node_with_revision = kg_repo.get_node_with_current_revision(session, membership.knowledge_node_id)
        if node_with_revision is None:
            continue
        node, revision = node_with_revision
        text_parts = [revision.title or "", revision.summary or "", revision.body or ""]
        contexts.append(
            _NodeContext(
                node_id=node.id or membership.knowledge_node_id,
                node_name=node.canonical_name,
                content="\n".join(part for part in text_parts if part).strip(),
            )
        )
    return contexts


async def build_question_templates(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
    questions_per_unit: int = 9,
) -> list[QuestionTemplate]:
    """Build question templates by teaching units."""

    created_templates: list[QuestionTemplate] = []
    valid_question_types = {item.value for item in QuestionType}
    valid_difficulties = {item.value for item in Difficulty}

    for unit_id in unit_ids:
        node_contexts = _load_unit_node_contexts(session, unit_id)
        if not node_contexts:
            logger.warning("question_builder_skip_unit_without_context", unit_id=unit_id, subject=subject)
            continue

        generated = await _try_llm_generate_templates(
            subject=subject,
            node_contexts=node_contexts,
            questions_per_unit=questions_per_unit,
        )
        if generated is None:
            generated = _build_deterministic_templates(
                node_contexts=node_contexts,
                questions_per_unit=questions_per_unit,
            )

        links_to_create: list[QuestionTemplateNodeLink] = []
        for idx, draft in enumerate(generated):
            question_type = (draft.question_type or "").strip().lower()
            difficulty = (draft.difficulty or "").strip().lower()
            if question_type not in valid_question_types:
                continue
            if difficulty not in valid_difficulties:
                continue

            stem = _clean_text(draft.stem)
            answer = _clean_text(draft.answer)
            explanation = _clean_text(draft.explanation)
            if not stem or not answer or not explanation:
                continue

            options_json = _normalize_options(draft.options)
            if question_type == QuestionType.SINGLE_CHOICE.value and not validate_single_choice_options(options_json):
                continue

            stem_hash = _stem_hash(stem)
            if exams_repo.find_template_by_stem_hash(session, subject, unit_id, stem_hash) is not None:
                logger.info("question_builder_skip_duplicate_stem_hash", unit_id=unit_id, stem_hash=stem_hash)
                continue

            template = QuestionTemplate(
                subject=subject,
                teaching_unit_id=unit_id,
                question_type=question_type,
                difficulty=difficulty,
                stem=stem,
                stem_hash=stem_hash,
                options_json=options_json,
                answer=answer,
                explanation=explanation,
                status="active",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            persisted = exams_repo.create_question_template(session, template)
            created_templates.append(persisted)

            fallback_node = node_contexts[idx % len(node_contexts)].node_id
            node_id = draft.knowledge_node_id if draft.knowledge_node_id is not None else fallback_node
            links_to_create.append(
                QuestionTemplateNodeLink(
                    question_template_id=persisted.id or 0,
                    knowledge_node_id=node_id,
                    coverage_weight=1.0,
                    role="primary",
                    created_at=utcnow(),
                )
            )

        if links_to_create:
            exams_repo.create_template_node_links(session, links_to_create)

    return created_templates
