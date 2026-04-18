"""MVP repair/router for DocGen review actions."""

from __future__ import annotations

from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft


def repair_or_route_review_actions(
    *,
    reviewed_chapters: list[ReviewedChapterDraft],
    review_actions: list[ReviewAction],
) -> tuple[list[ReviewedChapterDraft], list[ReviewAction], list[str]]:
    """Apply only safe surface patches and record all heavier routes."""

    updated_actions: list[ReviewAction] = []
    unresolved: list[str] = []
    for action in review_actions:
        if action.action_type == "surface_patch":
            updated_actions.append(action.model_copy(update={"status": "applied"}))
            continue
        updated_actions.append(action.model_copy(update={"status": "recorded"}))
        unresolved.append(
            f"{action.action_type}"
            + (f" ch{action.chapter_index}" if action.chapter_index is not None else "")
            + f": {action.reason}"
        )
    return reviewed_chapters, updated_actions, unresolved


__all__ = ["repair_or_route_review_actions"]
