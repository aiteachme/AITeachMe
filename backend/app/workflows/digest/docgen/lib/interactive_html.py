"""Interactive HTML sidecar generation for DocGen chapter enhancement."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal

import structlog

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.shared.infra.storage import CourseStorageScope, get_content_store, resolve_course_storage_scope
from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.utils.path_helpers import sanitize_doc_title
from app.workflows.digest.docgen.lib.html_sidecar import normalize_single_file_html
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger, DocumentBackbone
from app.workflows.digest.docgen.prompts.interactive_html import (
    build_interactive_html_messages,
    build_selection_interactive_html_messages,
)

logger = structlog.get_logger(__name__)

InteractiveMode = Literal["parameter_explorer", "process_stepper", "concept_mapper"]

_VISUAL_STRONG_MARKERS = (
    "函数",
    "图像",
    "几何",
    "空间",
    "导数",
    "微分",
    "积分",
    "方程",
    "概率",
    "分布",
    "变化",
    "单调性",
    "极值",
    "轨迹",
    "流程",
    "机制",
    "结构",
    "关系",
    "模拟",
    "实验",
)
_VISUAL_WEAK_MARKERS = (
    "公式",
    "定理",
    "性质",
    "方法",
    "步骤",
    "路径",
    "模型",
    "判定",
)
_EXCLUDE_MARKERS = (
    "提分策略",
    "易错点汇总",
    "复盘",
    "总结",
    "概述",
    "导论",
)
_ANY_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)
_INTERACTIVE_TITLE_MARKERS = (
    "图",
    "函数",
    "变化",
    "关系",
    "步骤",
    "流程",
    "推导",
    "计算",
    "换算",
    "比较",
    "辨析",
    "应用",
    "案例",
    "实验",
    "模拟",
)
_INTERACTIVE_LOW_VALUE_MARKERS = (
    "快速检测",
    "检测题",
    "自测",
    "练习",
    "总结",
    "复盘",
)


@dataclass(frozen=True)
class _InteractiveSectionCandidate:
    index: int
    heading_id: str
    title: str
    level: int
    context: str
    insert_at: int
    score: float


def _normalize_blob(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _plain_heading_text(raw: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", str(raw or ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _heading_text_to_id(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(text or "").strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "section"


def _build_signal_text(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
) -> str:
    claims = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text][:6]
    return "\n".join(
        [
            draft.title,
            draft.summary_draft,
            *claims,
            *[str(item.get("description") or "") for item in draft.placeholder_requests if isinstance(item, dict)],
        ]
    )


def _score_interactive_signal(title: str, context: str) -> float:
    signal = "\n".join([title, context])
    normalized = _normalize_blob(signal)
    strong_hits = sum(1 for marker in _VISUAL_STRONG_MARKERS if _normalize_blob(marker) in normalized)
    weak_hits = sum(1 for marker in _VISUAL_WEAK_MARKERS if _normalize_blob(marker) in normalized)
    formula_count = min(5, context.count("$$") + context.count("$"))
    score = strong_hits * 5 + weak_hits * 2 + formula_count
    if any(marker in title for marker in _INTERACTIVE_TITLE_MARKERS):
        score += 4
    if any(marker in title for marker in _INTERACTIVE_LOW_VALUE_MARKERS):
        score -= 4
    if any(_normalize_blob(marker) in normalized for marker in _EXCLUDE_MARKERS):
        score -= 5
    if len(_normalize_blob(context)) < 120:
        score -= 2
    return score


def _section_end_for_heading(
    headings: Sequence[re.Match[str]],
    heading_index: int,
    markdown_len: int,
) -> int:
    current_level = len(headings[heading_index].group("marks"))
    for candidate in headings[heading_index + 1 :]:
        if len(candidate.group("marks")) <= current_level:
            return candidate.start()
    return markdown_len


def _iter_interactive_section_candidates(markdown: str, *, fallback_title: str) -> list[_InteractiveSectionCandidate]:
    text = str(markdown or "")
    headings = list(_ANY_HEADING_RE.finditer(text))
    candidates: list[_InteractiveSectionCandidate] = []
    heading_counts: dict[str, int] = {}
    for heading_index, heading in enumerate(headings):
        level = len(heading.group("marks"))
        title = _plain_heading_text(heading.group("title"))
        if not title:
            continue
        base_heading_id = _heading_text_to_id(title)
        heading_count = heading_counts.get(base_heading_id, 0) + 1
        heading_counts[base_heading_id] = heading_count
        heading_id = base_heading_id if heading_count == 1 else f"{base_heading_id}-{heading_count}"
        if level not in {2, 3}:
            continue
        end = _section_end_for_heading(headings, heading_index, len(text))
        body = text[heading.end() : end].strip()
        context = f"{title}\n\n{body[:2400].rstrip()}".strip()
        candidates.append(
            _InteractiveSectionCandidate(
                index=len(candidates) + 1,
                heading_id=heading_id,
                title=title,
                level=level,
                context=context,
                insert_at=end,
                score=_score_interactive_signal(title, context),
            )
        )

    if candidates:
        return candidates

    fallback_context = _chapter_context_excerpt_from_markdown(text)
    return [
        _InteractiveSectionCandidate(
            index=1,
            heading_id=_heading_text_to_id(fallback_title),
            title=_plain_heading_text(fallback_title) or "本章核心概念",
            level=1,
            context=fallback_context,
            insert_at=len(text),
            score=_score_interactive_signal(fallback_title, fallback_context),
        )
    ] if fallback_context else []


def _select_interactive_section_candidates(
    markdown: str,
    *,
    fallback_title: str,
    max_count: int = 3,
) -> list[_InteractiveSectionCandidate]:
    candidates = _iter_interactive_section_candidates(markdown, fallback_title=fallback_title)
    if not candidates:
        return []

    positive = [item for item in candidates if item.score > 0]
    pool = positive or candidates
    target_count = 1
    if len(pool) >= 8:
        target_count = 3
    elif len(pool) >= 3:
        target_count = 2
    target_count = max(1, min(max_count, target_count, len(pool)))

    selected: list[_InteractiveSectionCandidate] = []
    for item in sorted(pool, key=lambda candidate: (-candidate.score, candidate.insert_at)):
        if any(abs(item.insert_at - existing.insert_at) < 80 for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= target_count:
            break

    return sorted(selected or pool[:1], key=lambda candidate: candidate.insert_at)


def choose_interactive_mode(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
) -> InteractiveMode:
    text = _build_signal_text(draft, claim_ledger=claim_ledger)
    if any(marker in text for marker in ("步骤", "方法", "流程", "推导", "计算", "求解", "操作")):
        return "process_stepper"
    if any(marker in text for marker in ("结构", "关系", "依赖", "网络", "概念图")):
        return "concept_mapper"
    return "parameter_explorer"


def should_generate_interactive_html(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
) -> bool:
    del claim_ledger, document_backbone
    return bool(_select_interactive_section_candidates(draft.markdown, fallback_title=draft.title))


def _chapter_context_excerpt(draft: ChapterDraft, *, limit: int = 2200) -> str:
    return _chapter_context_excerpt_from_markdown(draft.markdown, limit=limit)


def _chapter_context_excerpt_from_markdown(markdown: str, *, limit: int = 2200) -> str:
    text = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit].rstrip()


def _sanitize_generated_html(html: str, *, title: str) -> str:
    return normalize_single_file_html(html, title=title, allow_scripts=True)


def _build_preview_url(*, course_id: str, asset_path: str, title: str) -> str:
    from urllib.parse import quote

    return (
        f"/courses/{quote(course_id)}/knowledge-docs/interactive"
        f"?asset={quote(asset_path, safe='/')}"
        f"&title={quote(title)}"
    )


def _build_auto_preview_url(
    *,
    course_id: str,
    plan_id: str,
    anchor_id: str,
    title: str,
    selected_text: str,
    prompt: str,
) -> str:
    from urllib.parse import quote

    return (
        f"/courses/{quote(course_id)}/knowledge-docs/interactive-auto"
        f"?plan={quote(plan_id)}"
        f"&anchor={quote(anchor_id)}"
        f"&title={quote(title)}"
        f"&selected={quote(selected_text[:900])}"
        f"&prompt={quote(prompt[:500])}"
    )


def _build_markdown_link(*, preview_url: str, link_label: str) -> str:
    return f"[{link_label}]({preview_url})"


def build_interactive_markdown_link(*, preview_url: str, link_label: str) -> str:
    return _build_markdown_link(preview_url=preview_url, link_label=link_label)


def _selection_title(*, anchor_title: str, selected_text: str, user_prompt: str) -> str:
    seed = (user_prompt or selected_text or anchor_title or "交互演示").strip()
    seed = re.sub(r"\s+", " ", seed)
    if len(seed) > 28:
        seed = seed[:28].rstrip() + "..."
    return seed or "交互演示"


async def generate_selection_interactive_html_asset(
    *,
    course_id: str,
    course_scope: CourseStorageScope | None = None,
    traced_context: TracedExecutionContext,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
) -> dict[str, object]:
    title = _selection_title(
        anchor_title=anchor_title,
        selected_text=selected_text,
        user_prompt=user_prompt,
    )
    html = await acompletion_with_fallback(
        build_selection_interactive_html_messages(
            anchor_title=anchor_title,
            heading_path=heading_path,
            selected_text=selected_text,
            user_prompt=user_prompt,
            section_excerpt=section_excerpt,
        ),
        **docgen_completion_kwargs_with_metadata(
            DocGenModelStep.INTERACTIVE_HTML,
            digest_mode=traced_context.digest_mode or "",
            extra_metadata=traced_context.trace_metadata(
                docgen_stage="interactive_html_selection",
                asset_kind="interactive_html",
            ),
        ),
    )
    cleaned_html = _sanitize_generated_html(str(html), title=title)
    validation_issues = validate_single_file_html(cleaned_html)
    if validation_issues:
        raise ValueError("generated interactive HTML failed validation: " + "; ".join(validation_issues))

    cs = get_content_store()
    course_scope = course_scope or resolve_course_storage_scope(course_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"selection_interactive_{timestamp}_{uuid.uuid4().hex[:8]}_{sanitize_doc_title(title)}.html"
    storage_key = f"{course_scope.namespace}/assets/docgen/interactive/{filename}"
    asset_path = f"docgen/interactive/{filename}"
    await cs.write_text(storage_key, cleaned_html)
    preview_url = _build_preview_url(course_id=course_id, asset_path=asset_path, title=title)
    return {
        "title": title,
        "storage_key": storage_key,
        "asset_path": asset_path,
        "asset_url": f"/api/v1/courses/{course_id}/files/assets/{asset_path}",
        "preview_url": preview_url,
        "link_markdown": _build_markdown_link(preview_url=preview_url, link_label=title),
        "validation_issues": validation_issues,
    }


async def maybe_generate_interactive_html_asset(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
    markdown: str | None = None,
) -> dict[str, object] | None:
    assets = await maybe_generate_interactive_html_assets(
        draft=draft,
        traced_context=traced_context,
        digest_mode=digest_mode,
        claim_ledger=claim_ledger,
        document_backbone=document_backbone,
        markdown=markdown,
        max_assets=1,
    )
    return assets[0] if assets else None


def plan_interactive_html_assets(
    *,
    draft: ChapterDraft,
    course_id: str,
    markdown: str | None = None,
    max_assets: int = 3,
) -> list[dict[str, object]]:
    working_markdown = markdown if markdown is not None else draft.markdown
    candidates = _select_interactive_section_candidates(
        working_markdown,
        fallback_title=draft.title,
        max_count=max_assets,
    )
    plans: list[dict[str, object]] = []
    for candidate in candidates:
        plan_id = f"ch{draft.chapter_index:02d}_interactive_{candidate.index:02d}"
        title = candidate.title or draft.title
        link_label = f"{title} 交互演示"
        preview_url = _build_auto_preview_url(
            course_id=course_id,
            plan_id=plan_id,
            anchor_id=candidate.heading_id,
            title=link_label,
            selected_text=candidate.context or title,
            prompt="",
        )
        plans.append(
            {
                "asset_id": plan_id,
                "chapter_index": draft.chapter_index,
                "kind": "interactive",
                "status": "planned",
                "title": link_label,
                "anchor_heading": title,
                "anchor_heading_id": candidate.heading_id,
                "anchor_heading_level": candidate.level,
                "insert_at": candidate.insert_at,
                "preview_url": preview_url,
                "open_mode": "inline_lazy",
                "link_markdown": (
                    f"<!-- ATM_INTERACTIVE_PLAN:{plan_id} -->\n"
                    f"{_build_markdown_link(preview_url=preview_url, link_label=link_label)}"
                ),
            }
        )
    return plans


async def maybe_generate_interactive_html_assets(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
    markdown: str | None = None,
    max_assets: int = 3,
) -> list[dict[str, object]]:
    del document_backbone
    working_markdown = markdown if markdown is not None else draft.markdown
    candidates = _select_interactive_section_candidates(
        working_markdown,
        fallback_title=draft.title,
        max_count=max_assets,
    )
    if not candidates:
        return []

    interaction_mode = choose_interactive_mode(draft, claim_ledger=claim_ledger)
    concept_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type in {"definition", "core", "method"}][:4]
    formula_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type == "formula"][:3]
    claim_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text][:5]

    async def _generate_one(candidate: _InteractiveSectionCandidate) -> dict[str, object] | None:
        title = candidate.title or draft.title
        html = await acompletion_with_fallback(
            build_interactive_html_messages(
                chapter_title=title,
                chapter_objective=draft.summary_draft,
                digest_mode=digest_mode,
                interaction_mode=interaction_mode,
                concept_targets=concept_targets,
                formula_targets=formula_targets,
                claim_targets=claim_targets,
                chapter_context=candidate.context or _chapter_context_excerpt(draft),
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.INTERACTIVE_HTML,
                digest_mode=digest_mode,
                extra_metadata=traced_context.trace_metadata(
                    docgen_stage="interactive_html_sidecar",
                    asset_kind="interactive_html",
                    chapter_index=draft.chapter_index,
                    section_index=candidate.index,
                    section_title=title,
                ),
            ),
        )
        cleaned_html = _sanitize_generated_html(str(html), title=title)
        validation_issues = validate_single_file_html(cleaned_html)
        if validation_issues:
            logger.warning(
                "docgen_interactive_html_skipped_after_validation",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=title,
                validation_issues=validation_issues,
            )
            return None
        cs = get_content_store()
        course_scope = resolve_course_storage_scope(traced_context.course_id)
        filename = (
            f"docgen_interactive_{traced_context.build_session_id}_ch{draft.chapter_index:02d}"
            f"_s{candidate.index:02d}_{sanitize_doc_title(title)}.html"
        )
        storage_key = f"{course_scope.namespace}/assets/docgen/interactive/{filename}"
        asset_path = f"docgen/interactive/{filename}"
        await cs.write_text(storage_key, cleaned_html)
        preview_url = _build_preview_url(course_id=traced_context.course_id, asset_path=asset_path, title=title)
        link_label = f"{title} 交互演示"
        return {
            "asset_id": f"ch{draft.chapter_index:02d}_interactive_{candidate.index:02d}",
            "chapter_index": draft.chapter_index,
            "kind": "interactive",
            "title": link_label,
            "interaction_mode": interaction_mode,
            "anchor_heading": title,
            "anchor_heading_level": candidate.level,
            "insert_at": candidate.insert_at,
            "storage_key": storage_key,
            "asset_path": asset_path,
            "asset_url": f"/api/v1/courses/{traced_context.course_id}/files/assets/{asset_path}",
            "preview_url": preview_url,
            "open_mode": "inline",
            "link_markdown": _build_markdown_link(preview_url=preview_url, link_label=link_label),
            "validation_issues": validation_issues,
        }

    results = await run_llm_tasks(
        candidates,
        _generate_one,
        limit=min(3, max(1, len(candidates))),
    )
    return [item for item in results if item is not None]


__all__ = [
    "build_interactive_markdown_link",
    "choose_interactive_mode",
    "generate_selection_interactive_html_asset",
    "maybe_generate_interactive_html_asset",
    "maybe_generate_interactive_html_assets",
    "plan_interactive_html_assets",
    "should_generate_interactive_html",
]
