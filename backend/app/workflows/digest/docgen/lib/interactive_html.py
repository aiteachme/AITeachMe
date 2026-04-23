"""Interactive HTML sidecar generation for DocGen chapter enhancement."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.storage import get_content_store, resolve_subject_storage_scope
from app.utils.path_helpers import sanitize_doc_title
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger, DocumentBackbone
from app.workflows.digest.docgen.prompts import build_interactive_html_messages

InteractiveMode = Literal["parameter_explorer", "process_stepper", "concept_mapper"]

_VISUAL_STRONG_MARKERS = (
    "函数",
    "图像",
    "几何",
    "空间",
    "导数",
    "微分",
    "积分",
    "方程",
    "概率",
    "分布",
    "变化",
    "单调性",
    "极值",
    "轨迹",
    "流程",
    "机制",
    "结构",
    "关系",
    "模拟",
    "实验",
)
_VISUAL_WEAK_MARKERS = (
    "公式",
    "定理",
    "性质",
    "方法",
    "步骤",
    "路径",
    "模型",
    "判定",
)
_EXCLUDE_MARKERS = (
    "提分策略",
    "易错点汇总",
    "复盘",
    "总结",
    "概述",
    "导论",
)
_FENCE_RE = re.compile(r"^```(?:html)?\s*\n(?P<body>.*)\n```$", re.IGNORECASE | re.DOTALL)


def _normalize_blob(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _build_signal_text(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
) -> str:
    claims = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text][:6]
    return "\n".join(
        [
            draft.title,
            draft.summary_draft,
            *claims,
            *[str(item.get("description") or "") for item in draft.placeholder_requests if isinstance(item, dict)],
        ]
    )


def choose_interactive_mode(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
) -> InteractiveMode:
    text = _build_signal_text(draft, claim_ledger=claim_ledger)
    if any(marker in text for marker in ("步骤", "方法", "流程", "换元", "分部积分", "求解")):
        return "process_stepper"
    if any(marker in text for marker in ("结构", "关系", "依赖", "网络", "概念图")):
        return "concept_mapper"
    return "parameter_explorer"


def should_generate_interactive_html(
    draft: ChapterDraft,
    *,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
) -> bool:
    del document_backbone
    signal = _build_signal_text(draft, claim_ledger=claim_ledger)
    normalized = _normalize_blob(signal)
    if any(_normalize_blob(marker) in normalized for marker in _EXCLUDE_MARKERS):
        return False
    strong_hits = sum(1 for marker in _VISUAL_STRONG_MARKERS if _normalize_blob(marker) in normalized)
    weak_hits = sum(1 for marker in _VISUAL_WEAK_MARKERS if _normalize_blob(marker) in normalized)
    formula_count = draft.markdown.count("$$") + draft.markdown.count("$")
    return strong_hits >= 1 and (weak_hits >= 1 or formula_count >= 2 or strong_hits >= 2)


def _chapter_context_excerpt(draft: ChapterDraft, *, limit: int = 2200) -> str:
    text = re.sub(r"```.*?```", "", draft.markdown, flags=re.DOTALL)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit].rstrip()


def _strip_html_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    match = _FENCE_RE.match(cleaned)
    if match is not None:
        return match.group("body").strip()
    return cleaned


def _sanitize_generated_html(html: str, *, title: str) -> str:
    cleaned = _strip_html_fence(html)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"<script[^>]+src=[\"'][^\"']+[\"'][^>]*>\s*</script>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<link[^>]+href=[\"']https?://[^\"']+[\"'][^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage)\s*\(", "void(", cleaned)
    if "<!DOCTYPE html>" not in cleaned[:80]:
        cleaned = "<!DOCTYPE html>\n" + cleaned
    if "<html" not in cleaned.lower():
        body = cleaned
        cleaned = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
</head>
<body>
{body}
</body>
</html>"""
    return cleaned.strip() + "\n"


def _build_preview_url(*, subject: str, asset_path: str, title: str) -> str:
    from urllib.parse import quote

    return (
        f"/subject/{quote(subject)}/knowledge-docs/interactive"
        f"?asset={quote(asset_path, safe='/')}"
        f"&title={quote(title)}"
    )


def _build_markdown_link(*, preview_url: str, link_label: str) -> str:
    return "\n".join(
        [
            "> [!TIP]",
            f"> 交互演示：[{link_label}]({preview_url})",
            "> 在新标签页打开预览页；页面会在沙箱 iframe 中加载。",
        ]
    )


async def maybe_generate_interactive_html_asset(
    *,
    draft: ChapterDraft,
    traced_context: TracedExecutionContext,
    digest_mode: str,
    claim_ledger: ClaimLedger | None = None,
    document_backbone: DocumentBackbone | None = None,
) -> dict[str, object] | None:
    if not should_generate_interactive_html(draft, claim_ledger=claim_ledger, document_backbone=document_backbone):
        return None

    interaction_mode = choose_interactive_mode(draft, claim_ledger=claim_ledger)
    concept_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type in {"definition", "core", "method"}][:4]
    formula_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_type == "formula"][:3]
    claim_targets = [item.claim_text for item in list((claim_ledger or ClaimLedger()).items or []) if item.claim_text][:5]
    chapter_context = _chapter_context_excerpt(draft)

    html = await acompletion_with_fallback(
        build_interactive_html_messages(
            chapter_title=draft.title,
            chapter_objective=draft.summary_draft,
            digest_mode=digest_mode,
            interaction_mode=interaction_mode,
            concept_targets=concept_targets,
            formula_targets=formula_targets,
            claim_targets=claim_targets,
            chapter_context=chapter_context,
        ),
        task_type=TaskType.DOCGEN,
        model="primary",
        temperature=0.1,
        max_tokens=2600,
        extra_metadata=traced_context.trace_metadata(
            docgen_stage="interactive_html_sidecar",
            asset_kind="interactive_html",
            chapter_index=draft.chapter_index,
        ),
    )
    cleaned_html = _sanitize_generated_html(str(html), title=draft.title)
    cs = get_content_store()
    subject_scope = resolve_subject_storage_scope(traced_context.subject)
    filename = f"docgen_interactive_{traced_context.build_session_id}_ch{draft.chapter_index:02d}_{sanitize_doc_title(draft.title)}.html"
    storage_key = f"{subject_scope.namespace}/assets/docgen/interactive/{filename}"
    asset_path = f"docgen/interactive/{filename}"
    await cs.write_text(storage_key, cleaned_html)
    preview_url = _build_preview_url(subject=traced_context.subject, asset_path=asset_path, title=draft.title)
    return {
        "asset_id": f"ch{draft.chapter_index:02d}_interactive_01",
        "chapter_index": draft.chapter_index,
        "kind": "interactive",
        "title": f"{draft.title} 交互演示",
        "interaction_mode": interaction_mode,
        "storage_key": storage_key,
        "asset_path": asset_path,
        "asset_url": f"/api/v1/subjects/{traced_context.subject}/files/assets/{asset_path}",
        "preview_url": preview_url,
        "open_mode": "new_tab",
        "link_markdown": _build_markdown_link(preview_url=preview_url, link_label=f"{draft.title} 交互演示"),
    }


__all__ = [
    "choose_interactive_mode",
    "maybe_generate_interactive_html_asset",
    "should_generate_interactive_html",
]
