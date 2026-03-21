"""题目模板构建器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass

import structlog
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agents.examine.prompts import SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT
from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models import Difficulty, QuestionTemplate, QuestionTemplateNodeLink, QuestionType
from app.models.curriculum import TeachingUnitMembership
from app.repositories import assessment_repo
from app.repositories.knowledge import curriculum_repo, kg_repo
from app.schemas.llm import SYSTEM
from app.utils.time import utcnow

logger = structlog.get_logger()


def _stem_hash(stem: str) -> str:
    return hashlib.sha256(stem.strip().encode("utf-8")).hexdigest()


def _normalize_options(options: list[str] | None) -> str | None:
    if not options:
        return None
    return json.dumps([str(item) for item in options], ensure_ascii=False)


def validate_single_choice_options(options_json: str | None) -> bool:
    """校验单选题 options 是否为至少 2 项的 JSON 数组。"""

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


def _build_deterministic_templates(
    *,
    node_contexts: list[_NodeContext],
    questions_per_unit: int,
) -> list[_GeneratedTemplateItem]:
    """LLM 不可用时的本地兜底模板生成。"""

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
        stem = f"【{node.node_name}】({difficulty}) 题目 {idx + 1}"
        if qtype == QuestionType.SINGLE_CHOICE.value:
            options = ["A. 正确概念", "B. 常见误区", "C. 错误迁移", "D. 无关选项"]
            answer = options[0]
        elif qtype == QuestionType.FILL_BLANK.value:
            options = None
            answer = "关键结论"
        else:
            options = None
            answer = "完整作答包含核心概念与推理过程。"
        questions.append(
            _GeneratedTemplateItem(
                question_type=qtype,
                difficulty=difficulty,
                stem=stem,
                options=options,
                answer=answer,
                explanation=f"围绕 {node.node_name} 的标准解析。",
                knowledge_node_id=node.node_id,
            )
        )
    return questions


def _try_llm_generate_templates(
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

    async def _call_llm() -> _GeneratedTemplatePayload:
        return await acompletion_structured(
            response_model=_GeneratedTemplatePayload,
            messages=[{"role": SYSTEM, "content": prompt}],
        )

    try:
        payload = asyncio.run(_call_llm())
        return payload.questions
    except RuntimeError:
        # 当前线程已有事件循环（如 notebook/异步环境），不强行嵌套 run
        logger.warning("question_builder_llm_skipped_running_loop")
        return None
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


def build_question_templates(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
    questions_per_unit: int = 9,
    created_by_job_id: int | None = None,
) -> list[QuestionTemplate]:
    """Phase A：为教学单元构建 QuestionTemplate 模板。"""

    created_templates: list[QuestionTemplate] = []
    for unit_id in unit_ids:
        node_contexts = _load_unit_node_contexts(session, unit_id)
        if not node_contexts:
            logger.warning("question_builder_skip_unit_without_context", unit_id=unit_id, subject=subject)
            continue

        generated = _try_llm_generate_templates(
            subject=subject,
            node_contexts=node_contexts,
            questions_per_unit=questions_per_unit,
        )
        if generated is None:
            generated = _build_deterministic_templates(
                node_contexts=node_contexts,
                questions_per_unit=questions_per_unit,
            )

        links_to_create = []
        for draft in generated:
            question_type = (draft.question_type or "").strip().lower()
            difficulty = (draft.difficulty or "").strip().lower()
            if question_type not in {item.value for item in QuestionType}:
                continue
            if difficulty not in {item.value for item in Difficulty}:
                continue

            options_json = _normalize_options(draft.options)
            if question_type == QuestionType.SINGLE_CHOICE.value and not validate_single_choice_options(options_json):
                continue

            stem = draft.stem.strip()
            stem_hash = _stem_hash(stem)
            if assessment_repo.find_template_by_stem_hash(session, subject, unit_id, stem_hash) is not None:
                logger.info("question_builder_skip_duplicate_stem_hash", unit_id=unit_id, stem_hash=stem_hash)
                continue

            template = QuestionTemplate(
                subject=subject,
                teaching_unit_id=unit_id,
                question_type=question_type,
                difficulty=difficulty,
                stem=stem,
                stem_hash=stem_hash,
                options=options_json,
                answer=draft.answer.strip(),
                explanation=draft.explanation.strip(),
                status="active",
                created_by_job_id=created_by_job_id,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            persisted = assessment_repo.create_question_template(session, template)
            created_templates.append(persisted)

            # 至少绑定一个节点，优先使用生成结果中的 knowledge_node_id，否则回退到轮询节点
            if draft.knowledge_node_id is not None:
                node_id = draft.knowledge_node_id
            else:
                node_id = node_contexts[len(created_templates) % len(node_contexts)].node_id
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
            # 延迟批量创建，降低 commit 次数
            assessment_repo.create_template_node_links(session, links_to_create)

    return created_templates
