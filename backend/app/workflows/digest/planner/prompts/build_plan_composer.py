"""Prompts for composing final planner build plans."""

from __future__ import annotations

from app.workflows.digest.planner.prompts.examples import render_composer_examples
from app.workflows.digest.planner.lib.research_probe import EvidenceBrief, LearningIntentProfile, PlanSketch, material_topic_hints
from app.workflows.digest.common.models import DigestMaterialContext


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
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context, limit=10)) or "暂无明显主题"
    sources = "；".join(source.title for source in evidence_brief.opened_sources[:4]) or "暂无打开来源"
    sketch_tasks = "；".join(plan_sketch.research_tasks[:8]) or plan_sketch.raw_text
    provisional_chapters = "；".join(plan_sketch.provisional_chapters[:8]) or "暂无暂定章节"
    core_concepts = "、".join(evidence_brief.core_concepts[:10]) or "暂无明确概念清单"
    evidence_hints = "；".join(
        f"{item.chapter_hint}=>{item.evidence_summary}"
        for item in evidence_brief.chapter_evidence_hints[:6]
    ) or "暂无章节级证据提示"
    prompt = (
        "请综合草稿、用户意图和证据摘要，生成一份可确认的知识文档构建计划。\n\n"
        f"主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"模式：{digest_mode}\n"
        f"语气：{tone}\n"
        f"资料主题：{topics}\n\n"
        f"草稿任务：{sketch_tasks}\n\n"
        f"草稿暂定章节：{provisional_chapters}\n\n"
        f"意图类型：{intent_profile.goal_type}\n"
        f"成功标准：{'；'.join(intent_profile.success_criteria)}\n"
        f"证据摘要：{evidence_brief.concept_briefing}\n"
        f"核心概念：{core_concepts}\n"
        f"已打开来源：{sources}\n\n"
        f"章节级证据提示：{evidence_hints}\n\n"
        "你不是在把草稿、意图和证据逐段拼接。你需要先完成真正的综合：\n"
        "1. 判断资料到底在讲哪几个知识簇；\n"
        "2. 判断哪些知识簇应该合并成一章，哪些应该拆开；\n"
        "3. 判断每章应该更偏概念总结、题型突破、易错辨析还是速查复盘；\n"
        "4. 再生成一版更像真实知识文档目录的计划。\n\n"
        "输出必须符合 BuildPlannerDraft 结构。章节标题要具体，"
        "每章要包含 objective、required_elements、search_queries、writing_instructions、media_hints。\n\n"
        "硬约束：\n"
        "1. 章节标题要像后续详细知识文档的真实目录。\n"
        "2. 优先把草稿里的“暂定章节”改写成更自然的总结型标题，而不是完全重起炉灶。\n"
        "3. 如果证据提示已经体现主题边界，章节标题要反映这些证据，而不是重复用户原句。\n"
        "4. search_queries 必须能直接驱动后续 research / docgen。\n"
        "5. required_elements 必须是该章真正要覆盖的知识元素，而不是空泛标签。\n"
        "6. 不要把来源标题、网站名、作者名写入 title、objective、search_queries。\n"
        "7. sprint 模式更聚焦考点/题型/公式/易错点；systematic 模式更强调概念主线、结构、方法和应用。\n\n"
        "请参考这些 few-shot 规律：\n"
        f"{render_composer_examples()}"
    )
    return [
        {"role": "system", "content": "你是 AITeachMe 的构建计划合成器，只生成结构化学习计划。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_plan_composer_messages"]
