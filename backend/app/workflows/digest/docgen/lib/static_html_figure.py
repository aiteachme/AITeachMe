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
from app.workflows.digest.docgen.lib.html_sidecar import normalize_single_file_html
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger
from app.workflows.digest.docgen.prompts.static_html_figure import build_static_html_figure_messages

logger = structlog.get_logger(__name__)

_ANY_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)

_FIGURE_STRONG_MARKERS = (
    "函数",
    "图像",
    "坐标",
    "直线",
    "曲线",
    "抛物线",
    "斜率",
    "数轴",
    "几何",
    "三角形",
    "四边形",
    "圆",
    "角",
    "边",
    "辅助线",
    "面积",
    "周长",
    "体积",
    "向量",
    "波形",
    "正弦",
    "余弦",
    "频率",
    "幅度",
    "单位换算",
    "比例尺",
    "统计图",
    "分布图",
)
_FIGURE_WEAK_MARKERS = (
    "变化",
    "比较",
    "对应",
    "位置",
    "距离",
    "高度",
    "长度",
    "方向",
    "交点",
    "轨迹",
    "范围",
    "示意",
)
_STRUCTURE_ONLY_MARKERS = (
    "结构关系",
    "流程",
    "层次",
    "机制",
    "路径",
    "知识图谱",
)
_LOW_VALUE_MARKERS = (
    "总结",
    "复盘",
    "快速检测",
    "自测",
    "概述",
    "导论",
)


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


def _score_static_figure_signal(title: str, context: str) -> tuple[int, str]:
    signal = "\n".join([title, context])
    normalized = _normalize_blob(signal)
    strong_hits = [marker for marker in _FIGURE_STRONG_MARKERS if _normalize_blob(marker) in normalized]
    weak_hits = [marker for marker in _FIGURE_WEAK_MARKERS if _normalize_blob(marker) in normalized]
    score = len(strong_hits) * 5 + len(weak_hits) * 2
    if any(_normalize_blob(marker) in normalized for marker in _STRUCTURE_ONLY_MARKERS):
        score -= 4
    if any(marker in title for marker in _LOW_VALUE_MARKERS):
        score -= 5
    if "```mermaid" in context or "knowledge-docs/interactive" in context:
        score -= 3
    if len(_normalize_blob(context)) < 160:
        score -= 3
    if not strong_hits:
        score -= 4
    goal_terms = "、".join(strong_hits[:3] or weak_hits[:3]) or "关键图形关系"
    return score, f"用静态图示呈现：{goal_terms}"


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
        score, goal = _score_static_figure_signal(title, context)
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
            )
        )

    if candidates:
        return candidates

    fallback_context = re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()[:2200]
    if not fallback_context:
        return []
    score, goal = _score_static_figure_signal(fallback_title, fallback_context)
    return [
        _StaticFigureCandidate(
            index=1,
            heading_id=_heading_text_to_id(fallback_title),
            title=_plain_heading_text(fallback_title) or "本章图示",
            level=1,
            context=fallback_context,
            insert_at=len(text),
            score=score,
            goal=goal,
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
            html = await acompletion_with_fallback(
                build_static_html_figure_messages(
                    figure_title=figure_title,
                    figure_goal=candidate.goal,
                    digest_mode=digest_mode,
                    section_context=context,
                ),
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
            }
        except Exception as exc:
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
        max_concurrent=min(2, max(1, len(candidates))),
    )
    return [item for item in results if item is not None]


__all__ = ["generate_static_html_figure_assets"]
