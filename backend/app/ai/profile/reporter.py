"""
学习报告生成 — 总体掌握度、薄弱点 Top 5、复习建议

需求：11.3, 11.5
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.core.llm import acompletion
from app.repositories import profile_repo
from app.repositories.models import UserProfile

logger = structlog.get_logger()


async def generate_report(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
) -> dict:
    """
    生成学习进度报告。

    Returns:
        {
            "overall_mastery": float | None,
            "weak_points_top5": list[UserProfile],
            "suggestions": list[str],
        }
    """
    # 获取所有有测试记录的 profile（mastery 非 null）
    all_profiles, _ = profile_repo.list_profiles_by_subject(
        session, subject, user_id=user_id, limit=10000, offset=0
    )
    tested = [p for p in all_profiles if p.mastery is not None and p.attempts > 0]

    # 总体掌握度：所有已测试知识点的加权平均（按 attempts 加权）
    overall_mastery: float | None = None
    if tested:
        total_attempts = sum(p.attempts for p in tested)
        if total_attempts > 0:
            overall_mastery = sum(p.correct for p in tested) / total_attempts

    # 薄弱点 Top 5（mastery < 0.6，升序排列）
    weak_points = profile_repo.get_weak_points(
        session, subject, user_id=user_id, threshold=0.6
    )
    weak_top5 = weak_points[:5]

    # 生成复习建议
    suggestions = await _generate_suggestions(subject, overall_mastery, weak_top5)

    logger.info(
        "report_generated",
        subject=subject,
        overall_mastery=round(overall_mastery, 3) if overall_mastery is not None else None,
        weak_count=len(weak_points),
    )

    return {
        "overall_mastery": overall_mastery,
        "weak_points_top5": weak_top5,
        "suggestions": suggestions,
    }


async def _generate_suggestions(
    subject: str,
    overall_mastery: float | None,
    weak_points: list[UserProfile],
) -> list[str]:
    """通过 LLM 生成个性化复习建议。无薄弱点时返回默认建议。"""
    if not weak_points:
        return ["当前没有明显薄弱项，建议继续保持学习节奏，定期复习巩固。"]

    weak_desc = "\n".join(
        f"- {p.knowledge_point}：掌握度 {p.mastery:.0%}（{p.correct}/{p.attempts} 正确）"
        for p in weak_points
    )
    mastery_desc = f"{overall_mastery:.0%}" if overall_mastery is not None else "暂无数据"

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位学习顾问。根据学生的掌握度数据，给出 3~5 条简洁的复习建议。"
                "每条建议一句话，直接给出行动建议，不要编号。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"学科：{subject}\n"
                f"总体掌握度：{mastery_desc}\n"
                f"薄弱知识点：\n{weak_desc}\n\n"
                f"请给出复习建议："
            ),
        },
    ]

    try:
        result = await acompletion(messages)
        # 按行拆分，过滤空行和编号前缀
        lines = [
            line.lstrip("0123456789.、）) ").strip()
            for line in result.strip().splitlines()
            if line.strip()
        ]
        return lines if lines else ["建议针对薄弱知识点进行专项复习。"]
    except Exception:
        logger.warning("suggestion_generation_fallback", subject=subject)
        return [
            f"重点复习薄弱知识点：{', '.join(p.knowledge_point for p in weak_points)}",
            "建议通过做题巩固薄弱环节。",
        ]
