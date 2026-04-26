"""Chapter-level enhancement, assets, and practice seeds."""

from __future__ import annotations

import re

from app.shared.infra.settings import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    build_draft_excerpt,
    normalize_markdown_rendering,
    normalize_mermaid_blocks,
)
from app.workflows.digest.docgen.lib.asset_requests import build_asset_request_block, extract_asset_request_descriptions, strip_asset_requests
from app.workflows.digest.docgen.lib.asset_rendering import DocGenAssetRuntime
from app.workflows.digest.docgen.lib.interactive_html import maybe_generate_interactive_html_asset
from app.workflows.digest.docgen.lib.models import (
    AssetManifest,
    ChapterDraft,
    ClaimLedger,
    DocumentBackbone,
    EnhancedChapterDraft,
    PracticeManifest,
)
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

def _ensure_requested_placeholders(markdown: str, requests: list[dict]) -> str:
    additions: list[str] = []
    existing = {
        "mermaid": {item.strip().casefold() for item in extract_asset_request_descriptions(markdown, kind="mermaid")},
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
    mode_profile = get_docgen_mode_profile(digest_mode)
    claim_items = list((claim_ledger or ClaimLedger(chapter_index=draft.chapter_index)).items or [])
    claim_prompts = [item.claim_text for item in claim_items if item.claim_text][:3]
    confusion_items = [
        item.topic or item.contrast
        for item in list((document_backbone or DocumentBackbone()).confusion_map or [])
        if (not item.target_chapters or draft.chapter_index in item.target_chapters)
    ][:2]
    if mode_profile.is_sprint:
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


def _append_interactive_block(markdown: str, asset: dict[str, object] | None) -> str:
    if not asset:
        return markdown
    link_markdown = str(asset.get("link_markdown") or "").strip()
    if not link_markdown:
        return markdown
    return markdown.rstrip() + "\n\n" + link_markdown + "\n"


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
    settings = get_settings()
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
            markdown = strip_asset_requests(markdown, kinds={"image"})
            warnings.append("已移除图片占位；DocGen 当前不直接生成讲义配图。")
        if interactive_placeholders:
            markdown = strip_asset_requests(markdown, kinds={"interactive"})
            if settings.docgen.generate_interactive_html:
                warnings.append("已移除旧式交互占位；本轮会按章节启发式尝试生成 HTML 交互页 sidecar。")
            else:
                warnings.append("已移除交互占位；当前未启用知识文档交互页生成。")
    except Exception as exc:
        warnings.append(f"章节增强失败，已保留原始正文：{str(exc)[:120]}")
    markdown = strip_asset_requests(markdown)
    markdown = normalize_math_delimiters(markdown)
    markdown = validate_latex(markdown)
    markdown = normalize_markdown_rendering(markdown)
    markdown = normalize_mermaid_blocks(markdown)

    interactive_asset: dict[str, object] | None = None
    if settings.docgen.generate_interactive_html:
        try:
            traced_context.asset_kind = "interactive"
            interactive_asset = await maybe_generate_interactive_html_asset(
                draft=draft,
                traced_context=traced_context,
                digest_mode=digest_mode,
                claim_ledger=claim_ledger,
                document_backbone=document_backbone,
            )
            if interactive_asset is not None:
                markdown = _append_interactive_block(markdown, interactive_asset)
                assets.append(interactive_asset)
        except Exception as exc:
            warnings.append(f"交互页生成失败，已跳过交互增强：{str(exc)[:120]}")

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
