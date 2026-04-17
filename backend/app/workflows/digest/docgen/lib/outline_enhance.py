"""Execution-level outline enhancement for DocGen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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
        if any(marker in visual_text for marker in ("图", "结构", "流程", "关系", "场景", "例题")):
            media_requests.append({"kind": "image", "description": f"{title} 的学习配图或例题场景图"})
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
                retrieval_queries=clean_string_list([*chapter.get("search_queries", []), title, *required], limit=8),
                fallback_used=True,
            )
        )
    return outlines


def _coerce_outline_batch(
    batch: EnhancedChapterOutlineBatch,
    chapters: Sequence[Mapping[str, Any]],
    *,
    digest_mode: str,
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
        if not candidate.enhanced_title:
            candidate.enhanced_title = base.enhanced_title
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
    user_goal: str,
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
                user_goal=user_goal,
                plan_summary=plan_summary,
                chapters=chapters,
                docgen_history_brief=docgen_history_brief,
            ),
            task_type=TaskType.REASONING,
            model="reason",
            response_model=EnhancedChapterOutlineBatch,
            temperature=0.15,
            max_tokens=2600,
            extra_metadata={"docgen_stage": "enhance_plan_outline", **dict(extra_metadata or {})},
        )
    except Exception as exc:
        logger.warning("docgen_outline_enhance_failed", error=str(exc))
        return fallback, ["计划大纲增强失败，已使用 confirmed plan 规则增强结果。"]
    try:
        batch = response if isinstance(response, EnhancedChapterOutlineBatch) else EnhancedChapterOutlineBatch.model_validate(response)
    except Exception:
        return fallback, ["计划大纲增强结果无法解析，已使用 confirmed plan 规则增强结果。"]
    return _coerce_outline_batch(batch, chapters, digest_mode=digest_mode)


__all__ = ["enhance_plan_outline", "fallback_enhance_plan_outline"]
