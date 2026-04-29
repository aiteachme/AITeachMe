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
from app.workflows.digest.docgen.lib.textbook_style import (
    choose_heading_focus,
    format_worked_example_section,
    has_worked_example_section,
    normalize_educational_callouts,
    normalize_textbook_headings,
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
        focus_terms = [*claim_prompts, title]
        first_claim = claim_prompts[0] if claim_prompts else title or "核心考点"
        second_claim = claim_prompts[1] if len(claim_prompts) > 1 else first_claim
        examples = [
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p01",
                "chapter_index": draft.chapter_index,
                "type": "worked_example",
                "label": choose_heading_focus([first_claim], fallback=title),
                "stem": f"围绕《{title}》中的“{first_claim}”设计一道基础判定题，并说明应使用哪个定义、公式或方法。",
                "analysis_steps": [
                    "先圈出题目给出的对象、条件和要求，确认它对应本章哪一个知识点。",
                    "再选择相应的定义、公式或判定方法，并说明为什么能用。",
                    "最后把结果代回题目条件，检查范围、单位或逻辑方向是否一致。",
                ],
                "pitfall": "只看到熟悉关键词就套方法，容易忽略题目条件是否满足。",
            },
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p02",
                "chapter_index": draft.chapter_index,
                "type": "worked_example",
                "label": choose_heading_focus([second_claim], fallback=title),
                "stem": f"把“{second_claim}”改造成一道变式题：题目条件稍作变化，判断原方法是否仍然适用。",
                "analysis_steps": [
                    "先比较变式题和基础题的条件差异。",
                    "再判断原结论的适用前提是否仍然成立。",
                    "如果前提改变，需要说明应替换成哪一种方法或补充哪一步检验。",
                ],
                "pitfall": "变式题最容易错在把旧题路径完整照搬，而没有重新检查前提。",
            },
        ]
        if confusion_items:
            examples.append(
                {
                    "practice_id": f"ch{draft.chapter_index:02d}_p03",
                    "chapter_index": draft.chapter_index,
                    "type": "worked_example",
                    "label": choose_heading_focus([confusion_items[0]], fallback=title),
                    "stem": f"辨析“{confusion_items[0]}”：给出一个能用的条件和一个不能硬套的反例场景。",
                    "analysis_steps": [
                        "先写出两个概念或方法各自成立的条件。",
                        "再构造一个满足条件的正例，说明为什么可以使用。",
                        "最后构造一个不满足条件的反例，说明硬套会错在哪里。",
                    ],
                    "pitfall": "只记相似表述，不记边界条件，会把两个不同结论混用。",
                }
            )
        elif len(focus_terms) >= 2:
            examples.append(
                {
                    "practice_id": f"ch{draft.chapter_index:02d}_p03",
                    "chapter_index": draft.chapter_index,
                    "type": "worked_example",
                    "label": "综合应用",
                    "stem": f"把《{title}》中两个相关知识点合在一道小题里，说明解题顺序。",
                    "analysis_steps": [
                        "先判断哪一个知识点是入口，哪一个知识点是后续计算或论证工具。",
                        "再按依赖顺序展开步骤，避免先用后证。",
                        "最后检查两个结论之间是否存在条件冲突。",
                    ],
                    "pitfall": "综合题不是把公式堆在一起，而是要先确定使用顺序。",
                }
            )
        return examples
    first_claim = claim_prompts[0] if claim_prompts else "核心概念"
    questions = [
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p01",
            "chapter_index": draft.chapter_index,
            "type": "worked_example",
            "label": choose_heading_focus([first_claim], fallback=title),
            "stem": f"为《{title}》中的“{first_claim}”设计一个概念例题，并说明它检验了哪些定义条件。",
            "analysis_steps": [
                "先写清题目对象和需要验证的定义条件。",
                "再逐条检查条件是否成立。",
                "最后说明这个例子体现了概念的哪一部分含义。",
            ],
            "pitfall": "概念例题不能只给结论，必须回到定义条件。",
        },
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p02",
            "chapter_index": draft.chapter_index,
            "type": "reasoning_replay",
            "stem": f"复述《{title}》里一条方法或结论的推理路径：前提、关键步骤、结论各是什么？",
            "analysis_steps": [
                "先列出推理所需的前提。",
                "再按顺序写出关键步骤，不跳过中间依据。",
                "最后说明结论的适用范围。",
            ],
            "pitfall": "系统学习最怕只背结论，不说明推理从哪里来。",
        },
        {
            "practice_id": f"ch{draft.chapter_index:02d}_p03",
            "chapter_index": draft.chapter_index,
            "type": "transfer",
            "stem": f"把《{title}》中的一个主张或方法迁移到新场景，并说明适用条件。",
            "analysis_steps": [
                "先说明原场景中的关键条件。",
                "再检查新场景是否保留这些条件。",
                "最后指出需要调整的变量、边界或表达方式。",
            ],
            "pitfall": "迁移不是换个故事，而是确认结构条件是否相同。",
        },
    ]
    if confusion_items:
        questions.append(
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p04",
                "chapter_index": draft.chapter_index,
                "type": "boundary",
                "stem": f"说明“{confusion_items[0]}”的边界条件，并举一个容易混淆的反例或场景。",
                "analysis_steps": [
                    "先分别列出两个对象或方法的适用条件。",
                    "再说明反例违反了哪一个条件。",
                    "最后总结区分它们的一句话标准。",
                ],
                "pitfall": "边界题的关键不是背定义，而是抓住不能混用的条件。",
            }
        )
    return questions


_PRACTICE_HEADING_RE = re.compile(r"^##\s+.*(?:例题|练习|自测|自检|迁移).*$", re.MULTILINE)


def _append_practice_section(markdown: str, questions: list[dict], *, digest_mode: str, title: str = "") -> str:
    if not questions:
        return markdown
    if has_worked_example_section(markdown) or _PRACTICE_HEADING_RE.search(markdown):
        return markdown
    section = format_worked_example_section(
        questions,
        digest_mode=digest_mode,
        fallback_title=title or "本章",
        focus_items=[
            str(item.get("label") or item.get("stem") or item.get("question") or "")
            for item in questions
        ],
    )
    if not section:
        return markdown
    return markdown.rstrip() + "\n\n" + section + "\n"


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
    include_practice: bool = True,
) -> tuple[EnhancedChapterDraft, AssetManifest, PracticeManifest]:
    """增强单章草稿的表现层内容。

    这里只处理资产、公式、Markdown 结构和例题/练习。它不能修核心定义、
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
    markdown = normalize_textbook_headings(
        markdown,
        digest_mode=digest_mode,
        fallback_title=draft.title,
        focus_items=[
            *(item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text),
            draft.title,
        ],
    )
    markdown = normalize_educational_callouts(markdown)

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

    questions = (
        _build_practice_questions(
            draft,
            digest_mode=digest_mode,
            claim_ledger=claim_ledger,
            document_backbone=document_backbone,
        )
        if include_practice
        else []
    )
    markdown = _append_practice_section(markdown, questions, digest_mode=digest_mode, title=draft.title)
    markdown = normalize_educational_callouts(markdown)
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
