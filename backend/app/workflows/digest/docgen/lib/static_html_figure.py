"""Static HTML figure assets for DocGen chapters."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

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
    figure_type: FigureType = "concept_map"

    def add(points: int, reason: str, kind: FigureType) -> None:
        nonlocal score, figure_type
        score += points
        reasons.append(reason)
        if points >= 3 or figure_type == "concept_map":
            figure_type = kind

    has_problem_signal = bool(
        re.search(
            r"图示|如下图|如图|画出|示意图|题图|坐标|函数|几何|三角|圆|斜面|地图|曲线|图像|图象|结构|模型|区域|轴|路径|方向|向量|矢量",
            text,
        )
    )
    has_quantitative_signal = bool(
        re.search(r"力|合力|分力|力矩|力偶|约束|速度|加速度|电场|磁场|函数|坐标|概率|统计|供给|需求|曲线|成本|收益|面积|体积|角度|距离", text)
    )
    if has_problem_signal:
        add(4, "包含题图、坐标、结构或空间关系", "problem_diagram")
    if has_problem_signal and has_quantitative_signal:
        add(2, "图示与变量或数量关系需要对应标注", "problem_diagram")
    has_process_signal = bool(re.search(r"步骤|流程|顺序|阶段|时期|时间线|先.*再|首先|然后|最后|第一|第二|第三|①|②|③|1[).、]|2[).、]|3[).、]", text))
    has_comparison_signal = bool(re.search(r"比较|区别|对比|分类|适用范围|优缺点|表格|类型|性质|相同|不同|异同", text))
    if has_process_signal:
        add(4, "包含步骤、阶段或过程关系", "process_steps")
        if len(re.findall(r"阶段|时期|首先|然后|最后|第一|第二|第三|①|②|③", text)) >= 2:
            add(2, "多个阶段适合画成顺序图", "process_steps")
    if has_comparison_signal:
        add(4, "适合整理为对比表或归纳表", "comparison_table")
        if len(re.findall(r"、|，|,|；|;", context)) >= 3:
            add(1, "包含多项维度可归纳", "comparison_table")
    if re.search(r"=|\\frac|\\sum|\\sqrt|公式|推导|表达式|代入|化简|因此|所以|⇒|->|→", text):
        add(3, "包含公式、推导或等量关系", "formula_derivation")
    if re.search(r"易错|注意|误区|错误|判断|陷阱|常见", text):
        add(2, "包含易错点或判断提示", "mistake_card")
    if re.search(r"定义|概念|含义|本质|特点|作用|关系", text):
        add(1, "包含概念关系", "concept_map")

    if len(context) < 180 and not (
        (has_problem_signal and has_quantitative_signal)
        or has_process_signal
        or has_comparison_signal
    ):
        score -= 2
    if len(re.findall(r"[-*]\s+|^\s*\d+[).、]", context, flags=re.MULTILINE)) >= 3:
        score += 1
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
            spec = response if isinstance(response, FigureSpec) else FigureSpec.model_validate(response)
            spec, spec_validation = normalize_figure_spec(
                spec,
                fallback_title=figure_title,
                context=context,
            )
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
        except Exception as exc:
            logger.warning(
                "docgen_static_html_figure_skipped_after_error",
                chapter_index=draft.chapter_index,
                chapter_title=draft.title,
                section_title=candidate.title,
                error=str(exc)[:240],
            )
            try:
                spec = build_fallback_figure_spec(
                    title=figure_title,
                    figure_type=cast(FigureType, candidate.figure_type),
                    context=context,
                    goal=candidate.goal,
                )
                cleaned_html = _sanitize_static_html(
                    render_figure_spec_html(spec, title=figure_title),
                    title=figure_title,
                )
                validation_issues = validate_single_file_html(cleaned_html)
                if validation_issues:
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
                    "validation_report": {"fallback_after_error": str(exc)[:160]},
                }
            except Exception:
                return None

    results = await run_llm_tasks(
        candidates,
        _generate_one,
    )
    return [item for item in results if item is not None]


__all__ = ["generate_static_html_figure_assets"]
