"""Chapter-level enhancement, assets, and practice seeds."""

from __future__ import annotations

import re

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt, normalize_mermaid_blocks
from app.workflows.digest.docgen.lib.assets import DocGenAssetRuntime
from app.workflows.digest.docgen.lib.models import (
    AssetManifest,
    ChapterDraft,
    EnhancedChapterDraft,
    PracticeManifest,
)

_MERMAID_PLACEHOLDER_RE = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->", re.IGNORECASE | re.DOTALL)
_IMAGE_PLACEHOLDER_RE = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->", re.IGNORECASE | re.DOTALL)
_INTERACTIVE_PLACEHOLDER_RE = re.compile(r"<!--\s*\[INTERACTIVE:\s*(.+?)\]\s*-->", re.IGNORECASE | re.DOTALL)


def _placeholder_comment(kind: str, description: str) -> str:
    return f"<!-- [{kind}: {description}] -->"


def _ensure_requested_placeholders(markdown: str, requests: list[dict]) -> str:
    additions: list[str] = []
    existing = {
        "mermaid": {item.strip().casefold() for item in _MERMAID_PLACEHOLDER_RE.findall(markdown)},
        "image": {item.strip().casefold() for item in _IMAGE_PLACEHOLDER_RE.findall(markdown)},
        "interactive": {item.strip().casefold() for item in _INTERACTIVE_PLACEHOLDER_RE.findall(markdown)},
    }
    for item in requests:
        kind = str(item.get("kind") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        description_key = description.casefold()
        if kind == "mermaid" and description_key not in existing["mermaid"]:
            additions.append(_placeholder_comment("MERMAID", description))
            existing["mermaid"].add(description_key)
        elif kind in {"image", "images"} and description_key not in existing["image"]:
            additions.append(_placeholder_comment("IMAGE", description))
            existing["image"].add(description_key)
        elif kind in {"interactive", "interactive_html"} and description_key not in existing["interactive"]:
            additions.append(_placeholder_comment("INTERACTIVE", description))
            existing["interactive"].add(description_key)
    if not additions:
        return markdown
    return markdown.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"


def _build_practice_questions(draft: ChapterDraft, *, digest_mode: str) -> list[dict]:
    title = draft.title
    normalized_mode = str(digest_mode or "").strip().lower()
    if normalized_mode == "sprint":
        return [
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p01",
                "chapter_index": draft.chapter_index,
                "type": "pattern_check",
                "question": f"《{title}》最容易考成哪类题？请写出题眼、方法和易错点。",
            },
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p02",
                "chapter_index": draft.chapter_index,
                "type": "self_check",
                "question": f"不看正文，用 60 秒复盘《{title}》的核心抓手。",
            },
        ]
    return [
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p01",
            "chapter_index": draft.chapter_index,
            "type": "comprehension",
            "question": f"请用自己的话解释《{title}》解决的核心问题。",
        },
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p02",
            "chapter_index": draft.chapter_index,
            "type": "transfer",
            "question": f"把《{title}》中的一个方法迁移到新场景，并说明适用条件。",
        },
    ]


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
) -> tuple[EnhancedChapterDraft, AssetManifest, PracticeManifest]:
    markdown = _ensure_requested_placeholders(draft.markdown, draft.placeholder_requests)
    mermaid_placeholders = [item.strip() for item in _MERMAID_PLACEHOLDER_RE.findall(markdown)]
    image_placeholders = [item.strip() for item in _IMAGE_PLACEHOLDER_RE.findall(markdown)]
    interactive_placeholders = [item.strip() for item in _INTERACTIVE_PLACEHOLDER_RE.findall(markdown)]
    asset_runtime = DocGenAssetRuntime(traced_context)
    assets: list[dict] = []
    warnings: list[str] = []
    try:
        if mermaid_placeholders:
            traced_context.asset_kind = "mermaid"
            markdown = await asset_runtime.process_mermaid_placeholders(markdown)
            assets.extend(
                {
                    "asset_id": f"ch{draft.chapter_index:02d}_mermaid_{index:02d}",
                    "chapter_index": draft.chapter_index,
                    "kind": "mermaid",
                    "source_placeholder": description,
                    "status": "rendered_markdown",
                }
                for index, description in enumerate(mermaid_placeholders, start=1)
            )
        if image_placeholders:
            traced_context.asset_kind = "image"
            markdown = await asset_runtime.process_image_placeholders(markdown)
            assets.extend(
                {
                    "asset_id": f"ch{draft.chapter_index:02d}_image_{index:02d}",
                    "chapter_index": draft.chapter_index,
                    "kind": "image",
                    "source_placeholder": description,
                    "status": "placeholder_processed",
                }
                for index, description in enumerate(image_placeholders, start=1)
            )
        if interactive_placeholders:
            traced_context.asset_kind = "interactive_html"
            markdown = await asset_runtime.process_interactive_placeholders(markdown, digest_mode=digest_mode)
            assets.extend(
                {
                    "asset_id": f"ch{draft.chapter_index:02d}_interactive_{index:02d}",
                    "chapter_index": draft.chapter_index,
                    "kind": "interactive_html",
                    "source_placeholder": description,
                    "status": "rendered_html",
                }
                for index, description in enumerate(interactive_placeholders, start=1)
            )
    except Exception as exc:
        warnings.append(f"章节增强失败，已保留原始正文：{str(exc)[:120]}")
    markdown = normalize_math_delimiters(markdown)
    markdown = validate_latex(markdown)
    markdown = normalize_mermaid_blocks(markdown)
    questions = _build_practice_questions(draft, digest_mode=digest_mode)
    markdown = _append_practice_section(markdown, questions)
    enhanced = EnhancedChapterDraft(
        chapter_index=draft.chapter_index,
        title=draft.title,
        markdown=markdown,
        summary=build_draft_excerpt(markdown, max_chars=260),
        evidence_ledger=draft.evidence_ledger,
        quality_signals=draft.quality_signals,
        sources=draft.sources,
        source_details=draft.source_details,
        asset_ids=[str(item.get("asset_id")) for item in assets],
        practice_ids=[str(item.get("practice_id")) for item in questions],
        warnings=warnings,
    )
    return enhanced, AssetManifest(assets=assets), PracticeManifest(questions=questions)


__all__ = ["enhance_chapter_draft"]
