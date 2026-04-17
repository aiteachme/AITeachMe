"""Prompts for composing final planner build plans."""

from __future__ import annotations

from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import (
    EvidenceBrief,
    LearningIntent,
    PlannerBrief,
    material_topic_hints,
)
from app.workflows.digest.planner.prompts.examples import render_composer_examples

PLAN_JSON_MARKER = "<PLAN_JSON>"
PLAN_JSON_END_MARKER = "</PLAN_JSON>"


def _render_material_context(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料正文上下文"
    return digest


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
    planner_brief: PlannerBrief,
    learning_intent: LearningIntent,
    evidence_brief: EvidenceBrief,
    message_history: list[str] | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context, limit=10)) or "暂无明显主题"
    opened_sources = [source for source in evidence_brief.sources if source.opened]
    sources = "；".join(source.title for source in opened_sources[:4]) or "暂无打开来源"
    sketch_tasks = "；".join(planner_brief.focus_points[:8]) or planner_brief.markdown
    provisional_chapters = "；".join(planner_brief.outline_items[:8]) or "暂无暂定章节"
    core_concepts = "、".join(evidence_brief.core_concepts[:10]) or "暂无明确概念清单"
    evidence_hints = "；".join(evidence_brief.chapter_hints[:6]) or "暂无章节级证据提示"
    material_excerpt = _render_material_context(material_context)
    prompt = (
        "请综合思考过程、用户意图、检索证据和资料原文，生成一份可确认的知识文档构建计划。\n"
        "你这一次输出同时承担两件事：先给用户可见的大纲整理过程，再给系统可解析的 JSON 合同。\n\n"
        f"主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"模式：{digest_mode}\n"
        f"语气：{tone}\n"
        f"资料主题：{topics}\n\n"
        f"资料原文上下文（每份资料最多前 10000 tokens）：\n{material_excerpt}\n\n"
        f"最近对话与修改意见：\n{_compact_message_history(message_history)}\n\n"
        f"上一版方案：\n{_compact_latest_plan(latest_plan)}\n\n"
        f"草稿任务：{sketch_tasks}\n\n"
        f"草稿暂定章节：{provisional_chapters}\n\n"
        f"意图类型：{learning_intent.goal_type}\n"
        f"目标受众：{learning_intent.audience}\n"
        f"成功标准：{'；'.join(learning_intent.success_criteria)}\n"
        f"约束：{'；'.join(learning_intent.constraints)}\n"
        f"证据摘要：{evidence_brief.summary}\n"
        f"核心概念：{core_concepts}\n"
        f"已打开来源：{sources}\n\n"
        f"章节级证据提示：{evidence_hints}\n\n"
        "你不是在把草稿、意图和证据逐段拼接。你需要先完成真正的综合：\n"
        "1. 判断资料到底在讲哪几个知识簇；\n"
        "2. 判断哪些知识簇应该合并成一章，哪些应该拆开；\n"
        "3. 判断每章应该更偏概念总结、题型突破、易错辨析还是速查复盘；\n"
        "4. 再生成一版更像真实知识文档目录的计划。\n\n"
        "输出格式必须严格分两段：\n"
        "第一段只输出下面两条可见内容，控制在 280 字以内：\n"
        "3. 计划大纲整理：用 4-6 个短句说明将如何合并、拆分和排序章节。\n"
        "4. 暂定章节方向：用分号列出 4-8 个章节标题方向，每个标题要具体。\n\n"
        f"第二段必须从单独一行 {PLAN_JSON_MARKER} 开始，随后输出一个合法 JSON 对象，最后以 {PLAN_JSON_END_MARKER} 结束。\n"
        "JSON 必须符合 BuildPlannerDraft 结构，包含 subject、user_goal、digest_mode、tone、selected_skillpacks、"
        "chapter_plan、research_queries、media_plan、build_constraints、plan_summary。"
        "每章必须包含 chapter_index、title、objective、required_elements、search_queries、writing_instructions、media_hints。"
        "media_hints 固定包含 images、mermaid、interactive 三个数组。\n\n"
        "JSON 形状示意：\n"
        "{\n"
        '  "subject": "主题名",\n'
        '  "user_goal": "用户目标",\n'
        '  "digest_mode": "systematic",\n'
        '  "tone": "encouraging",\n'
        '  "selected_skillpacks": [],\n'
        '  "chapter_plan": [\n'
        "    {\n"
        '      "chapter_index": 1,\n'
        '      "title": "具体章节标题",\n'
        '      "objective": "本章学习目的",\n'
        '      "required_elements": ["知识元素"],\n'
        '      "search_queries": ["检索查询"],\n'
        '      "writing_instructions": "写作要求",\n'
        '      "media_hints": {"images": [], "mermaid": [], "interactive": []}\n'
        "    }\n"
        "  ],\n"
        '  "research_queries": ["整体检索查询"],\n'
        '  "media_plan": {"enable_mermaid": true, "enable_images": false, "enable_interactive_html": false},\n'
        '  "build_constraints": {"include_exercises": true, "include_sources": true, "math_mode": false, "target_chapter_count": 4},\n'
        '  "plan_summary": "一句话总结"\n'
        "}\n\n"
        "硬约束：\n"
        "1. 章节标题要像后续详细知识文档的真实目录，章节数量遵循当前模式的配置范围。\n"
        "2. 优先把草稿里的“暂定章节”改写成更自然的总结型标题，而不是完全重起炉灶。\n"
        "3. 如果证据提示已经体现主题边界，章节标题要反映这些证据，而不是重复用户原句。\n"
        "4. search_queries 围绕外部检索校准和当前主题写，每章 1-2 条即可。\n"
        "5. required_elements 必须是该章真正要覆盖的知识元素，每章 3-5 条即可。\n"
        "6. 不要把来源标题、网站名、作者名写入 title、objective、search_queries。\n"
        "7. 章节标题必须具体到资料中的知识对象、任务或能力边界，但不要绑定某个固定学科模板。\n"
        "8. objective 用一句话说明这一点为什么要学，尽量点出应用场景或易错风险，不超过 60 个中文字符。\n"
        "9. sprint 模式更聚焦考点/题型/公式/易错点；systematic 模式更强调概念主线、结构、方法和应用。\n"
        "10. JSON 段只能输出 JSON，不要放 Markdown 代码块、注释或尾随逗号。\n\n"
        "请参考这些 few-shot 规律：\n"
        f"{render_composer_examples()}"
    )
    return [
        {"role": "system", "content": "你是 AITeachMe 的构建计划合成器，必须同时输出可见规划摘要和可解析 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = [
    "PLAN_JSON_END_MARKER",
    "PLAN_JSON_MARKER",
    "build_plan_composer_messages",
]
