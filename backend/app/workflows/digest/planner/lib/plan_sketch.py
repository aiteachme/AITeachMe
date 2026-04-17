"""Keep the visible planner brief as-is."""

from __future__ import annotations

from app.workflows.digest.planner.lib.models import PlannerBrief


def parse_planner_brief_text(text: str, *, fallback: PlannerBrief) -> PlannerBrief:
    markdown = str(text or "").strip()
    return fallback.model_copy(update={"markdown": markdown or fallback.markdown})


__all__ = ["parse_planner_brief_text"]
