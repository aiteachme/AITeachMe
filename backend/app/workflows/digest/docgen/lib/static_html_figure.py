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
    FigureType,
    build_fallback_figure_spec,
    is_renderable_problem_diagram,
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
    figure_type: FigureType


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


def _score_static_figure_signal(title: str, context: str) -> tuple[int, str, FigureType]:
    text = f"{title}\n{context}".lower()
    score = 0
    reasons: list[str] = []
    figure_type: FigureType = "problem_diagram"

    def add(points: int, reason: str) -> None:
        nonlocal score, figure_type
        score += points
        reasons.append(reason)
        figure_type = "problem_diagram"

    has_problem_signal = bool(
        re.search(
            r"图示|如下图|如图|画出|示意|题图|坐标|曲线|图像|图象|抛物线|几何|三角|圆|椭圆|斜面|地图|结构|模型|装置|区域|轴|路径|方向|向量|矢量|电路|受力|力图|示波|流程图|树状图|网络图",
            text,
        )
    )
    has_quantitative_signal = bool(
        re.search(r"力|合力|分力|力矩|力偶|约束|速度|加速度|电场|磁场|函数|坐标|概率|统计|供给|需求|曲线|成本|收益|面积|体积|角度|距离|半径|焦点|边长|高度|电压|电流", text)
    )
    if has_problem_signal:
        add(4, "包含题图、坐标、结构或空间关系")
    if has_problem_signal and has_quantitative_signal:
        add(2, "图示与变量或数量关系需要对应标注")
    if has_problem_signal and re.search(r"=|\\frac|\\sum|\\sqrt|表达式|方程|函数|导数|切线|斜率|曲线|坐标|图像|图象|抛物线", text):
        add(2, "表达式或函数关系可落到坐标、曲线或标注图")

    if len(context) < 180 and not (
        (has_problem_signal and has_quantitative_signal)
        or has_problem_signal
    ):
        score -= 2
    if len(re.findall(r"[-*]\s+|^\s*\d+[).、]", context, flags=re.MULTILINE)) >= 3:
        score += 1 if has_problem_signal else 0
    score = max(0, min(10, score))
    if score < 6:
        return score, "", figure_type
    goal = "；".join(reasons[:3]) or "把正文里的关键关系画成讲义辅助图。"
    return score, goal, figure_type


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
    qualified = [item for item in candidates if item.score >= 6]
    if not qualified:
        return []

    selected: list[_StaticFigureCandidate] = []
    for item in sorted(qualified, key=lambda candidate: (-candidate.score, candidate.insert_at)):
        if any(abs(item.insert_at - existing.insert_at) < 160 for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= max(1, max_assets):
            break
    return sorted(selected, key=lambda candidate: candidate.insert_at)


async def generate_static_html_figure_assets(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    markdown: str,
    claim_ledger: ClaimLedger | None = None,
    max_assets: int = 1,
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

    async def _generate_one(candidate: _StaticFigureCandidate) -> dict[str, object] | None:
        figure_title = f"{candidate.title} 图示"
        context = "\n".join([candidate.context, *claim_targets]).strip()
        spec_validation: dict[str, object] = {}

        def _fallback_spec(reason: str) -> FigureSpec:
            fallback = build_fallback_figure_spec(
                title=figure_title,
                figure_type="problem_diagram",
                context=context,
                goal=candidate.goal,
            )
            normalized, validation = normalize_figure_spec(
                fallback,
                fallback_title=figure_title,
                context=context,
                allow_fallback_elements=False,
            )
            spec_validation["fallback_validation"] = validation
            warnings = list(spec_validation.get("warnings") or [])
            warnings.append(reason)
            spec_validation["warnings"] = warnings
            return normalized

        def _normalize_model_spec(raw_spec: FigureSpec) -> FigureSpec:
            forced = raw_spec.model_copy(update={"type": "problem_diagram"})
            normalized, validation = normalize_figure_spec(
                forced,
                fallback_title=figure_title,
                context=context,
                allow_fallback_elements=False,
            )
            spec_validation.update(validation)
            if is_renderable_problem_diagram(normalized):
                return normalized
            fallback = _fallback_spec("fallback_problem_diagram_used")
            if is_renderable_problem_diagram(fallback):
                return fallback
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
            if not is_renderable_problem_diagram(spec):
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
            logger.warning(
                "docgen_static_html_figure_skipped_after_error",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=candidate.title,
                error=str(exc)[:240],
            )
            return await _store_spec(_fallback_spec("fallback_after_model_error"))

    results = await run_llm_tasks(
        candidates,
        _generate_one,
    )
    return [item for item in results if item is not None]


__all__ = ["generate_static_html_figure_assets"]
