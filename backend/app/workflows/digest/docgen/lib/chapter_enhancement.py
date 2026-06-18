"""Chapter-level presentation and asset enhancement."""

from __future__ import annotations

import re

from app.shared.infra.settings import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    build_draft_excerpt,
)
from app.workflows.digest.docgen.lib.asset_requests import build_asset_request_block, extract_asset_request_descriptions, strip_asset_requests
from app.workflows.digest.docgen.lib.asset_rendering import DocGenAssetRuntime
from app.workflows.digest.docgen.lib.interactive_html import plan_interactive_html_assets
from app.workflows.digest.docgen.lib.models import (
    AssetManifest,
    ChapterDraft,
    ClaimLedger,
    EnhancedChapterDraft,
    PracticeManifest,
)
from app.workflows.digest.docgen.lib.presentation_policy import normalize_docgen_presentation

_MERMAID_FENCE_RE = re.compile(
    r"(?im)^\s*```\s*(?:mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|"
    r"stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\b"
)


def _sanitize_public_doc_terms(markdown: str) -> str:
    return (
        str(markdown or "")
        .replace("速成课模式", "紧凑节奏")
        .replace("速成课", "紧凑节奏")
        .replace("系统课", "系统节奏")
        .replace("章节合同", "学习大纲")
    )


def _has_rendered_mermaid_block(markdown: str) -> bool:
    return bool(_MERMAID_FENCE_RE.search(str(markdown or "")))


def _ensure_requested_placeholders(markdown: str, requests: list[dict]) -> str:
    additions: list[str] = []
    existing = {
        "mermaid": {item.strip().casefold() for item in extract_asset_request_descriptions(markdown, kind="mermaid")},
        "interactive": {item.strip().casefold() for item in extract_asset_request_descriptions(markdown, kind="interactive")},
    }
    has_rendered_mermaid = _has_rendered_mermaid_block(markdown)
    for item in requests:
        kind = str(item.get("kind") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        description_key = description.casefold()
        if kind == "mermaid" and not has_rendered_mermaid and description_key not in existing["mermaid"]:
            additions.append(build_asset_request_block("mermaid", description))
            existing["mermaid"].add(description_key)
    if not additions:
        return markdown
    return markdown.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"


def _insert_asset_links(markdown: str, assets: list[dict[str, object]]) -> str:
    if not assets:
        return markdown
    updated = markdown
    insertions: list[tuple[int, int, str]] = []
    fallback_at = len(markdown)
    for order, asset in enumerate(assets):
        link_markdown = str(asset.get("link_markdown") or "").strip()
        if not link_markdown:
            continue
        try:
            insert_at = int(asset.get("insert_at") or fallback_at)
        except (TypeError, ValueError):
            insert_at = fallback_at
        insert_at = max(0, min(len(markdown), insert_at))
        insertions.append((insert_at, order, link_markdown))
    for insert_at, _order, link_markdown in sorted(insertions, key=lambda item: (item[0], item[1]), reverse=True):
        prefix = updated[:insert_at].rstrip()
        suffix = updated[insert_at:].lstrip("\n")
        updated = f"{prefix}\n\n{link_markdown}\n\n{suffix}".rstrip() + "\n"
    return updated


async def enhance_chapter_draft(
    draft: ChapterDraft,
    *,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    used_static_figure_signatures: set[str] | None = None,
) -> tuple[EnhancedChapterDraft, AssetManifest, PracticeManifest]:
    """增强单章草稿的表现层内容。

    这里只处理资产、公式和 Markdown 展示结构。它不能修核心定义、新增知识
    结论、生成标题或补写练习；这些语义内容必须由 writer / review /
    repair 的模型链路完成。
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
    markdown = normalize_docgen_presentation(
        markdown,
        digest_mode=digest_mode,
        title=draft.title,
        focus_items=[
            *(item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text),
            draft.title,
        ],
    )

    interactive_assets: list[dict[str, object]] = []
    if settings.docgen.generate_interactive_html:
        try:
            traced_context.asset_kind = "interactive"
            interactive_assets = plan_interactive_html_assets(
                draft=draft,
                course_id=traced_context.course_id,
                markdown=markdown,
            )
            if interactive_assets:
                markdown = _insert_asset_links(markdown, interactive_assets)
                assets.extend(interactive_assets)
        except Exception as exc:
            warnings.append(f"交互页生成失败，已跳过交互增强：{str(exc)[:120]}")

    questions: list[dict] = []
    markdown = normalize_docgen_presentation(markdown, digest_mode=digest_mode, title=draft.title)
    markdown = _sanitize_public_doc_terms(markdown)
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
