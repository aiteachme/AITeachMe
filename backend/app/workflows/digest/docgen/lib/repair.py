"""MVP repair/router for DocGen review actions."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
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
_MAX_LLM_PATCH_ROUNDS_PER_CHAPTER = 3
_MAX_PATCH_CONTEXT_CHARS = 7000


class _LocalMarkdownPatch(DocGenBaseModel):
    status: Literal["patch", "no_change"] = "patch"
    target_anchor: str = ""
    patch_markdown: str = ""
    covered_action_ids: list[str] = Field(default_factory=list)
    unresolved_action_ids: list[str] = Field(default_factory=list)
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


def _is_deterministic_rendering_patch(action: ReviewAction) -> bool:
    return action.action_type == "surface_patch" and (
        "Markdown 渲染结构异常" in action.reason
        or "Markdown 展示与学习结构异常" in action.reason
    )


def _repair_action_key(action_index: int, action: ReviewAction) -> str:
    return action.action_id or f"repair_action_{action_index:03d}"


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


def _patch_context_for_actions(chapter: ReviewedChapterDraft, actions: list[ReviewAction]) -> str:
    if len(actions) == 1:
        return _patch_context_for_action(chapter, actions[0])
    sections: list[str] = []
    seen: set[tuple[int, int]] = set()
    for action in actions:
        section = _find_heading_section(
            chapter.markdown,
            anchor=action.target_anchor,
            chapter_title=chapter.title,
        )
        if section is None or section in seen:
            continue
        seen.add(section)
        start, end = section
        sections.append(chapter.markdown[start:end].strip())
    if sections:
        return _trim_patch_context("\n\n---\n\n".join(sections))
    return _trim_patch_context(chapter.markdown)


def _fallback_patch_target_anchor(
    indexed_actions: list[tuple[int, ReviewAction]],
    *,
    covered_keys: set[str],
) -> str:
    if covered_keys:
        for action_index, action in indexed_actions:
            if _repair_action_key(action_index, action) in covered_keys and action.target_anchor:
                return action.target_anchor
    for _, action in indexed_actions:
        if action.target_anchor:
            return action.target_anchor
    return ""


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
    """对单章执行一次确定性展示修补。

    LLM 内容修补统一走 batched patch rounds；这里只处理无需模型的
    Markdown 渲染结构归一化。
    """

    if _is_deterministic_rendering_patch(action):
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
            detail="Non-deterministic patch actions are handled by batched LLM patch rounds.",
        ),
        updated_action,
        _unresolved_message(updated_action, status="skipped"),
    )


async def _apply_llm_patch_actions(
    *,
    chapter: ReviewedChapterDraft,
    indexed_actions: list[tuple[int, ReviewAction]],
    repair_round: int,
) -> tuple[ReviewedChapterDraft, list[tuple[int, ReviewAction, RepairTraceItem, str | None]], list[tuple[int, ReviewAction]]]:
    """Ask the model for one local patch that can cover multiple actions."""

    action_payloads = [
        {
            **action.model_dump(mode="json"),
            "repair_action_key": _repair_action_key(action_index, action),
        }
        for action_index, action in indexed_actions
    ]
    action_keys = {
        _repair_action_key(action_index, action): (action_index, action)
        for action_index, action in indexed_actions
    }
    llm_call_group = f"ch{chapter.chapter_index:02d}_repair_round_{repair_round}"
    try:
        patch_result = await acompletion_with_fallback(
            build_chapter_patch_messages(
                chapter_title=chapter.title,
                actions=action_payloads,
                markdown_context=_patch_context_for_actions(chapter, [action for _, action in indexed_actions]),
                full_markdown_chars=len(chapter.markdown),
                repair_round=repair_round,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.REPAIR_PATCH,
                chapter_index=chapter.chapter_index,
                repair_round=repair_round,
                repair_action_count=len(indexed_actions),
            ),
            response_model=_LocalMarkdownPatch,
        )
        patch = patch_result if isinstance(patch_result, _LocalMarkdownPatch) else _LocalMarkdownPatch(
            patch_markdown=str(patch_result or "")
        )
    except Exception as exc:
        results: list[tuple[int, ReviewAction, RepairTraceItem, str | None]] = []
        for action_index, action in indexed_actions:
            updated_action = action.model_copy(update={"status": "downgraded"})
            results.append(
                (
                    action_index,
                    updated_action,
                    RepairTraceItem(
                        trace_id=f"repair_trace_{repair_round:02d}_{_repair_action_key(action_index, action)}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="downgraded",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=False,
                        llm_attempted=True,
                        llm_call_group=llm_call_group,
                        detail=f"LLM patch round failed: {str(exc)[:180]}",
                    ),
                    _unresolved_message(updated_action, status="downgraded"),
                )
            )
        return chapter, results, []

    covered_keys = {str(item).strip() for item in patch.covered_action_ids if str(item).strip()}
    unresolved_keys = {str(item).strip() for item in patch.unresolved_action_ids if str(item).strip()}
    covered_keys &= set(action_keys)
    unresolved_keys &= set(action_keys)
    if not covered_keys and not unresolved_keys:
        covered_keys = set(action_keys)
    patched = (
        chapter.markdown
        if patch.status == "no_change"
        else _insert_local_patch(
            chapter.markdown,
            patch.patch_markdown,
            target_anchor=patch.target_anchor or _fallback_patch_target_anchor(indexed_actions, covered_keys=covered_keys),
            chapter_title=chapter.title,
        )
    )
    if not patched or patched == chapter.markdown:
        results = []
        for action_index, action in indexed_actions:
            updated_action = action.model_copy(update={"status": "skipped"})
            results.append(
                (
                    action_index,
                    updated_action,
                    RepairTraceItem(
                        trace_id=f"repair_trace_{repair_round:02d}_{_repair_action_key(action_index, action)}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="skipped",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=False,
                        llm_attempted=True,
                        llm_call_group=llm_call_group,
                        detail="LLM local patch round returned empty, no_change, duplicate, or unchanged markdown.",
                    ),
                    _unresolved_message(updated_action, status="skipped"),
                )
            )
        return chapter, results, []
    updated = chapter.model_copy(
        update={
            "markdown": patched,
            "patched": True,
            "warnings": [
                *chapter.warnings,
                f"已根据 {len(covered_keys)} 条复核动作执行第 {repair_round} 轮局部修补。",
            ],
        }
    )
    results = []
    remaining: list[tuple[int, ReviewAction]] = []
    for action_index, action in indexed_actions:
        key = _repair_action_key(action_index, action)
        if key in covered_keys:
            updated_action = action.model_copy(update={"status": "applied"})
            results.append(
                (
                    action_index,
                    updated_action,
                    RepairTraceItem(
                        trace_id=f"repair_trace_{repair_round:02d}_{key}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="applied",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=True,
                        llm_attempted=True,
                        llm_call_group=llm_call_group,
                        detail="Applied shared LLM local patch round to this review action.",
                    ),
                    None,
                )
            )
        elif key in unresolved_keys:
            updated_action = action.model_copy(update={"status": "skipped"})
            results.append(
                (
                    action_index,
                    updated_action,
                    RepairTraceItem(
                        trace_id=f"repair_trace_{repair_round:02d}_{key}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="skipped",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=False,
                        llm_attempted=True,
                        llm_call_group=llm_call_group,
                        detail="LLM local patch round marked this action unresolved.",
                    ),
                    _unresolved_message(updated_action, status="skipped"),
                )
            )
        else:
            remaining.append((action_index, action))
    return updated, results, remaining


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
        results: list[tuple[int, ReviewAction, RepairTraceItem, str | None]] = []
        llm_actions: list[tuple[int, ReviewAction]] = []
        for action_index, action in indexed_actions:
            if not _is_deterministic_rendering_patch(action):
                llm_actions.append((action_index, action))
                continue
            patched_chapter, trace_item, updated_action, unresolved_message = await _apply_patch_action(
                chapter=current_chapter,
                action=action,
            )
            current_chapter = patched_chapter
            results.append((action_index, updated_action, trace_item, unresolved_message))

        remaining_llm_actions = llm_actions
        for repair_round in range(1, _MAX_LLM_PATCH_ROUNDS_PER_CHAPTER + 1):
            if not remaining_llm_actions:
                break
            current_chapter, round_results, remaining_llm_actions = await _apply_llm_patch_actions(
                chapter=current_chapter,
                indexed_actions=remaining_llm_actions,
                repair_round=repair_round,
            )
            results.extend(round_results)

        for action_index, action in remaining_llm_actions:
            updated_action = action.model_copy(update={"status": "skipped"})
            results.append(
                (
                    action_index,
                    updated_action,
                    RepairTraceItem(
                        trace_id=f"repair_trace_max_rounds_{_repair_action_key(action_index, action)}",
                        action_id=action.action_id,
                        action_type=action.action_type,
                        chapter_index=action.chapter_index,
                        status="skipped",
                        reason=action.reason,
                        target_anchor=action.target_anchor,
                        changed=False,
                        detail=(
                            "Skipped because this chapter reached the configured LLM local repair round limit "
                            f"({_MAX_LLM_PATCH_ROUNDS_PER_CHAPTER})."
                        ),
                    ),
                    _unresolved_message(updated_action, status="skipped"),
                )
            )
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
        patch_results = await run_llm_tasks(
            patch_jobs,
            lambda job: _process_patch_actions_for_chapter(job[0], job[1]),
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
