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
你只能根据给定复核动作对当前章节做局部修补。
禁止新增、删除或重排章节；禁止引入没有证据支撑的新事实；禁止输出解释。
你必须返回完整的修补后 Markdown，保留原一级标题、已有 Mermaid、图片、例题/练习和来源口径。
可见标题保持课程讲义口吻，必要时去掉草稿痕迹或内部修补口吻。
修补内容优先融入现有相关小节，避免新增生硬的修补小节。
""".strip()
    user_prompt = f"""
章节标题：{chapter_title}

复核动作：
{action}

当前章节 Markdown：
{markdown}

输出要求：
1. 只输出修补后的完整 Markdown。
2. 不要包裹 ```markdown 代码块。
3. 只改复核动作指向的问题，不做风格大改。
4. 如果无法安全修补，原样返回 Markdown。
5. 如果需要新增例题，要保留题目、推理/解析和易错提醒等学习价值。
6. 标题、列表和解析步骤保持标准 Markdown 结构。
7. 保留已有 `> [!TIP]`、`> [!IMPORTANT]`、`> [!WARNING]` 提示块；不要把它们改回普通引用。新增快速抓手、核心前提或易错提醒时也优先使用标准提示块。
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
