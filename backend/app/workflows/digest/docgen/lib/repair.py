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
from app.workflows.digest.docgen.lib.unit_tests import unit_test_structure_issues
from app.workflows.digest.docgen.prompts.repair import build_chapter_patch_messages


_ACTION_REQUIRES_FUTURE_REPAIR = {
    "regenerate_chapter",
    "re_dispatch",
    "rebuild_backbone",
}
_PATCHABLE_ACTION_TYPES = {"surface_patch", "section_patch", "regenerate_chapter"}
_MAX_LLM_PATCH_ROUNDS_PER_CHAPTER = 3
_MAX_PATCH_CONTEXT_CHARS = 7000
_MAX_LOCAL_PATCH_CHARS = 2200
_MAX_PATCH_GROWTH_CHARS = 3200
_MAX_PATCH_GROWTH_RATIO = 0.55
_PATCH_PRESENTATION_REGRESSION_MARKERS = (
    "标题层级",
    "标题过长",
    "过长正文",
    "连续列表过长",
    "缺少题目、解析或答案字段",
    "高亮过多",
    "表格列数过多",
    "不受控 HTML",
    "display math 疑似吞入",
)


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


def _is_unit_test_action(action: ReviewAction) -> bool:
    text = " ".join(
        str(item or "")
        for item in (
            action.action_id,
            action.reason,
            action.instruction,
            action.expected_effect,
            " ".join(action.constraints or []),
        )
    )
    return "单元测试" in text


def _is_length_contract_action(action: ReviewAction) -> bool:
    return str(action.action_id or "").endswith("_section_length")


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


def _normalized_visible_heading(value: str) -> str:
    cleaned = re.sub(
        r"^\s*(?:\d+(?:\.\d+)*|[一二三四五六七八九十百千万]+|[ivxlcdm]+)\s*[.)）．、:：]?\s*",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )
    return _normalize_anchor(cleaned)


def _heading_titles(markdown: str, *, levels: set[int]) -> list[str]:
    titles: list[str] = []
    for line in str(markdown or "").splitlines():
        match = _heading_match(line)
        if match is None:
            continue
        if len(match.group("marks")) in levels:
            titles.append(match.group("title").strip())
    return titles


def _duplicate_h2_titles(markdown: str) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for title in _heading_titles(markdown, levels={2}):
        key = _normalized_visible_heading(title)
        if not key:
            continue
        if key in seen and seen[key] not in duplicates:
            duplicates.append(seen[key])
        else:
            seen[key] = title
    return duplicates


def _repeated_content_block_reason(markdown: str) -> str | None:
    lines = [
        _normalize_anchor(re.sub(r"^[>\-\s*`#]+", "", line))
        for line in str(markdown or "").splitlines()
        if len(_normalize_anchor(line)) >= 16 and not _heading_match(line)
    ]
    seen: dict[str, int] = {}
    for index in range(0, max(0, len(lines) - 3)):
        block = "|".join(lines[index:index + 4])
        if len(block) < 120:
            continue
        previous = seen.get(block)
        if previous is not None and index - previous > 4:
            return "检测到重复正文块，疑似 repair 把已有内容再次插入。"
        seen[block] = index
    return None


def _local_patch_risk_reason(
    *,
    original_markdown: str,
    patch_markdown: str,
    append_to_end: bool,
    unit_test_patch: bool = False,
) -> str | None:
    patch = str(patch_markdown or "").strip()
    if not patch:
        return None
    if len(patch) > _MAX_LOCAL_PATCH_CHARS:
        return f"局部补丁过长（{len(patch)} 字符），已拒收以避免整章改写。"
    if _heading_titles(patch, levels={1}):
        return "局部补丁包含一级标题，疑似整章片段。"

    patch_h2 = _heading_titles(patch, levels={2})
    if not append_to_end and len(patch_h2) > 1:
        return "局部补丁包含多个二级标题，疑似跨小节改写。"
    existing_h2 = {_normalized_visible_heading(title): title for title in _heading_titles(original_markdown, levels={2})}
    patch_h2_keys = [_normalized_visible_heading(title) for title in patch_h2]
    if unit_test_patch:
        non_unit_titles = [title for title, key in zip(patch_h2, patch_h2_keys, strict=False) if key != _normalize_anchor("单元测试")]
        if non_unit_titles:
            return "单元测试补丁只能包含 `## 单元测试`，不能附带其它二级标题。"
        if patch_h2_keys != [_normalize_anchor("单元测试")]:
            return "单元测试补丁必须包含且只包含一个 `## 单元测试` 二级标题。"
    elif append_to_end:
        non_unit_titles = [title for title, key in zip(patch_h2, patch_h2_keys, strict=False) if key != _normalize_anchor("单元测试")]
        if non_unit_titles:
            return "章末补丁只能新增 `## 单元测试`，不能附带其它二级标题。"
        if _normalize_anchor("单元测试") in existing_h2 and patch_h2:
            return "原章节已经存在 `## 单元测试`，拒绝重复追加。"
    else:
        overlaps = [existing_h2[key] for key in patch_h2_keys if key and key in existing_h2]
        if overlaps:
            return f"局部补丁重复已有二级标题：{', '.join(overlaps[:3])}。"

    repeated = _repeated_content_block_reason(patch)
    if repeated:
        return repeated
    return None


def _patched_markdown_risk_reason(*, original_markdown: str, patched_markdown: str) -> str | None:
    growth = len(patched_markdown) - len(original_markdown)
    if growth > _MAX_PATCH_GROWTH_CHARS and growth / max(1, len(original_markdown)) > _MAX_PATCH_GROWTH_RATIO:
        return f"修补后正文增长过大（+{growth} 字符），疑似非局部改写。"
    duplicate_h2 = _duplicate_h2_titles(patched_markdown)
    if duplicate_h2:
        return f"修补后出现重复二级标题：{', '.join(duplicate_h2[:3])}。"
    repeated = _repeated_content_block_reason(patched_markdown)
    if repeated:
        return repeated
    before_issues = set(find_docgen_presentation_issues(original_markdown))
    after_issues = set(find_docgen_presentation_issues(patched_markdown))
    regressions = [
        issue
        for issue in after_issues - before_issues
        if any(marker in issue for marker in _PATCH_PRESENTATION_REGRESSION_MARKERS)
    ]
    if regressions:
        return f"修补后新增展示结构问题：{'；'.join(regressions[:3])}。"
    return None


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
    append_to_end: bool = False,
    replace_unit_test: bool = False,
) -> str:
    patch = _clean_patch_snippet(patch_markdown, chapter_title=chapter_title)
    if not patch:
        return markdown
    if not replace_unit_test and _normalize_anchor(patch) and _normalize_anchor(patch) in _normalize_anchor(markdown):
        return markdown
    if replace_unit_test:
        section = _find_heading_section(markdown, anchor="单元测试", chapter_title=chapter_title)
        if section is not None:
            start, end = section
            before = markdown[:start].rstrip()
            after = markdown[end:].lstrip()
            replaced = f"{before}\n\n{patch}\n"
            if after:
                replaced += f"\n{after}"
            return replaced.rstrip() + "\n"
        append_to_end = True
    section = None if append_to_end else _find_heading_section(markdown, anchor=target_anchor, chapter_title=chapter_title)
    if append_to_end:
        insert_at = len(markdown)
    else:
        insert_at = section[1] if section is not None else _fallback_insert_offset(markdown)
    before = markdown[:insert_at].rstrip()
    after = markdown[insert_at:].lstrip()
    middle = f"{before}\n\n{patch}\n"
    if after:
        return f"{middle}\n{after}".rstrip() + "\n"
    return middle.rstrip() + "\n"


def _rejected_llm_patch_results(
    *,
    indexed_actions: list[tuple[int, ReviewAction]],
    repair_round: int,
    llm_call_group: str,
    reason: str,
) -> list[tuple[int, ReviewAction, RepairTraceItem, str | None]]:
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
                    detail=f"Rejected unsafe LLM local patch: {reason}",
                ),
                _unresolved_message(updated_action, status="downgraded"),
            )
        )
    return results


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
    unit_test_patch = any(
        _is_unit_test_action(action) and _repair_action_key(action_index, action) in covered_keys
        for action_index, action in indexed_actions
    )
    append_to_end = unit_test_patch
    patch_markdown = _clean_patch_snippet(patch.patch_markdown, chapter_title=chapter.title)
    if patch.status != "no_change":
        risk_reason = _local_patch_risk_reason(
            original_markdown=chapter.markdown,
            patch_markdown=patch_markdown,
            append_to_end=append_to_end,
            unit_test_patch=unit_test_patch,
        )
        if risk_reason:
            return chapter, _rejected_llm_patch_results(
                indexed_actions=indexed_actions,
                repair_round=repair_round,
                llm_call_group=llm_call_group,
                reason=risk_reason,
            ), (indexed_actions if unit_test_patch else [])
    patched = (
        chapter.markdown
        if patch.status == "no_change"
        else _insert_local_patch(
            chapter.markdown,
            patch_markdown,
            target_anchor=patch.target_anchor or _fallback_patch_target_anchor(indexed_actions, covered_keys=covered_keys),
            chapter_title=chapter.title,
            append_to_end=append_to_end,
            replace_unit_test=unit_test_patch,
        )
    )
    if patched and patched != chapter.markdown:
        normalized_patched = normalize_docgen_presentation(patched, title=chapter.title)
        if unit_test_patch:
            structure_issues = unit_test_structure_issues(normalized_patched)
            if structure_issues:
                return chapter, _rejected_llm_patch_results(
                    indexed_actions=indexed_actions,
                    repair_round=repair_round,
                    llm_call_group=llm_call_group,
                    reason="单元测试补丁未通过题答合同：" + "；".join(structure_issues[:4]),
                ), indexed_actions
        risk_reason = _patched_markdown_risk_reason(
            original_markdown=chapter.markdown,
            patched_markdown=normalized_patched,
        )
        if risk_reason:
            return chapter, _rejected_llm_patch_results(
                indexed_actions=indexed_actions,
                repair_round=repair_round,
                llm_call_group=llm_call_group,
                reason=risk_reason,
            ), (indexed_actions if unit_test_patch else [])
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
    allow_llm_patches: bool = True,
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

        regular_llm_actions = [
            indexed_action for indexed_action in llm_actions if not _is_unit_test_action(indexed_action[1])
        ]
        unit_test_llm_actions = [
            indexed_action for indexed_action in llm_actions if _is_unit_test_action(indexed_action[1])
        ]
        remaining_llm_actions: list[tuple[int, ReviewAction]] = []
        if not allow_llm_patches:
            recorded_actions = [
                indexed_action
                for indexed_action in regular_llm_actions
                if not _is_length_contract_action(indexed_action[1])
            ]
            regular_llm_actions = [
                indexed_action
                for indexed_action in regular_llm_actions
                if _is_length_contract_action(indexed_action[1])
            ]
            for action_index, action in recorded_actions:
                updated_action = action.model_copy(update={"status": "recorded"})
                results.append(
                    (
                        action_index,
                        updated_action,
                        RepairTraceItem(
                            trace_id=f"repair_trace_recorded_{_repair_action_key(action_index, action)}",
                            action_id=action.action_id,
                            action_type=action.action_type,
                            chapter_index=action.chapter_index,
                            status="recorded",
                            reason=action.reason,
                            target_anchor=action.target_anchor,
                            changed=False,
                            llm_attempted=False,
                            detail="Recorded after rule review without a second semantic LLM rewrite.",
                        ),
                        _unresolved_message(updated_action, status="recorded"),
                    )
                )
        for action_batch in (regular_llm_actions, unit_test_llm_actions):
            repair_round = 1
            current_batch = action_batch
            while current_batch and repair_round <= _MAX_LLM_PATCH_ROUNDS_PER_CHAPTER:
                current_chapter, round_results, current_batch = await _apply_llm_patch_actions(
                    chapter=current_chapter,
                    indexed_actions=current_batch,
                    repair_round=repair_round,
                )
                repair_round += 1
                results.extend(round_results)
            remaining_llm_actions.extend(current_batch)

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
                else:
                    unresolved_by_index.pop(action_index, None)

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
