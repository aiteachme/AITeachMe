"""Planner source triage helpers."""

from __future__ import annotations

from app.shared.infra.search.types import SearchResult
from app.workflows.digest.planner.lib.research_probe import PlannerSelectedSource


def rule_based_source_triage(
    results: list[SearchResult],
    *,
    limit: int,
    source_type: str,
    target_chapters: list[str] | None = None,
) -> list[PlannerSelectedSource]:
    selected: list[PlannerSelectedSource] = []
    seen: set[str] = set()
    for result in results:
        key = result.url or f"{result.title}::{result.snippet[:80]}"
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(
            PlannerSelectedSource(
                title=result.title or result.url,
                url=result.url,
                source_type=source_type,
                reason="与本轮学习目标和检索词相关。",
                target_chapters=list(target_chapters or []),
                should_open=True,
                snippet=result.snippet,
            )
        )
        if len(selected) >= limit:
            break
    return selected


__all__ = ["rule_based_source_triage"]
