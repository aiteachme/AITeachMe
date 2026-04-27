"""Keep the visible planner brief as-is."""

from __future__ import annotations

from app.workflows.digest.planner.lib.models import PlannerBrief


def parse_planner_brief_text(text: str, *, base_brief: PlannerBrief) -> PlannerBrief:
    markdown = str(text or "").strip()
    return base_brief.model_copy(update={"markdown": markdown or base_brief.markdown})


__all__ = ["parse_planner_brief_text"]
