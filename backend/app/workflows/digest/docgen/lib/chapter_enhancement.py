"""Chapter-level enhancement, assets, and practice seeds."""

from __future__ import annotations

import re

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt, normalize_mermaid_blocks
from app.workflows.digest.docgen.lib.asset_requests import build_asset_request_block, extract_asset_request_descriptions, strip_asset_requests
from app.workflows.digest.docgen.lib.assets import DocGenAssetRuntime
from app.workflows.digest.docgen.lib.models import (
    AssetManifest,
    ChapterDraft,
    ClaimLedger,
    DocumentBackbone,
    EnhancedChapterDraft,
    PracticeManifest,
)

def _ensure_requested_placeholders(markdown: str, requests: list[dict]) -> str:
    additions: list[str] = []
    existing = {
        "mermaid": {item.strip().casefold() for item in extract_asset_request_descriptions(markdown, kind="mermaid")},
        "image": {item.strip().casefold() for item in extract_asset_request_descriptions(markdown, kind="image")},
        "interactive": {item.strip().casefold() for item in extract_asset_request_descriptions(markdown, kind="interactive")},
    }
    for item in requests:
        kind = str(item.get("kind") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        description_key = description.casefold()
        if kind == "mermaid" and description_key not in existing["mermaid"]:
            additions.append(build_asset_request_block("mermaid", description))
            existing["mermaid"].add(description_key)
    if not additions:
        return markdown
    return markdown.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"


def _build_practice_questions(
    draft: ChapterDraft,
    *,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
) -> list[dict]:
    title = draft.title
    normalized_mode = str(digest_mode or "").strip().lower()
    claim_items = list((claim_ledger or ClaimLedger(chapter_index=draft.chapter_index)).items or [])
    claim_prompts = [item.claim_text for item in claim_items if item.claim_text][:3]
    confusion_items = [
        item.topic or item.contrast
        for item in list((document_backbone or DocumentBackbone()).confusion_map or [])
        if (not item.target_chapters or draft.chapter_index in item.target_chapters)
    ][:2]
    if normalized_mode == "sprint":
        questions = [
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p01",
                "chapter_index": draft.chapter_index,
                "type": "pattern_check",
                "question": f"围绕《{title}》中“{claim_prompts[0] if claim_prompts else '核心抓手'}”，写出题眼、方法和易错点。",
            },
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p02",
                "chapter_index": draft.chapter_index,
                "type": "self_check",
                "question": f"不看正文，用 60 秒复盘《{title}》的核心抓手。",
            },
        ]
        if confusion_items:
            questions.append(
                {
                    "practice_id": f"ch{draft.chapter_index:02d}_p03",
                    "chapter_index": draft.chapter_index,
                    "type": "pitfall_check",
                    "question": f"辨析“{confusion_items[0]}”：什么时候能用，什么时候不能硬套？",
                }
            )
        return questions
    questions = [
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p01",
            "chapter_index": draft.chapter_index,
            "type": "comprehension",
            "question": f"请用自己的话解释《{title}》中“{claim_prompts[0] if claim_prompts else '核心概念'}”解决的核心问题。",
        },
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p02",
            "chapter_index": draft.chapter_index,
            "type": "transfer",
            "question": f"把《{title}》中的一个主张或方法迁移到新场景，并说明适用条件。",
        },
    ]
    if confusion_items:
        questions.append(
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p03",
                "chapter_index": draft.chapter_index,
                "type": "boundary",
                "question": f"说明“{confusion_items[0]}”的边界条件，并举一个容易混淆的反例或场景。",
            }
        )
    return questions


def _append_practice_section(markdown: str, questions: list[dict]) -> str:
    if not questions:
        return markdown
    lines = [markdown.rstrip(), "", "## 本章自检", ""]
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question['question']}")
    return "\n".join(lines).strip() + "\n"


async def enhance_chapter_draft(
    draft: ChapterDraft,
    *,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
) -> tuple[EnhancedChapterDraft, AssetManifest, PracticeManifest]:
    """增强单章草稿的表现层内容。

    这里只处理资产、公式、Markdown 结构和自检题。它不能修核心定义、
    新增知识结论或改变 claim/evidence 关系；这些问题必须走 review /
    repair 回流。
    """

    markdown = _ensure_requested_placeholders(draft.markdown, draft.placeholder_requests)
    mermaid_placeholders = [item.strip() for item in extract_asset_request_descriptions(markdown, kind="mermaid")]
    image_placeholders = [item.strip() for item in extract_asset_request_descriptions(markdown, kind="image")]
    interactive_placeholders = [item.strip() for item in extract_asset_request_descriptions(markdown, kind="interactive")]
    asset_runtime = DocGenAssetRuntime(traced_context)
    assets: list[dict] = []
    mermaid_render_reports: list[dict[str, object]] = []
    warnings: list[str] = []
    try:
        if mermaid_placeholders:
            traced_context.asset_kind = "mermaid"
            markdown, mermaid_render_reports = await asset_runtime.process_mermaid_placeholders_with_reports(markdown)
            assets.extend(
                {
                    "asset_id": f"ch{draft.chapter_index:02d}_mermaid_{index:02d}",
                    "chapter_index": draft.chapter_index,
                    "kind": "mermaid",
                    "source_placeholder": description,
                    "status": "rendered_markdown",
                    "render_report": mermaid_render_reports[index - 1] if index - 1 < len(mermaid_render_reports) else {},
                }
                for index, description in enumerate(mermaid_placeholders, start=1)
            )
        if image_placeholders:
            traced_context.asset_kind = "image"
            markdown, image_render_reports = await asset_runtime.process_image_placeholders_with_reports(markdown)
            assets.extend(
                {
                    "asset_id": f"ch{draft.chapter_index:02d}_image_{index:02d}",
                    "chapter_index": draft.chapter_index,
                    "kind": "image",
                    "source_placeholder": description,
                    "status": str((image_render_reports[index - 1] if index - 1 < len(image_render_reports) else {}).get("status") or "unknown"),
                    "render_report": image_render_reports[index - 1] if index - 1 < len(image_render_reports) else {},
                }
                for index, description in enumerate(image_placeholders, start=1)
            )
        if interactive_placeholders:
            markdown = strip_asset_requests(markdown, kinds={"interactive"})
            warnings.append("已移除交互占位；后端仅发布标准 Markdown，交互展示交给前端能力处理。")
    except Exception as exc:
        warnings.append(f"章节增强失败，已保留原始正文：{str(exc)[:120]}")
    markdown = strip_asset_requests(markdown)
    markdown = normalize_math_delimiters(markdown)
    markdown = validate_latex(markdown)
    markdown = normalize_mermaid_blocks(markdown)
    questions = _build_practice_questions(
        draft,
        digest_mode=digest_mode,
        claim_ledger=claim_ledger,
        document_backbone=document_backbone,
    )
    markdown = _append_practice_section(markdown, questions)
    enhanced = EnhancedChapterDraft(
        chapter_index=draft.chapter_index,
        title=draft.title,
        markdown=markdown,
        summary=build_draft_excerpt(markdown, max_chars=260),
        evidence_ledger=draft.evidence_ledger,
        claim_ledger_ref=draft.claim_ledger_ref,
        conflict_warning_refs=draft.conflict_warning_refs,
        quality_signals=draft.quality_signals,
        source_scope=draft.source_scope,
        sources=draft.sources,
        source_details=draft.source_details,
        asset_ids=[str(item.get("asset_id")) for item in assets],
        practice_ids=[str(item.get("practice_id")) for item in questions],
        warnings=warnings,
        fallback_used=draft.fallback_used,
    )
    return enhanced, AssetManifest(assets=assets), PracticeManifest(questions=questions)


__all__ = ["enhance_chapter_draft"]
