"""Chapter-level enhancement, assets, and practice seeds."""

from __future__ import annotations

import re

from app.shared.infra.settings import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    build_draft_excerpt,
)
from app.workflows.digest.common.pedagogy import is_usable_resolved_chapter_title
from app.workflows.digest.docgen.lib.asset_requests import build_asset_request_block, extract_asset_request_descriptions, strip_asset_requests
from app.workflows.digest.docgen.lib.asset_rendering import DocGenAssetRuntime
from app.workflows.digest.docgen.lib.interactive_html import plan_interactive_html_assets
from app.workflows.digest.docgen.lib.models import (
    AssetManifest,
    ChapterDraft,
    ClaimLedger,
    DocumentBackbone,
    EnhancedChapterDraft,
    PracticeManifest,
)
from app.workflows.digest.docgen.lib.presentation_policy import normalize_docgen_presentation
from app.workflows.digest.docgen.lib.textbook_style import (
    choose_heading_focus,
    format_worked_example_section,
    has_worked_example_section,
)
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def _sanitize_public_doc_terms(markdown: str) -> str:
    return (
        str(markdown or "")
        .replace("速成课模式", "快速复习节奏")
        .replace("速成课", "快速复习")
        .replace("系统课", "系统学习")
        .replace("章节合同", "学习大纲")
    )


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
    raw_title = draft.title
    mode_profile = get_docgen_mode_profile(digest_mode)
    claim_items = list((claim_ledger or ClaimLedger(chapter_index=draft.chapter_index)).items or [])
    claim_prompts = [item.claim_text for item in claim_items if item.claim_text][:3]
    confusion_items = [
        item.topic or item.contrast
        for item in list((document_backbone or DocumentBackbone()).confusion_map or [])
        if (not item.target_chapters or draft.chapter_index in item.target_chapters)
    ][:2]
    title = raw_title if is_usable_resolved_chapter_title(raw_title) else (
        choose_heading_focus([*claim_prompts, *confusion_items], fallback="本章核心内容") or "本章核心内容"
    )
    if mode_profile.is_sprint:
        focus_terms = [*claim_prompts, title]
        first_claim = claim_prompts[0] if claim_prompts else title or "核心重点"
        second_claim = claim_prompts[1] if len(claim_prompts) > 1 else first_claim
        examples = [
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p01",
                "chapter_index": draft.chapter_index,
                "type": "worked_example",
                "label": choose_heading_focus([first_claim], fallback=title),
                "stem": f"用《{title}》中的“{first_claim}”完成一个基础判断：先说清对象和条件，再说明应使用哪个定义、结论或方法。",
                "analysis_steps": [
                    "先圈出任务给出的对象、条件和要求，确认它对应本章哪一个知识点。",
                    "再选择相应的定义、结论或判定方法，并说明为什么能用。",
                    "最后把结果代回原条件，检查范围、单位或逻辑方向是否一致。",
                ],
                "pitfall": "只看到熟悉说法就套方法，容易忽略题目条件是否满足。",
            },
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p02",
                "chapter_index": draft.chapter_index,
                "type": "worked_example",
                "label": choose_heading_focus([second_claim], fallback=title),
                "stem": f"把“{second_claim}”换一个条件做检查：判断原方法是否仍然适用。",
                "analysis_steps": [
                    "先比较变式任务和基础任务的条件差异。",
                    "再判断原结论的适用前提是否仍然成立。",
                    "如果前提改变，需要说明应替换成哪一种方法或补充哪一步检验。",
                ],
                "pitfall": "变式任务最容易错在把旧路径完整照搬，而没有重新检查前提。",
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
                    "stem": f"把《{title}》中两个相关知识点合在一个综合任务里，说明处理顺序。",
                    "analysis_steps": [
                        "先判断哪一个知识点是入口，哪一个知识点是后续计算或论证工具。",
                        "再按依赖顺序展开步骤，避免先用后证。",
                        "最后检查两个结论之间是否存在条件冲突。",
                    ],
                    "pitfall": "综合任务不是把结论堆在一起，而是要先确定使用顺序和适用条件。",
                }
            )
        while len(examples) < 5:
            focus = focus_terms[min(len(examples) - 1, len(focus_terms) - 1)] if focus_terms else title
            examples.append(
                {
                    "practice_id": f"ch{draft.chapter_index:02d}_p{len(examples) + 1:02d}",
                    "chapter_index": draft.chapter_index,
                    "type": "worked_example",
                    "label": choose_heading_focus([focus], fallback=title),
                    "stem": f"完成一道与“{focus}”直接相关的小题：先判断条件是否满足，再写出处理步骤和最后检查。",
                    "analysis_steps": [
                        "先判断任务属于哪类高频场景、常见题型或操作任务。",
                        "再写出使用该方法必须满足的条件。",
                        "最后按模板完成步骤，并做一次易错检查。",
                    ],
                    "pitfall": "重点是先看条件和方法边界，不能只背答案。",
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
            "stem": f"用《{title}》中的“{first_claim}”完成一个概念自检：说明它检验了哪些定义条件。",
            "analysis_steps": [
                "先写清讨论对象和需要验证的定义条件。",
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
    for claim in claim_prompts[1:4]:
        if len(questions) >= 5:
            break
        questions.append(
            {
                "practice_id": f"ch{draft.chapter_index:02d}_p{len(questions) + 1:02d}",
                "chapter_index": draft.chapter_index,
                "type": "worked_example",
                "label": choose_heading_focus([claim], fallback=title),
                "stem": f"给“{claim}”补一个覆盖例题或应用案例，说明它如何落到具体任务中。",
                "analysis_steps": [
                    "先回到该知识点的定义、条件或结构。",
                    "再构造一个能使用它的具体任务。",
                    "最后说明例题中的哪一步体现了这个知识点。",
                ],
                "pitfall": "系统课的例题必须回扣知识点，不能只给一个孤立答案。",
            }
        )
    return questions


_PRACTICE_HEADING_RE = re.compile(r"^#{2,4}\s+.*(?:例题|练习|自测|自检|迁移).*$", re.MULTILINE)
_WORKED_EXAMPLE_TITLE_RE = re.compile(r"(?m)^(?:#{3,5}\s+.*(?:例题|案例|任务|变式)|\s*>\s*\*\*例题\s*\d*)")
_PRACTICE_STEM_RE = re.compile(r"(?m)^\s*(?:>\s*)?\*\*(?:题目|任务|案例)\*\*[：:]")
_PRACTICE_ANALYSIS_RE = re.compile(r"(?m)^\s*(?:>\s*)?\*\*(?:解析|解法|步骤)\*\*[：:]")
_PRACTICE_PITFALL_RE = re.compile(r"(?m)^\s*(?:>\s*)?\*\*(?:易错点|错因|注意)\*\*[：:]")


def _structured_practice_signal_count(markdown: str) -> int:
    text = str(markdown or "")
    title_count = len(_WORKED_EXAMPLE_TITLE_RE.findall(text))
    stem_count = len(_PRACTICE_STEM_RE.findall(text))
    analysis_count = len(_PRACTICE_ANALYSIS_RE.findall(text))
    pitfall_count = len(_PRACTICE_PITFALL_RE.findall(text))
    structured_count = min(stem_count, analysis_count)
    if structured_count and pitfall_count:
        structured_count = min(structured_count, pitfall_count)
    if not structured_count:
        return 0
    return max(title_count, structured_count)


def _minimum_visible_examples(*, digest_mode: str, question_count: int) -> int:
    if question_count <= 0:
        return 0
    mode_profile = get_docgen_mode_profile(digest_mode)
    desired = int(mode_profile.example_density_policy.get("worked_examples_per_chapter", 1) or 1)
    # The deterministic supplement should be enough to make the chapter usable,
    # while avoiding a large duplicated exercise appendix when the writer already did well.
    cap = 4 if mode_profile.is_sprint else 2
    return max(1, min(question_count, desired, cap))


def _append_practice_section(markdown: str, questions: list[dict], *, digest_mode: str, title: str = "") -> str:
    if not questions:
        return markdown
    minimum_examples = _minimum_visible_examples(digest_mode=digest_mode, question_count=len(questions))
    existing_examples = _structured_practice_signal_count(markdown)
    has_practice_area = has_worked_example_section(markdown) or _PRACTICE_HEADING_RE.search(markdown)
    if has_practice_area and existing_examples >= minimum_examples:
        return markdown
    supplement_count = max(1, minimum_examples - existing_examples) if has_practice_area else len(questions)
    supplement_start = min(existing_examples, len(questions) - 1) if has_practice_area else 0
    supplement_end = max(supplement_start + 1, min(len(questions), supplement_start + supplement_count))
    supplement_questions = questions[supplement_start:supplement_end]
    section = format_worked_example_section(
        supplement_questions,
        digest_mode=digest_mode,
        fallback_title=title or "本章",
        focus_items=[
            str(item.get("label") or item.get("stem") or item.get("question") or "")
            for item in supplement_questions
        ],
    )
    if not section:
        return markdown
    return markdown.rstrip() + "\n\n" + section + "\n"


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
    markdown = normalize_docgen_presentation(
        markdown,
        digest_mode=digest_mode,
        title=draft.title,
        focus_items=[
            *(item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text),
            draft.title,
        ],
    )

    # Do not run model-backed static HTML figures in per-chapter enhancement:
    # the readable Markdown path must finish before optional visual sidecars.

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
    mode_profile = get_docgen_mode_profile(digest_mode)
    if not mode_profile.is_sprint:
        markdown = _append_practice_section(markdown, questions, digest_mode=digest_mode, title=draft.title)
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
