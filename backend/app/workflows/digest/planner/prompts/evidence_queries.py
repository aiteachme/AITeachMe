"""Prompts for generating planner evidence queries."""

from __future__ import annotations

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import PlannerBrief, material_topic_hints

_MAX_DIGEST_CHARS = 3600


def _render_material_digest(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料摘要"
    if len(digest) <= _MAX_DIGEST_CHARS:
        return digest
    return digest[: _MAX_DIGEST_CHARS - 1].rstrip() + "…"


def build_evidence_query_messages(
    *,
    subject: str,
    user_goal: str,
    material_context: DigestMaterialContext,
    planner_brief: PlannerBrief,
    query_count: int,
) -> list[dict[str, str]]:
    topics = "、".join(material_topic_hints(material_context, limit=10)) or "暂无明显主题"
    focus = "；".join(planner_brief.focus_points[:8]) or "暂无关注重点"
    outline = "；".join(planner_brief.outline_items[:8]) or "暂无预计大纲"
    digest = _render_material_digest(material_context)
    prompt = (
        "请为 Planner 证据探测生成少量高质量检索问题。\n"
        "你只负责生成查询问题，不要决定使用哪个检索器，不要描述工具调用策略。\n\n"
        f"主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"资料主题提示：{topics}\n"
        f"可见思考关注重点：{focus}\n"
        f"预计计划大纲：{outline}\n"
        f"资料摘要：\n{digest}\n\n"
        f"输出 {query_count} 条中文查询。\n"
        "要求：\n"
        "1. 查询要能同时服务本地资料命中和外部资料校准。\n"
        "2. 每条必须包含具体知识对象、题型、概念边界、公式条件或易错点。\n"
        "3. 不要写“学习资料”“相关知识”“基础概念”这类空泛查询。\n"
        "4. 不要写网站名、来源标题、作者名或 URL。"
    )
    return [
        {"role": "system", "content": "你是 Planner 检索问题生成器，只输出结构化查询列表。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_evidence_query_messages"]
