"""Prompts for planner plan sketch streaming."""

from __future__ import annotations

from app.workflows.digest.planner.prompts.examples import render_plan_sketch_examples
from app.workflows.digest.planner.lib.models import material_topic_hints
from app.workflows.digest.common.models import DigestMaterialContext


_MAX_DIGEST_CHARS = 6000


def _render_material_digest(material_context: DigestMaterialContext) -> str:
    digest = (material_context.material_digest or "").strip()
    if not digest:
        return "暂无资料摘要"
    if len(digest) <= _MAX_DIGEST_CHARS:
        return digest
    return digest[: _MAX_DIGEST_CHARS - 1].rstrip() + "…"


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
    digest = _render_material_digest(material_context)
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
        f"资料摘要：\n{digest}\n\n"
        f"最近对话：\n{history}\n\n"
        "你必须严格按下面的 Markdown 合同输出，不要加解释：\n\n"
        "# 思考过程\n\n"
        "> 我会先用一句话说明当前资料和目标该怎么拆。\n\n"
        "## 思考重点\n"
        "1. ...\n"
        "2. ...\n"
        "3. ...\n\n"
        "## 计划大纲\n"
        "1. ...\n"
        "2. ...\n"
        "3. ...\n\n"
        "## 规划假设\n"
        "- ...\n\n"
        "## 待确认点\n"
        "- ...\n\n"
        "硬约束：\n"
        "1. 必须使用上述标题层级和有序列表格式。\n"
        "2. 思考重点和计划大纲必须是标准 Markdown 有序列表，不要用 (1) 文本编号。\n"
        "3. 不允许输出网站名、来源标题、subj_ 标识、代码块、JSON。\n"
        "4. 思考重点必须服务后续详细知识文档生成，不能只写空泛口号。\n"
        "5. 计划大纲必须像真实讲义目录，不能是“概述/总结/提升”这类模板名。\n"
        "6. 全文尽量控制在 260 字以内，每条只写一个清晰动作或方向。\n\n"
        "请参考下面这些 few-shot 示例的风格和格式，注意它们都是“思考过程”示例，不是最终方案：\n\n"
        f"{render_plan_sketch_examples()}"
    )


__all__ = ["build_plan_sketch_prompt"]
