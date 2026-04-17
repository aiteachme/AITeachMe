"""Prompts for planner plan sketch streaming."""

from __future__ import annotations

from app.workflows.digest.planner.prompts.examples import render_plan_sketch_examples
from app.workflows.digest.planner.lib.models import material_topic_hints
from app.workflows.digest.common.models import DigestMaterialContext


def _render_material_context(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料正文上下文"
    return digest


def build_plan_sketch_prompt(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    material_context: DigestMaterialContext,
    message_history: list[str],
) -> str:
    topics = "、".join(material_topic_hints(material_context, limit=8)) or "暂无明显主题"
    files = "、".join(doc.filename for doc in material_context.source_documents[:5]) or "暂无已解析文件"
    history = "\n".join(f"- {item}" for item in message_history[-4:] if str(item).strip()) or "暂无补充意见"
    material_excerpt = _render_material_context(material_context)
    return (
        "你是 AITeachMe 的学习规划助手。"
        "请先生成一份给用户看的“可见思考过程”，不要输出正式构建方案，也不要写知识文档正文。"
        "这里的思考过程是用户可读的规划摘要，不要暴露隐藏推理链或内部草稿。\n\n"
        f"学科/主题：{subject}\n"
        f"用户目标：{user_goal}\n"
        f"模式：{digest_mode}\n"
        f"语气：{tone}\n"
        f"主题提示：{topics}\n"
        f"资料文件：{files}\n"
        f"资料原文上下文（每份资料最多前 10000 tokens）：\n{material_excerpt}\n\n"
        f"最近对话：\n{history}\n\n"
        "你必须严格按下面的两行格式输出，不要加解释，不要写 Markdown 标题：\n\n"
        "1. 关注重点：用一句话列出 4-6 个资料里最该抓的具体知识对象、题型、公式、易错点或章节边界。\n"
        "2. 预计计划大纲：用分号列出 4-6 个后续可能展开的讲义方向。\n\n"
        "硬约束：\n"
        "1. 只能输出两条编号内容：关注重点、预计计划大纲。\n"
        "2. 不允许输出 #、##、代码块、JSON、网站名、来源标题、subj_ 标识。\n"
        "3. 不要写空泛表达，例如“梳理基础”“强化理解”“提升能力”；必须落到资料里的具体对象。\n"
        "4. 全文控制在 220 字以内。\n\n"
        "请参考下面这些 few-shot 示例的风格和格式，注意它们都是“思考过程”示例，不是最终方案：\n\n"
        f"{render_plan_sketch_examples()}"
    )


__all__ = ["build_plan_sketch_prompt"]
