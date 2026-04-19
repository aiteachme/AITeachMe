"""MVP repair/router for DocGen review actions."""

from __future__ import annotations

import re

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.docgen.lib.models import RepairTraceItem, ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.prompts import build_chapter_patch_messages


_ACTION_REQUIRES_FUTURE_REPAIR = {
    "evidence_patch",
    "regenerate_chapter",
    "re_dispatch",
    "rebuild_backbone",
}


def _unresolved_message(action: ReviewAction, *, status: str) -> str:
    chapter = f" ch{action.chapter_index}" if action.chapter_index is not None else ""
    anchor = f" @{action.target_anchor}" if action.target_anchor else ""
    return f"{action.action_type}{chapter}{anchor}: {action.reason} [{status}]"


def _strip_markdown_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    match = re.match(r"^```(?:markdown)?\s*\n(?P<body>.*?)\n```$", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match is not None:
        return match.group("body").strip()
    return cleaned


async def _apply_patch_action(
    *,
    chapter: ReviewedChapterDraft,
    action: ReviewAction,
) -> tuple[ReviewedChapterDraft, RepairTraceItem, ReviewAction, str | None]:
    """对单章执行一次安全局部 patch。

    只处理 review action 指向的小范围问题；LLM 必须返回完整章节
    Markdown。若返回空、无变化或失败，就记录 skipped/downgraded，
    不假装已经修复。
    """

    try:
        patched_markdown = await acompletion_with_fallback(
            build_chapter_patch_messages(
                chapter_title=chapter.title,
                action=action.model_dump(mode="json"),
                markdown=chapter.markdown,
            ),
            task_type=TaskType.DOCGEN,
            model="primary",
            extra_metadata={
                "chapter_index": chapter.chapter_index,
                "repair_action_id": action.action_id,
                "repair_action_type": action.action_type,
            },
        )
        patched = _strip_markdown_fence(str(patched_markdown))
        if not patched or patched == chapter.markdown:
            updated_action = action.model_copy(update={"status": "skipped"})
            return (
                chapter,
                RepairTraceItem(
                    trace_id=f"repair_trace_{action.action_id or action.action_type}",
                    action_id=action.action_id,
                    action_type=action.action_type,
                    chapter_index=action.chapter_index,
                    status="skipped",
                    reason=action.reason,
                    target_anchor=action.target_anchor,
                    changed=False,
                    detail="LLM patch returned empty or unchanged markdown.",
                ),
                updated_action,
                _unresolved_message(updated_action, status="skipped"),
            )
        updated = chapter.model_copy(
            update={
                "markdown": patched,
                "patched": True,
                "warnings": [
                    *chapter.warnings,
                    f"已根据复核动作执行局部修补：{action.reason}",
                ],
            }
        )
        updated_action = action.model_copy(update={"status": "applied"})
        return (
            updated,
            RepairTraceItem(
                trace_id=f"repair_trace_{action.action_id or action.action_type}",
                action_id=action.action_id,
                action_type=action.action_type,
                chapter_index=action.chapter_index,
                status="applied",
                reason=action.reason,
                target_anchor=action.target_anchor,
                changed=True,
                detail="Applied LLM markdown patch to the target chapter.",
            ),
            updated_action,
            None,
        )
    except Exception as exc:
        updated_action = action.model_copy(update={"status": "downgraded"})
        return (
            chapter,
            RepairTraceItem(
                trace_id=f"repair_trace_{action.action_id or action.action_type}",
                action_id=action.action_id,
                action_type=action.action_type,
                chapter_index=action.chapter_index,
                status="downgraded",
                reason=action.reason,
                target_anchor=action.target_anchor,
                changed=False,
                detail=f"LLM patch failed: {str(exc)[:180]}",
            ),
            updated_action,
            _unresolved_message(updated_action, status="downgraded"),
        )


async def repair_or_route_review_actions(
    *,
    reviewed_chapters: list[ReviewedChapterDraft],
    review_actions: list[ReviewAction],
) -> tuple[list[ReviewedChapterDraft], list[ReviewAction], list[str], list[RepairTraceItem]]:
    """Apply safe patches and route heavier actions for later repair loops."""

    chapters_by_index = {chapter.chapter_index: chapter for chapter in reviewed_chapters}
    updated_actions: list[ReviewAction] = []
    unresolved: list[str] = []
    repair_trace: list[RepairTraceItem] = []
    patched_chapter_indexes: set[int] = set()
    for action_index, action in enumerate(review_actions, start=1):
        if action.action_type in {"surface_patch", "section_patch"}:
            chapter = chapters_by_index.get(int(action.chapter_index or 0))
            if chapter is None:
                updated_action = action.model_copy(update={"status": "skipped"})
                updated_actions.append(updated_action)
                unresolved.append(_unresolved_message(updated_action, status="skipped"))
                repair_trace.append(
                    RepairTraceItem(
                        trace_id=f"repair_trace_{action.action_id or action.action_type}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="skipped",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=False,
                        detail="No target chapter found for patch action.",
                    )
                )
                continue
            if chapter.chapter_index in patched_chapter_indexes:
                updated_action = action.model_copy(update={"status": "skipped"})
                updated_actions.append(updated_action)
                unresolved.append(_unresolved_message(updated_action, status="skipped"))
                repair_trace.append(
                    RepairTraceItem(
                        trace_id=f"repair_trace_{action_index:03d}_{action.action_id or action.action_type}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="skipped",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=False,
                        detail="Skipped because another patch was already applied to this chapter in the same repair pass.",
                    )
                )
                continue
            patched_chapter, trace_item, updated_action, unresolved_message = await _apply_patch_action(
                chapter=chapter,
                action=action,
            )
            chapters_by_index[patched_chapter.chapter_index] = patched_chapter
            if trace_item.changed:
                patched_chapter_indexes.add(patched_chapter.chapter_index)
            updated_actions.append(updated_action)
            repair_trace.append(trace_item)
            if unresolved_message:
                unresolved.append(unresolved_message)
            continue
        if action.action_type in _ACTION_REQUIRES_FUTURE_REPAIR:
            status = "downgraded"
            detail = "MVP repair router recorded this action without changing markdown."
        else:
            status = "recorded"
            detail = "Review requested record-only handling."
        updated_action = action.model_copy(update={"status": status})
        updated_actions.append(updated_action)
        unresolved.append(_unresolved_message(updated_action, status=status))
        repair_trace.append(
            RepairTraceItem(
                trace_id=f"repair_trace_{action_index:03d}_{action.action_id or action.action_type}",
                action_id=action.action_id,
                action_type=action.action_type,
                chapter_index=action.chapter_index,
                status=status,
                reason=action.reason,
                target_anchor=action.target_anchor,
                changed=False,
                detail=detail,
            )
        )
    repaired_chapters = [chapters_by_index[index] for index in sorted(chapters_by_index)]
    return repaired_chapters, updated_actions, unresolved, repair_trace


__all__ = ["repair_or_route_review_actions"]
