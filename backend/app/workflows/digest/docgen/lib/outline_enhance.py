"""Execution-level outline enhancement for DocGen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import re

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.common.pedagogy import resolve_effective_chapter_title
from app.workflows.digest.docgen.lib.models import (
    EnhancedChapterOutline,
    EnhancedChapterOutlineBatch,
    clean_string_list,
    clean_text,
)
from app.workflows.digest.docgen.prompts.outline_enhance import build_outline_enhance_messages

logger = structlog.get_logger(__name__)
_TITLE_STOPWORDS = {
    "数学",
    "知识",
    "学习",
    "章节",
    "核心",
    "内容",
    "基础",
    "应用",
    "模块",
    "策略",
    "理解",
    "方法",
    "讲解",
    "解析",
}


def _title_terms(value: str) -> set[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(value or "")).strip()
    terms: set[str] = set()
    for token in normalized.split():
        token = token.strip().casefold()
        if len(token) >= 3 and token not in _TITLE_STOPWORDS:
            terms.add(token)
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", normalized))
    for size in (4, 3, 2):
        for index in range(0, max(0, len(cjk) - size + 1)):
            item = cjk[index : index + size]
            if item and item not in _TITLE_STOPWORDS:
                terms.add(item)
    return terms


def _resolve_enhanced_title(
    candidate_title: str,
    *,
    confirmed_title: str,
    user_prompt: str,
    plan_summary: str,
) -> tuple[str, str | None]:
    candidate = clean_text(candidate_title)
    confirmed = clean_text(confirmed_title)
    if not candidate:
        return confirmed, None
    if len(candidate) > 32:
        return confirmed, f"标题 `{candidate}` 过长，已回退到 confirmed title。"
    if candidate == confirmed or candidate in confirmed or confirmed in candidate:
        return candidate, None

    user_terms = _title_terms(user_prompt)
    plan_terms = _title_terms(" ".join([confirmed, plan_summary]))
    candidate_terms = _title_terms(candidate)
    if candidate_terms & user_terms:
        return candidate, None
    if candidate_terms & plan_terms:
        return candidate, None
    return confirmed, f"标题 `{candidate}` 与用户提示和 confirmed plan 锚点不一致，已回退到 `{confirmed}`。"


def fallback_enhance_plan_outline(
    chapters: Sequence[Mapping[str, Any]],
    *,
    digest_mode: str,
) -> list[EnhancedChapterOutline]:
    normalized_mode = str(digest_mode or "").strip().lower()
    outlines: list[EnhancedChapterOutline] = []
    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        required = clean_string_list(chapter.get("required_elements", []), limit=8)
        objective = clean_text(chapter.get("objective")) or f"讲清《{title}》的核心知识和使用场景。"
        if normalized_mode == "sprint":
            teaching_outline = ["考点导读", "核心概念速判", "典型题型拆解", "易错点复盘", "本章自检"]
            example_targets = required[:3] or [title]
            pitfall_targets = ["混淆条件", "套公式不看适用范围", "只背结论不讲理由"]
        else:
            teaching_outline = ["章节导读", "关键概念与定义", "结构与推理路径", "例子和迁移", "本章小结"]
            example_targets = required[:2] or [title]
            pitfall_targets = ["定义边界", "推理跳步", "条件缺失"]
        media_requests = []
        if index == 1:
            media_requests.append({"kind": "mermaid", "description": f"{title} 的知识结构图"})
        visual_text = " ".join([title, *required, objective])
        if any(marker in visual_text for marker in ("公式", "推导", "证明", "计算", "定理")):
            media_requests.append({"kind": "interactive", "description": f"{title} 的公式推导展开器"})
        outlines.append(
            EnhancedChapterOutline(
                chapter_index=chapter_index,
                confirmed_title=title,
                enhanced_title=title,
                objective=objective,
                teaching_outline=teaching_outline,
                content_points=required or [objective],
                concept_targets=required[:5] or [title],
                definition_targets=required[:4] or [title],
                formula_targets=[item for item in required if any(marker in item for marker in ("公式", "定理", "性质"))],
                example_targets=example_targets,
                pitfall_targets=pitfall_targets,
                summary_targets=["用一句话说清本章主线", "列出最容易遗忘或混淆的点"],
                media_requests=media_requests,
                practice_seed_policy={"style": "exam" if normalized_mode == "sprint" else "reasoning"},
                retrieval_queries=clean_string_list([title, *required], limit=8),
                fallback_used=True,
            )
        )
    return outlines


def _coerce_outline_batch(
    batch: EnhancedChapterOutlineBatch,
    chapters: Sequence[Mapping[str, Any]],
    *,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
) -> tuple[list[EnhancedChapterOutline], list[str]]:
    fallback = {
        outline.chapter_index: outline
        for outline in fallback_enhance_plan_outline(chapters, digest_mode=digest_mode)
    }
    incoming = {int(item.chapter_index): item for item in batch.chapters if int(item.chapter_index) > 0}
    resolved: list[EnhancedChapterOutline] = []
    warnings = list(batch.plan_mismatch_warnings)
    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        base = fallback[chapter_index]
        candidate = incoming.get(chapter_index)
        if candidate is None:
            resolved.append(base)
            continue
        candidate.chapter_index = chapter_index
        candidate.confirmed_title = base.confirmed_title
        candidate.enhanced_title, title_warning = _resolve_enhanced_title(
            candidate.enhanced_title,
            confirmed_title=base.confirmed_title,
            user_prompt=user_prompt,
            plan_summary=plan_summary,
        )
        if title_warning:
            warnings.append(title_warning)
        if not candidate.objective:
            candidate.objective = base.objective
        if not candidate.teaching_outline:
            candidate.teaching_outline = base.teaching_outline
        if not candidate.content_points:
            candidate.content_points = base.content_points
        if not candidate.retrieval_queries:
            candidate.retrieval_queries = base.retrieval_queries
        resolved.append(candidate)
        warnings.extend(candidate.plan_mismatch_warnings)
    if len(incoming) != len(chapters):
        warnings.append("outline_enhance 返回章节数量与 confirmed plan 不一致，已按 confirmed plan 收口。")
    return resolved, list(dict.fromkeys(item for item in warnings if item))


async def enhance_plan_outline(
    *,
    subject: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> tuple[list[EnhancedChapterOutline], list[str]]:
    fallback = fallback_enhance_plan_outline(chapters, digest_mode=digest_mode)
    try:
        response = await acompletion_with_fallback(
            build_outline_enhance_messages(
                subject=subject,
                digest_mode=digest_mode,
                user_prompt=user_prompt,
                plan_summary=plan_summary,
                chapters=chapters,
                docgen_history_brief=docgen_history_brief,
            ),
            task_type=TaskType.REASONING,
            model="reason",
            response_model=EnhancedChapterOutlineBatch,
            temperature=0.15,
            max_tokens=5000,
            extra_metadata={"docgen_stage": "enhance_plan_outline", **dict(extra_metadata or {})},
        )
    except Exception as exc:
        logger.warning("docgen_outline_enhance_failed", error=str(exc))
        return fallback, ["计划大纲增强失败，已使用 confirmed plan 规则增强结果。"]
    try:
        batch = response if isinstance(response, EnhancedChapterOutlineBatch) else EnhancedChapterOutlineBatch.model_validate(response)
    except Exception:
        return fallback, ["计划大纲增强结果无法解析，已使用 confirmed plan 规则增强结果。"]
    return _coerce_outline_batch(
        batch,
        chapters,
        digest_mode=digest_mode,
        user_prompt=user_prompt,
        plan_summary=plan_summary,
    )


__all__ = ["enhance_plan_outline", "fallback_enhance_plan_outline"]
