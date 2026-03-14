"""
结构化考试生成 — Instructor 强制 JSON Schema 输出

读取 KnowledgeGraphNode 获取知识范围，优先考查薄弱点（mastery < 0.6），
检查 Mistake 表避免重复最近的错题。

需求：9.1, 9.2, 9.3, 9.4, 9.6
"""

from __future__ import annotations

from pydantic import BaseModel, Field as PydanticField
import structlog
from sqlmodel import Session

from app.core.llm import acompletion_structured
from app.repositories import knowledge_repo, exam_repo, profile_repo
from app.repositories.models import (
    Question,
    QuestionType,
    Difficulty,
)

logger = structlog.get_logger()


# ─── Instructor 结构化输出模型 ───


class GeneratedQuestion(BaseModel):
    """LLM 生成的单道题目，Instructor 强制校验。"""

    question_key: str
    type: str  # single_choice / fill_blank / short_answer
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_point: str
    difficulty: str  # easy / medium / hard


class GeneratedExam(BaseModel):
    """LLM 生成的完整考卷。"""

    questions: list[GeneratedQuestion] = PydanticField(min_length=1)


# ─── 生成逻辑 ───


async def generate_exam(
    session: Session,
    *,
    subject: str,
    num_questions: int = 10,
    difficulty_distribution: dict[str, float] | None = None,
    knowledge_points: list[str] | None = None,
) -> list[Question]:
    """
    生成结构化考卷。

    1. 读取 KnowledgeGraphNode 获取知识范围
    2. 读取 UserProfile 薄弱点优先出题
    3. 读取 Mistake 避免重复近期错题
    4. 调用 LLM 结构化输出
    5. 返回 Question 列表（未持久化，由 service 层保存）
    """
    # 1. 获取知识范围
    graph_nodes = knowledge_repo.list_graph_nodes_by_subject(session, subject)
    all_kp = list({n.title for n in graph_nodes}) if graph_nodes else []

    # 2. 获取薄弱点
    weak_profiles = profile_repo.get_weak_points(session, subject)
    weak_kps = [p.knowledge_point for p in weak_profiles]

    # 3. 获取近期错题以避免重复
    recent_mistakes, _ = exam_repo.list_mistakes_by_subject(
        session, subject, limit=20, offset=0
    )
    recent_stems = [m["question_stem"] for m in recent_mistakes]

    # 4. 构建 prompt
    messages = _build_generation_prompt(
        subject=subject,
        num_questions=num_questions,
        all_knowledge_points=all_kp,
        weak_knowledge_points=weak_kps,
        recent_mistake_stems=recent_stems,
        difficulty_distribution=difficulty_distribution,
        requested_knowledge_points=knowledge_points,
    )

    logger.info(
        "exam_generation_start",
        subject=subject,
        num_questions=num_questions,
        knowledge_points_count=len(all_kp),
        weak_points_count=len(weak_kps),
    )

    # 5. 调用 LLM（重试由 core/llm 统一处理）
    result: GeneratedExam = await acompletion_structured(
        response_model=GeneratedExam,
        messages=messages,
    )

    # 6. 转换为 Question 模型
    questions = _to_question_models(result)

    logger.info("exam_generation_done", subject=subject, generated=len(questions))
    return questions


def _build_generation_prompt(
    *,
    subject: str,
    num_questions: int,
    all_knowledge_points: list[str],
    weak_knowledge_points: list[str],
    recent_mistake_stems: list[str],
    difficulty_distribution: dict[str, float] | None,
    requested_knowledge_points: list[str] | None,
) -> list[dict]:
    """构建考试生成的 LLM 消息。"""
    kp_section = ""
    if requested_knowledge_points:
        kp_section = f"重点考查以下知识点：{', '.join(requested_knowledge_points)}\n"
    elif all_knowledge_points:
        kp_section = f"可用知识点范围：{', '.join(all_knowledge_points[:50])}\n"

    weak_section = ""
    if weak_knowledge_points:
        weak_section = (
            f"以下是学生的薄弱知识点（mastery < 0.6），请优先出题考查：\n"
            f"{', '.join(weak_knowledge_points[:10])}\n"
        )

    avoid_section = ""
    if recent_mistake_stems:
        stems_preview = "\n".join(f"- {s[:80]}" for s in recent_mistake_stems[:10])
        avoid_section = f"请避免生成与以下近期错题完全相同的题目：\n{stems_preview}\n"

    diff_section = ""
    if difficulty_distribution:
        parts = [f"{k}: {int(v * 100)}%" for k, v in difficulty_distribution.items()]
        diff_section = f"难度分布要求：{', '.join(parts)}\n"

    system_msg = (
        f"你是一位专业的{subject}学科出题老师。请根据给定的知识范围生成一份结构化考卷。\n\n"
        f"要求：\n"
        f"- 生成 {num_questions} 道题目\n"
        f"- 支持三种题型：single_choice（单选题）、fill_blank（填空题）、short_answer（简答题）\n"
        f"- 每道题的 question_key 格式为 q1, q2, q3...\n"
        f"- 单选题必须有至少 2 个选项，answer 必须是选项之一\n"
        f"- difficulty 取值：easy / medium / hard\n"
        f"- knowledge_point 必须非空\n"
        f"- 每道题必须有 explanation（解析）\n"
        f"{kp_section}{weak_section}{avoid_section}{diff_section}"
    )

    return [{"role": "system", "content": system_msg}]


def _to_question_models(exam: GeneratedExam) -> list[Question]:
    """将 LLM 结构化输出转换为 Question SQLModel 实例。"""
    questions: list[Question] = []
    for gq in exam.questions:
        # 规范化枚举值
        q_type = gq.type if gq.type in {e.value for e in QuestionType} else QuestionType.SHORT_ANSWER.value
        diff = gq.difficulty if gq.difficulty in {e.value for e in Difficulty} else Difficulty.MEDIUM.value

        q = Question(
            exam_id=0,  # 由 service 层在保存时设置
            question_key=gq.question_key,
            type=q_type,
            stem=gq.stem,
            options=gq.options if q_type == QuestionType.SINGLE_CHOICE.value else None,
            answer=gq.answer,
            explanation=gq.explanation,
            knowledge_point=gq.knowledge_point,
            difficulty=diff,
        )
        questions.append(q)
    return questions
