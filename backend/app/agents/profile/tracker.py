"""
掌握度计算 — 从判分结果更新 UserProfile

从每道已判分题目提取 knowledge_point，增量更新 UserProfile 的 attempts/correct。
mastery = correct / attempts（attempts > 0），否则 mastery = None。
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.repositories import profile_repo
from app.repositories.models import Question

logger = structlog.get_logger()


def update_profiles_from_grading(
    session: Session,
    *,
    subject: str,
    grading_results: list[dict],
    user_id: str = "local",
) -> None:
    """
    Update mastery profiles incrementally from one grading result batch.

    Args:
        session: 数据库会话。
        subject: 学科标识。
        grading_results: 判分结果列表，每项至少包含 `question` 和 `is_correct`。
        user_id: 用户 ID，默认 `local`。
    """
    if not grading_results:
        return

    # 按 knowledge_point 聚合本次判分结果
    kp_stats: dict[str, dict[str, int]] = {}
    for r in grading_results:
        kp = r["question"].knowledge_point
        if kp not in kp_stats:
            kp_stats[kp] = {"attempts": 0, "correct": 0}
        kp_stats[kp]["attempts"] += 1
        if r["is_correct"]:
            kp_stats[kp]["correct"] += 1

    # 获取该学科所有已有 profile，构建查找表
    existing_profiles, _ = profile_repo.list_profiles_by_subject(
        session, subject, user_id=user_id, limit=10000, offset=0
    )
    profile_map = {p.knowledge_point: p for p in existing_profiles}

    # 逐知识点增量更新
    for kp, stats in kp_stats.items():
        current = profile_map.get(kp)
        prev_attempts = current.attempts if current else 0
        prev_correct = current.correct if current else 0

        profile_repo.upsert_profile(
            session,
            user_id=user_id,
            subject=subject,
            knowledge_point=kp,
            attempts=prev_attempts + stats["attempts"],
            correct=prev_correct + stats["correct"],
        )

    logger.info(
        "profiles_updated",
        subject=subject,
        knowledge_points=len(kp_stats),
        total_attempts=sum(s["attempts"] for s in kp_stats.values()),
    )
