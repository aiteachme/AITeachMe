"""Prompt builders for DocGen repair patches."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_chapter_patch_messages(
    *,
    chapter_title: str,
    action: dict,
    markdown: str,
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的章节修补器。
你只能根据给定 ReviewAction 对当前章节做局部修补。
禁止新增、删除或重排章节；禁止引入没有证据支撑的新事实；禁止输出解释。
你必须返回完整的修补后 Markdown，保留原一级标题、已有 Mermaid、图片、例题/练习和来源口径。
可见二级/三级标题必须像教材或课程讲义目录，来自知识对象、公式、方法、题型或应用场景；不要新增学习动作口号或内部修补口吻。
如果修补突击模式内容，优先把缺口融入“例题 + 解析 + 易错点”或已有知识小节，不要另起生硬的修补小节。
""".strip()
    user_prompt = f"""
章节标题：{chapter_title}

ReviewAction：
{action}

当前章节 Markdown：
{markdown}

输出要求：
1. 只输出修补后的完整 Markdown。
2. 不要包裹 ```markdown 代码块。
3. 只改 ReviewAction 指向的问题，不做风格大改。
4. 如果无法安全修补，原样返回 Markdown。
5. 如果需要新增例题，必须同时给出题目、解析步骤和易错点。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "chapter_patch",
        inputs={
            "chapter_title": chapter_title,
            "action_type": str(action.get("action_type") or ""),
            "chapter_index": action.get("chapter_index"),
            "markdown_chars": len(markdown),
        },
        output=messages,
    )


__all__ = ["build_chapter_patch_messages"]
