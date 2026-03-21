"""Runtime helpers for the profile workflow."""

from __future__ import annotations

import structlog

from app.core.llm import acompletion
from app.core.prompt_loader import populate_prompt
from app.schemas.llm import SYSTEM, USER
from app.workflows.profile.prompts import SYSTEM_PROMPT_REPORT_SUGGESTIONS

logger = structlog.get_logger()


async def generate_report_suggestions(
    *,
    subject: str,
    overall_mastery: float | None,
    weak_points: list[dict],
) -> list[str]:
    """Generate study suggestions from profile summary data."""

    if not weak_points:
        return ["当前没有明显薄弱项，建议保持练习频率并定期回顾重点章节。"]

    prompt = populate_prompt(
        SYSTEM_PROMPT_REPORT_SUGGESTIONS,
        subject=subject,
        overall_mastery=f"{overall_mastery:.0%}" if overall_mastery is not None else "暂无数据",
        weak_points="\n".join(
            f"- {item['knowledge_point']}（掌握度：{item['mastery_text']}）"
            for item in weak_points
        ),
    )
    try:
        result = await acompletion(
            messages=[
                {"role": SYSTEM, "content": "你是一名学习顾问。"},
                {"role": USER, "content": prompt},
            ]
        )
        suggestions = [
            line.lstrip("0123456789.、").strip()
            for line in result.splitlines()
            if line.strip()
        ]
        return suggestions or ["建议优先针对薄弱知识点安排专项复习。"]
    except Exception:
        logger.warning("generate_report_suggestions_fallback", subject=subject)
        return ["建议优先针对薄弱知识点安排专项复习。"]
