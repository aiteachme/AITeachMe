"""MVP repair/router for DocGen review actions."""

from __future__ import annotations

import re
from typing import Literal

from app.shared.infra.llm_support import acompletion_with_fallback, get_llm_concurrency_limit
from app.shared.infra.runtime import gather_with_concurrency
from app.shared.infra.tools.builtin.markdown_processing import normalize_markdown_rendering
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import DocGenBaseModel, RepairTraceItem, ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.presentation_policy import (
    find_docgen_presentation_issues,
    normalize_docgen_presentation,
)
from app.workflows.digest.docgen.prompts.repair import build_chapter_patch_messages


_ACTION_REQUIRES_FUTURE_REPAIR = {
    "regenerate_chapter",
    "re_dispatch",
    "rebuild_backbone",
}
_PATCHABLE_ACTION_TYPES = {"surface_patch", "section_patch", "evidence_patch", "regenerate_chapter"}
_MAX_PATCH_ATTEMPTS_PER_CHAPTER = 1
_MAX_PATCH_CONTEXT_CHARS = 7000


class _LocalMarkdownPatch(DocGenBaseModel):
    status: Literal["patch", "no_change"] = "patch"
    target_anchor: str = ""
    patch_markdown: str = ""
    note: str = ""


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


def _normalize_anchor(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _trim_patch_context(markdown: str, *, max_chars: int = _MAX_PATCH_CONTEXT_CHARS) -> str:
    text = str(markdown or "").strip()
    if len(text) <= max_chars:
        return text
    head_len = max_chars // 2
    tail_len = max_chars - head_len
    return f"{text[:head_len].rstrip()}\n\n[...中间内容已截断，仅用于局部修补定位...]\n\n{text[-tail_len:].lstrip()}"


def _heading_match(line: str):
    return re.match(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", line.strip())


def _find_heading_section(markdown: str, *, anchor: str, chapter_title: str) -> tuple[int, int] | None:
    normalized_anchor = _normalize_anchor(anchor)
    normalized_title = _normalize_anchor(chapter_title)
    if not normalized_anchor or normalized_anchor == normalized_title:
        return None
    lines = str(markdown or "").splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    for index, line in enumerate(lines):
        match = _heading_match(line)
        if match is None:
            continue
        heading_title = _normalize_anchor(match.group("title"))
        if normalized_anchor not in heading_title and heading_title not in normalized_anchor:
            continue
        level = len(match.group("marks"))
        end_index = len(lines)
        for next_index in range(index + 1, len(lines)):
            next_match = _heading_match(lines[next_index])
            if next_match is not None and len(next_match.group("marks")) <= level:
                end_index = next_index
                break
        return offsets[index], offsets[end_index] if end_index < len(offsets) else len(markdown)
    return None


def _patch_context_for_action(chapter: ReviewedChapterDraft, action: ReviewAction) -> str:
    section = _find_heading_section(
        chapter.markdown,
        anchor=action.target_anchor,
        chapter_title=chapter.title,
    )
    if section is None:
        return _trim_patch_context(chapter.markdown)
    start, end = section
    return _trim_patch_context(chapter.markdown[start:end])


def _clean_patch_snippet(markdown: str, *, chapter_title: str) -> str:
    cleaned = normalize_markdown_rendering(_strip_markdown_fence(markdown)).strip()
    lines = []
    chapter_title_norm = _normalize_anchor(chapter_title)
    for line in cleaned.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line.strip())
        if match is not None and _normalize_anchor(match.group(1)) == chapter_title_norm:
            continue
        if match is not None:
            lines.append(f"## {match.group(1).strip()}")
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _fallback_insert_offset(markdown: str) -> int:
    matches = list(
        re.finditer(
            r"(?m)^##\s+(?:本章小结|小结|总结|回顾|复盘|本章复盘|自测|练习)",
            str(markdown or ""),
        )
    )
    if matches:
        return matches[-1].start()
    return len(markdown)


def _insert_local_patch(
    markdown: str,
    patch_markdown: str,
    *,
    target_anchor: str,
    chapter_title: str,
) -> str:
    patch = _clean_patch_snippet(patch_markdown, chapter_title=chapter_title)
    if not patch:
        return markdown
    if _normalize_anchor(patch) and _normalize_anchor(patch) in _normalize_anchor(markdown):
        return markdown
    section = _find_heading_section(markdown, anchor=target_anchor, chapter_title=chapter_title)
    insert_at = section[1] if section is not None else _fallback_insert_offset(markdown)
    before = markdown[:insert_at].rstrip()
    after = markdown[insert_at:].lstrip()
    middle = f"{before}\n\n{patch}\n"
    if after:
        return f"{middle}\n{after}".rstrip() + "\n"
    return middle.rstrip() + "\n"


async def _apply_patch_action(
    *,
    chapter: ReviewedChapterDraft,
    action: ReviewAction,
) -> tuple[ReviewedChapterDraft, RepairTraceItem, ReviewAction, str | None]:
    """对单章执行一次安全局部 patch。

    只处理 review action 指向的小范围问题；LLM 只返回局部补丁片段，
    由代码插回章节。若返回空、无变化或失败，就记录 skipped/downgraded，
    不假装已经修复。
    """

    if action.action_type == "surface_patch" and "Markdown 渲染结构异常" in action.reason:
        before_issues = find_docgen_presentation_issues(chapter.markdown)
        patched = normalize_docgen_presentation(
            chapter.markdown,
            title=chapter.title,
            focus_items=[],
        )
        after_issues = find_docgen_presentation_issues(patched)
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
        patch_result = await acompletion_with_fallback(
            build_chapter_patch_messages(
                chapter_title=chapter.title,
                action=action.model_dump(mode="json"),
                markdown_context=_patch_context_for_action(chapter, action),
                full_markdown_chars=len(chapter.markdown),
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.REPAIR_PATCH,
                chapter_index=chapter.chapter_index,
                repair_action_id=action.action_id,
                repair_action_type=action.action_type,
            ),
            response_model=_LocalMarkdownPatch,
        )
        if isinstance(patch_result, _LocalMarkdownPatch):
            patch = patch_result
        else:
            patch = _LocalMarkdownPatch(patch_markdown=str(patch_result or ""))
        patched = (
            chapter.markdown
            if patch.status == "no_change"
            else _insert_local_patch(
                chapter.markdown,
                patch.patch_markdown,
                target_anchor=patch.target_anchor or action.target_anchor,
                chapter_title=chapter.title,
            )
        )
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
                    detail="LLM local patch returned empty, no_change, duplicate, or unchanged markdown.",
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
    """Apply safe local patches and route heavier actions for later repair loops."""

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
        attempted_count = 0
        results: list[tuple[int, ReviewAction, RepairTraceItem, str | None]] = []
        for action_index, action in indexed_actions:
            if attempted_count >= _MAX_PATCH_ATTEMPTS_PER_CHAPTER:
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
                            detail="Skipped because this chapter already had one local repair attempt in this pass.",
                        ),
                        _unresolved_message(updated_action, status="skipped"),
                    )
                )
                continue

            attempted_count += 1
            patched_chapter, trace_item, updated_action, unresolved_message = await _apply_patch_action(
                chapter=current_chapter,
                action=action,
            )
            current_chapter = patched_chapter
            results.append((action_index, updated_action, trace_item, unresolved_message))
        return current_chapter, results

    for action_index, action in enumerate(review_actions, start=1):
        if action.action_type in _PATCHABLE_ACTION_TYPES:
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
            patch_action = action
            if action.action_type == "regenerate_chapter":
                patch_action = action.model_copy(
                    update={
                        "action_type": "section_patch",
                        "reason": f"重生成动作降级为单章局部修补：{action.reason}",
                    }
                )
            patch_actions_by_chapter.setdefault(chapter.chapter_index, []).append((action_index, patch_action))
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
        patch_jobs = [
            (chapters_by_index[chapter_index], indexed_actions)
            for chapter_index, indexed_actions in sorted(patch_actions_by_chapter.items())
        ]
        patch_results = await gather_with_concurrency(
            patch_jobs,
            lambda job: _process_patch_actions_for_chapter(job[0], job[1]),
            limit=get_llm_concurrency_limit(),
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
