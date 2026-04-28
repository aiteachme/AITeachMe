"""Runtime helpers for the profile workflow."""

from __future__ import annotations

import structlog
from langsmith import traceable

from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.prompt_loader import populate_prompt
from app.schemas.llm import SYSTEM, USER
from app.workflows.profile.pipeline.prompts import SYSTEM_PROMPT_REPORT_SUGGESTIONS

logger = structlog.get_logger()

_NO_WEAK_POINTS_MESSAGE = "\u5f53\u524d\u6ca1\u6709\u660e\u663e\u8584\u5f31\u70b9\uff0c\u5efa\u8bae\u4fdd\u6301\u7ec3\u4e60\u9891\u7387\u5e76\u5b9a\u671f\u56de\u987e\u91cd\u70b9\u7ae0\u8282\u3002"
_DEFAULT_SUGGESTION = "\u5efa\u8bae\u4f18\u5148\u9488\u5bf9\u8584\u5f31\u77e5\u8bc6\u70b9\u5b89\u6392\u4e13\u9879\u590d\u4e60\u3002"
_NO_DATA_TEXT = "\u6682\u65e0\u6570\u636e"
_ADVISOR_SYSTEM_PROMPT = "\u4f60\u662f\u4e00\u540d\u5b66\u4e60\u987e\u95ee\u3002"
_BULLET_PREFIX_CHARS = "0123456789.\u3001- "


@traceable(name="profile.generate_report_suggestions", run_type="chain")
async def generate_report_suggestions(
    *,
    subject_name: str,
    overall_mastery: float | None,
    weak_points: list[dict],
) -> list[str]:
    """Generate lightweight study suggestions for a subject profile."""

    if not weak_points:
        return [_NO_WEAK_POINTS_MESSAGE]

    prompt = populate_prompt(
        SYSTEM_PROMPT_REPORT_SUGGESTIONS,
        subject_name=subject_name,
        overall_mastery=f"{overall_mastery:.0%}" if overall_mastery is not None else _NO_DATA_TEXT,
        weak_points="\n".join(
            f"- {item['knowledge_point']}\uff08\u638c\u63e1\u5ea6\uff1a{item['mastery_text']}\uff09"
            for item in weak_points
        ),
    )
    try:
        result = await acompletion(
            messages=[
                {"role": SYSTEM, "content": _ADVISOR_SYSTEM_PROMPT},
                {"role": USER, "content": prompt},
            ],
            task_type=TaskType.SUMMARIZE,
            model="light",
        )
        lines = [
            line.lstrip(_BULLET_PREFIX_CHARS).strip()
            for line in result.splitlines()
            if line.strip()
        ]
        return lines or [_DEFAULT_SUGGESTION]
    except Exception as exc:
        logger.warning("generate_report_suggestions_failed", subject_name=subject_name, error=str(exc))
        raise
