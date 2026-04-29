"""MVP repair/router for DocGen review actions."""

from __future__ import annotations

import asyncio
import re

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.tools.builtin.markdown_processing import (
    find_markdown_rendering_issues,
    normalize_markdown_rendering,
)
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import RepairTraceItem, ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.prompts.repair import build_chapter_patch_messages


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

    if action.action_type == "surface_patch" and "Markdown 渲染结构异常" in action.reason:
        before_issues = find_markdown_rendering_issues(chapter.markdown)
        patched = normalize_markdown_rendering(chapter.markdown)
        after_issues = find_markdown_rendering_issues(patched)
        improved = patched and patched != chapter.markdown and len(after_issues) < len(before_issues)
        if improved:
            updated = chapter.model_copy(
                update={
                    "markdown": patched,
                    "patched": True,
                    "warnings": [
                        *chapter.warnings,
                        f"已执行确定性 Markdown 渲染修补：{action.reason}",
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
                    detail="Applied deterministic markdown rendering normalization.",
                ),
                updated_action,
                None,
            )
        updated_action = action.model_copy(update={"status": "skipped"})
        remaining = "；".join(after_issues or before_issues or ["确定性修补未减少渲染问题。"])
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
                detail=f"Deterministic markdown normalization did not reduce rendering issues: {remaining}",
            ),
            updated_action,
            _unresolved_message(updated_action, status="skipped"),
        )

    try:
        patched_markdown = await acompletion_with_fallback(
            build_chapter_patch_messages(
                chapter_title=chapter.title,
                action=action.model_dump(mode="json"),
                markdown=chapter.markdown,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.REPAIR_PATCH,
                chapter_index=chapter.chapter_index,
                repair_action_id=action.action_id,
                repair_action_type=action.action_type,
            ),
        )
        patched = normalize_markdown_rendering(_strip_markdown_fence(str(patched_markdown)))
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
    updated_actions_by_index: dict[int, ReviewAction] = {}
    unresolved_by_index: dict[int, str] = {}
    repair_trace_by_index: dict[int, RepairTraceItem] = {}
    patch_actions_by_chapter: dict[int, list[tuple[int, ReviewAction]]] = {}

    async def _process_patch_actions_for_chapter(
        chapter: ReviewedChapterDraft,
        indexed_actions: list[tuple[int, ReviewAction]],
    ) -> tuple[ReviewedChapterDraft, list[tuple[int, ReviewAction, RepairTraceItem, str | None]]]:
        current_chapter = chapter
        chapter_locked = False
        results: list[tuple[int, ReviewAction, RepairTraceItem, str | None]] = []
        for action_index, action in indexed_actions:
            if chapter_locked:
                updated_action = action.model_copy(update={"status": "skipped"})
                results.append(
                    (
                        action_index,
                        updated_action,
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
                        ),
                        _unresolved_message(updated_action, status="skipped"),
                    )
                )
                continue

            patched_chapter, trace_item, updated_action, unresolved_message = await _apply_patch_action(
                chapter=current_chapter,
                action=action,
            )
            current_chapter = patched_chapter
            if trace_item.changed and "Markdown 渲染结构异常" not in action.reason:
                chapter_locked = True
            results.append((action_index, updated_action, trace_item, unresolved_message))
        return current_chapter, results

    for action_index, action in enumerate(review_actions, start=1):
        if action.action_type in {"surface_patch", "section_patch"}:
            chapter = chapters_by_index.get(int(action.chapter_index or 0))
            if chapter is None:
                updated_action = action.model_copy(update={"status": "skipped"})
                updated_actions_by_index[action_index] = updated_action
                unresolved_by_index[action_index] = _unresolved_message(updated_action, status="skipped")
                repair_trace_by_index[action_index] = RepairTraceItem(
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
                continue
            patch_actions_by_chapter.setdefault(chapter.chapter_index, []).append((action_index, action))
            continue

        if action.action_type in _ACTION_REQUIRES_FUTURE_REPAIR:
            status = "downgraded"
            detail = "MVP repair router recorded this action without changing markdown."
        else:
            status = "recorded"
            detail = "Review requested record-only handling."
        updated_action = action.model_copy(update={"status": status})
        updated_actions_by_index[action_index] = updated_action
        unresolved_by_index[action_index] = _unresolved_message(updated_action, status=status)
        repair_trace_by_index[action_index] = RepairTraceItem(
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

    if patch_actions_by_chapter:
        patch_results = await asyncio.gather(
            *[
                _process_patch_actions_for_chapter(chapters_by_index[chapter_index], indexed_actions)
                for chapter_index, indexed_actions in sorted(patch_actions_by_chapter.items())
            ]
        )
        for patched_chapter, action_results in patch_results:
            chapters_by_index[patched_chapter.chapter_index] = patched_chapter
            for action_index, updated_action, trace_item, unresolved_message in action_results:
                updated_actions_by_index[action_index] = updated_action
                repair_trace_by_index[action_index] = trace_item
                if unresolved_message:
                    unresolved_by_index[action_index] = unresolved_message

    updated_actions = [
        updated_actions_by_index[index]
        for index in range(1, len(review_actions) + 1)
        if index in updated_actions_by_index
    ]
    unresolved = [
        unresolved_by_index[index]
        for index in range(1, len(review_actions) + 1)
        if index in unresolved_by_index
    ]
    repair_trace = [
        repair_trace_by_index[index]
        for index in range(1, len(review_actions) + 1)
        if index in repair_trace_by_index
    ]
    repaired_chapters = [chapters_by_index[index] for index in sorted(chapters_by_index)]
    return repaired_chapters, updated_actions, unresolved, repair_trace


__all__ = ["repair_or_route_review_actions"]
