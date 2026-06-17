"""Static HTML figure assets for DocGen chapters."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.shared.infra.storage import get_content_store, resolve_course_storage_scope
from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.utils.path_helpers import sanitize_doc_title
from app.workflows.digest.docgen.lib.figure_spec import (
    FigureSpec,
    assess_static_figure_layout,
    is_renderable_static_figure,
    normalize_figure_spec,
    render_figure_spec_html,
)
from app.workflows.digest.docgen.lib.html_sidecar import normalize_single_file_html
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger
from app.workflows.digest.docgen.prompts.static_html_figure import build_static_html_figure_messages

logger = structlog.get_logger(__name__)

_ANY_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class _StaticFigureCandidate:
    index: int
    heading_id: str
    title: str
    level: int
    context: str
    insert_at: int
    score: int
    goal: str
    figure_type: str


def _plain_heading_text(raw: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", str(raw or ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _heading_text_to_id(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(text or "").strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "section"


def _sanitize_static_html(html: str, *, title: str) -> str:
    return normalize_single_file_html(html, title=title, allow_scripts=False)


def _build_preview_url(*, course_id: str, asset_path: str, title: str) -> str:
    from urllib.parse import quote

    return (
        f"/courses/{quote(course_id)}/knowledge-docs/html-figure"
        f"?asset={quote(asset_path, safe='/')}"
        f"&title={quote(title)}"
    )


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


def _score_static_figure_signal(title: str, context: str) -> tuple[int, str, str]:
    score = 0
    reasons: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(reason)

    compact_context = re.sub(r"\s+", "", context)
    content_len = len(compact_context)
    sentence_count = len([item for item in re.split(r"[。！？!?；;]\s*", context) if item.strip()])
    structured_item_count = len(re.findall(r"[-*]\s+|^\s*\d+[).、]", context, flags=re.MULTILINE))

    if content_len >= 180:
        add(2, "片段信息量足够")
    if sentence_count >= 3:
        add(2, "包含多句连续说明")
    if structured_item_count >= 2:
        add(1, "片段有列表或编号结构")

    if content_len >= 240 and score:
        score += 1
    score = max(0, min(10, score))
    if score < 3:
        return score, "", "auto"
    goal = (
        "请由模型判断这段是否存在文字难以表达的空间、数量、状态、结构或几何关系；"
        "若只是普通步骤、公式罗列或概念摘要，必须返回空 elements。"
    )
    if reasons:
        goal = f"{goal} 候选原因：{'；'.join(reasons[:2])}。"
    return score, goal, "auto"


def _iter_static_figure_candidates(markdown: str, *, fallback_title: str) -> list[_StaticFigureCandidate]:
    text = str(markdown or "")
    headings = list(_ANY_HEADING_RE.finditer(text))
    candidates: list[_StaticFigureCandidate] = []
    heading_counts: dict[str, int] = {}
    for heading_index, heading in enumerate(headings):
        level = len(heading.group("marks"))
        title = _plain_heading_text(heading.group("title"))
        if level not in {2, 3, 4} or not title:
            continue
        base_heading_id = _heading_text_to_id(title)
        heading_count = heading_counts.get(base_heading_id, 0) + 1
        heading_counts[base_heading_id] = heading_count
        heading_id = base_heading_id if heading_count == 1 else f"{base_heading_id}-{heading_count}"
        end = _section_end_for_heading(headings, heading_index, len(text))
        body = text[heading.end() : end].strip()
        context = f"{title}\n\n{body[:2200].rstrip()}".strip()
        score, goal, figure_type = _score_static_figure_signal(title, context)
        candidates.append(
            _StaticFigureCandidate(
                index=len(candidates) + 1,
                heading_id=heading_id,
                title=title,
                level=level,
                context=context,
                insert_at=end,
                score=score,
                goal=goal,
                figure_type=figure_type,
            )
        )

    if candidates:
        return candidates

    fallback_context = re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()[:2200]
    fallback_heading = _plain_heading_text(fallback_title)
    if not fallback_context or not fallback_heading:
        return []
    score, goal, figure_type = _score_static_figure_signal(fallback_title, fallback_context)
    return [
        _StaticFigureCandidate(
            index=1,
            heading_id=_heading_text_to_id(fallback_title),
            title=fallback_heading,
            level=1,
            context=fallback_context,
            insert_at=len(text),
            score=score,
            goal=goal,
            figure_type=figure_type,
        )
    ]


def _select_static_figure_candidates(
    markdown: str,
    *,
    fallback_title: str,
    max_assets: int = 1,
) -> list[_StaticFigureCandidate]:
    candidates = _iter_static_figure_candidates(markdown, fallback_title=fallback_title)
    qualified = [item for item in candidates if len(re.sub(r"\s+", "", item.context)) >= 40]
    if not qualified:
        return []

    selected: list[_StaticFigureCandidate] = []
    attempt_limit = max(1, min(len(qualified), max_assets * 4))
    for item in sorted(qualified, key=lambda candidate: candidate.insert_at):
        if any(abs(item.insert_at - existing.insert_at) < 160 for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= attempt_limit:
            break
    return selected


def _compact_visual_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _coordinate_bucket(value: float) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 50.0
    return int(round(parsed / 8.0) * 8)


def _figure_spec_visual_signature(spec: FigureSpec) -> str:
    """Return a stable visual signature used to skip repeated sidecar figures."""

    parts: list[str] = [str(spec.type)]
    for item in spec.elements[:18]:
        label = _compact_visual_text(item.label or item.text)
        if item.kind == "shape":
            node_key = _compact_visual_text(item.id or item.label)
            parts.append(f"shape:{item.shape_type}:{node_key}:{label}")
            continue
        if item.kind in {"line", "vector"}:
            start = _compact_visual_text(item.from_id)
            end = _compact_visual_text(item.to_id)
            if start or end:
                parts.append(f"{item.kind}:{start}->{end}:{label}")
            else:
                parts.append(
                    f"{item.kind}:{_coordinate_bucket(item.x)},{_coordinate_bucket(item.y)}"
                    f"->{_coordinate_bucket(item.x2)},{_coordinate_bucket(item.y2)}:{label}"
                )
            continue
        if item.kind in {"axis", "curve", "point"}:
            parts.append(
                f"{item.kind}:{_coordinate_bucket(item.x)},{_coordinate_bucket(item.y)}"
                f":{_coordinate_bucket(item.x2)},{_coordinate_bucket(item.y2)}:{label}"
            )
            continue
        if label:
            parts.append(f"{item.kind}:{label}")
    return "|".join(part for part in parts if part)


async def generate_static_html_figure_assets(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    markdown: str,
    claim_ledger: ClaimLedger | None = None,
    max_assets: int = 1,
    used_visual_signatures: set[str] | None = None,
) -> list[dict[str, object]]:
    candidates = _select_static_figure_candidates(
        markdown,
        fallback_title=draft.title,
        max_assets=max_assets,
    )
    if not candidates:
        return []

    claim_targets = [
        item.claim_text
        for item in list((claim_ledger or ClaimLedger()).items or [])
        if item.claim_text
    ][:4]
    stored_visual_signatures = used_visual_signatures if used_visual_signatures is not None else set()

    async def _generate_one(candidate: _StaticFigureCandidate) -> dict[str, object] | None:
        figure_title = f"{candidate.title} 图示"
        context = "\n".join([candidate.context, *claim_targets]).strip()
        spec_validation: dict[str, object] = {}

        def _normalize_model_spec(raw_spec: FigureSpec) -> FigureSpec:
            normalized, validation = normalize_figure_spec(
                raw_spec,
                fallback_title=figure_title,
                context=context,
                allow_fallback_elements=False,
            )
            spec_validation.update(validation)
            if is_renderable_static_figure(normalized):
                return normalized
            warnings = list(spec_validation.get("warnings") or [])
            warnings.append("model_returned_nonvisual_or_unsafe_figure")
            spec_validation["warnings"] = warnings
            logger.warning(
                "docgen_static_html_figure_skipped_after_nonvisual_spec",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=candidate.title,
                figure_type=normalized.type,
                element_kinds=[item.kind for item in normalized.elements[:8]],
            )
            return normalized

        async def _store_spec(spec: FigureSpec) -> dict[str, object] | None:
            if not is_renderable_static_figure(spec):
                return None
            layout_report = assess_static_figure_layout(spec)
            spec_validation["layout_quality"] = layout_report
            if not layout_report.get("ok"):
                logger.warning(
                    "docgen_static_html_figure_skipped_after_layout_audit",
                    chapter_index=draft.chapter_index,
                    chapter_title=draft.title,
                    section_title=candidate.title,
                    layout_issues=layout_report.get("issues"),
                    layout_metrics=layout_report.get("metrics"),
                )
                return None
            html = render_figure_spec_html(spec, title=figure_title)
            cleaned_html = _sanitize_static_html(str(html), title=figure_title)
            validation_issues = validate_single_file_html(cleaned_html)
            if validation_issues:
                logger.warning(
                    "docgen_static_html_figure_skipped_after_validation",
                    chapter_index=draft.chapter_index,
                    chapter_title=draft.title,
                    section_title=candidate.title,
                    validation_issues=validation_issues,
                )
                return None

            visual_signature = _figure_spec_visual_signature(spec)
            spec_validation["visual_signature"] = visual_signature[:240]
            if visual_signature in stored_visual_signatures:
                logger.warning(
                    "docgen_static_html_figure_skipped_after_duplicate_signature",
                    chapter_index=draft.chapter_index,
                    chapter_title=draft.title,
                    section_title=candidate.title,
                )
                return None
            stored_visual_signatures.add(visual_signature)

            cs = get_content_store()
            course_scope = resolve_course_storage_scope(traced_context.course_id)
            filename = (
                f"docgen_figure_{traced_context.build_session_id}_ch{draft.chapter_index:02d}"
                f"_s{candidate.index:02d}_{sanitize_doc_title(candidate.title)}.html"
            )
            storage_key = f"{course_scope.namespace}/assets/docgen/figures/{filename}"
            asset_path = f"docgen/figures/{filename}"
            await cs.write_text(storage_key, cleaned_html)
            preview_url = _build_preview_url(
                course_id=traced_context.course_id,
                asset_path=asset_path,
                title=figure_title,
            )
            return {
                "asset_id": f"ch{draft.chapter_index:02d}_figure_{candidate.index:02d}",
                "chapter_index": draft.chapter_index,
                "kind": "static_html_figure",
                "title": figure_title,
                "anchor_heading": candidate.title,
                "anchor_heading_id": candidate.heading_id,
                "anchor_heading_level": candidate.level,
                "insert_at": candidate.insert_at,
                "storage_key": storage_key,
                "asset_path": asset_path,
                "asset_url": f"/api/v1/courses/{traced_context.course_id}/files/assets/{asset_path}",
                "preview_url": preview_url,
                "open_mode": "inline_static",
                "link_markdown": f"[图示：{candidate.title}]({preview_url})",
                "validation_issues": validation_issues,
                "figure_type": spec.type,
                "figure_spec": spec.model_dump(mode="json"),
                "validation_report": spec_validation,
            }

        try:
            response = await acompletion_with_fallback(
                build_static_html_figure_messages(
                    figure_title=figure_title,
                    figure_goal=candidate.goal,
                    figure_type=candidate.figure_type,
                    digest_mode=digest_mode,
                    section_context=context,
                ),
                response_model=FigureSpec,
                **docgen_completion_kwargs_with_metadata(
                    DocGenModelStep.STATIC_HTML_FIGURE,
                    digest_mode=digest_mode,
                    extra_metadata=traced_context.trace_metadata(
                        docgen_stage="static_html_figure",
                        asset_kind="static_html_figure",
                        chapter_index=draft.chapter_index,
                        section_index=candidate.index,
                        section_title=candidate.title,
                    ),
                ),
            )
            raw_spec = response if isinstance(response, FigureSpec) else FigureSpec.model_validate(response)
            return await _store_spec(_normalize_model_spec(raw_spec))
        except Exception as exc:
            warnings = list(spec_validation.get("warnings") or [])
            warnings.append("model_error_no_fallback_figure")
            spec_validation["warnings"] = warnings
            logger.warning(
                "docgen_static_html_figure_skipped_after_error",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=candidate.title,
                error=str(exc)[:240],
            )
            return None

    results = await run_llm_tasks(
        candidates,
        _generate_one,
    )
    return [item for item in results if item is not None][: max(1, max_assets)]


__all__ = ["generate_static_html_figure_assets"]
