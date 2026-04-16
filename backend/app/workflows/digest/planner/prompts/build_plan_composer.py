"""Prompts for composing final planner build plans."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import (
    EvidenceBrief,
    LearningIntentProfile,
    PlanSketch,
    material_topic_hints,
)
from app.workflows.digest.planner.prompts.examples import render_composer_examples

_MAX_DIGEST_CHARS = 5000


def _render_material_digest(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料摘要"
    if len(digest) <= _MAX_DIGEST_CHARS:
        return digest
    return digest[: _MAX_DIGEST_CHARS - 1].rstrip() + "…"


def _compact_message_history(message_history: list[str] | None) -> str:
    cleaned = [str(item).strip() for item in message_history or [] if str(item).strip()]
    if not cleaned:
        return "暂无补充修改意见"
    return "\n".join(f"- {item}" for item in cleaned[-6:])


def _compact_latest_plan(latest_plan: dict[str, Any] | None) -> str:
    if not latest_plan:
        return "暂无上一版方案"
    plan_summary = str(latest_plan.get("plan_summary") or "").strip()
    chapter_count = len(list(latest_plan.get("chapter_plan") or []))
    if plan_summary:
        return f"上一版摘要：{plan_summary}\n上一版章节数：{chapter_count}"
    return f"上一版章节数：{chapter_count}"


def build_plan_composer_messages(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    material_context: DigestMaterialContext,
    plan_sketch: PlanSketch,
    intent_profile: LearningIntentProfile,
    evidence_brief: EvidenceBrief,
    message_history: list[str] | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context, limit=10)) or "暂无明显主题"
    sources = "；".join(source.title for source in evidence_brief.opened_sources[:4]) or "暂无打开来源"
    sketch_tasks = "；".join(plan_sketch.research_tasks[:8]) or plan_sketch.raw_text
    provisional_chapters = "；".join(plan_sketch.provisional_chapters[:8]) or "暂无暂定章节"
    core_concepts = "、".join(evidence_brief.core_concepts[:10]) or "暂无明确概念清单"
    evidence_hints = (
        "；".join(
            f"{item.chapter_hint}=>{item.evidence_summary}"
            for item in evidence_brief.chapter_evidence_hints[:6]
        )
        or "暂无章节级证据提示"
    )
    digest = _render_material_digest(material_context)
    prompt = (
        "请综合思考过程、用户意图和外部证据摘要，生成一份可确认的知识文档构建计划。\n"
        "输出要短、清楚、分点，方便前端直接展示成几条计划大纲。\n\n"
        f"主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"模式：{digest_mode}\n"
        f"语气：{tone}\n"
        f"资料主题：{topics}\n\n"
        f"资料摘要：\n{digest}\n\n"
        f"最近对话与修改意见：\n{_compact_message_history(message_history)}\n\n"
        f"上一版方案：\n{_compact_latest_plan(latest_plan)}\n\n"
        f"草稿任务：{sketch_tasks}\n\n"
        f"草稿暂定章节：{provisional_chapters}\n\n"
        f"意图类型：{intent_profile.goal_type}\n"
        f"成功标准：{'；'.join(intent_profile.success_criteria)}\n"
        f"证据摘要：{evidence_brief.concept_briefing}\n"
        f"核心概念：{core_concepts}\n"
        f"已打开本地来源：{sources}\n\n"
        f"章节级证据提示：{evidence_hints}\n\n"
        "你不是在把草稿、意图和证据逐段拼接。你需要先完成真正的综合：\n"
        "1. 判断资料到底在讲哪几个知识簇；\n"
        "2. 判断哪些知识簇应该合并成一章，哪些应该拆开；\n"
        "3. 判断每章应该更偏概念总结、题型突破、易错辨析还是速查复盘；\n"
        "4. 再生成一版更像真实知识文档目录的计划。\n\n"
        "输出必须符合 BuildPlannerDraft 结构。章节标题要具体，"
        "每章要包含 objective、required_elements、search_queries、writing_instructions、media_hints。\n\n"
        "硬约束：\n"
        "1. 章节标题要像后续详细知识文档的真实目录，章节数量遵循当前模式的配置范围。\n"
        "2. 优先把草稿里的“暂定章节”改写成更自然的总结型标题，而不是完全重起炉灶。\n"
        "3. 如果证据提示已经体现主题边界，章节标题要反映这些证据，而不是重复用户原句。\n"
        "4. search_queries 围绕外部检索校准和当前主题写，每章 1-2 条即可。\n"
        "5. required_elements 必须是该章真正要覆盖的知识元素，每章 3-5 条即可。\n"
        "6. 不要把来源标题、网站名、作者名写入 title、objective、search_queries。\n"
        "7. 章节标题必须具体到资料中的知识对象、任务或能力边界，但不要绑定某个固定学科模板。\n"
        "8. objective 用一句话说明这一点为什么要学，尽量点出应用场景或易错风险，不超过 60 个中文字符。\n"
        "9. sprint 模式更聚焦考点/题型/公式/易错点；systematic 模式更强调概念主线、结构、方法和应用。\n\n"
        "请参考这些 few-shot 规律：\n"
        f"{render_composer_examples()}"
    )
    return [
        {"role": "system", "content": "你是 AITeachMe 的构建计划合成器，只生成结构化学习计划。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_plan_composer_messages"]
