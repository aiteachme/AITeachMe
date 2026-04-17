"""Prompt rendering helpers for the planner lane."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext


def render_material_digest(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    return digest or "暂无资料正文上下文"


def render_material_overview(material_context: DigestMaterialContext) -> str:
    profile = material_context.learning_domain_profile.build_context_string()
    files = [
        doc.filename
        for doc in material_context.source_documents
        if str(doc.filename or "").strip()
    ]
    stats = material_context.material_stats_profile.stats
    source_count = stats.total_sources or len(material_context.source_documents)
    section_count = stats.total_sections or len(material_context.material_sections)
    lines = [
        profile,
        f"资料文件：{'、'.join(files) if files else '暂无已解析文件'}",
        f"资料规模：{source_count} 个文件，{section_count} 个片段",
    ]
    return "\n".join(line for line in lines if line.strip())


def render_message_history(message_history: list[str] | None, *, limit: int = 4) -> str:
    cleaned = [str(item).strip() for item in message_history or [] if str(item).strip()]
    if not cleaned:
        return "暂无补充意见"
    return "\n".join(f"- {item}" for item in cleaned[-limit:])


def render_latest_plan(latest_plan: dict[str, Any] | None) -> str:
    if not latest_plan:
        return "暂无上一版方案"
    plan_summary = str(latest_plan.get("plan_summary") or "").strip()
    chapter_count = len(list(latest_plan.get("chapter_plan") or []))
    lines = [f"上一版章节数：{chapter_count}"]
    if plan_summary:
        lines.insert(0, f"上一版摘要：{plan_summary}")
    return "\n".join(lines)


__all__ = [
    "render_latest_plan",
    "render_material_digest",
    "render_material_overview",
    "render_message_history",
]
