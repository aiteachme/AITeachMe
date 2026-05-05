"""Prompt builders for DocGen repair patches."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_chapter_patch_messages(
    *,
    chapter_title: str,
    action: dict,
    markdown_context: str,
    full_markdown_chars: int,
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的章节修补器。
你只能根据给定复核动作产出一段局部补丁片段，由系统负责插入原章节。
禁止新增、删除或重排章节；禁止引入没有证据支撑的新事实；禁止输出整章 Markdown。
如果复核动作是 evidence_patch，你只能使用章节已有正文、已有来源口径和复核动作中的线索补强表达：
- 能安全补证据说明时，补到相关小节附近。
- 不能确认来源时，收窄断言、补充条件或不确定性提示。
- 不要编造书名、页码、URL、实验结果或外部事实。
可见标题保持课程讲义口吻，必要时去掉草稿痕迹或内部修补口吻。
修补内容优先融入现有相关小节，避免新增生硬的“修补说明”小节。
""".strip()
    user_prompt = f"""
章节标题：{chapter_title}

复核动作：
{action}

当前章节相关上下文：
{markdown_context}

原章节总长度：{full_markdown_chars} 字符

输出要求：
1. 只返回一段可插入的局部 Markdown 补丁，不要返回完整章节。
2. 不要包裹 ```markdown 代码块，不要输出解释。
3. 只改复核动作指向的问题，不做风格大改。
4. 如果无法安全修补，返回 no_change。
5. 如果需要新增例题，要保留题目、推理/解析和易错提醒等学习价值。
6. 标题、列表和解析步骤保持标准 Markdown 结构。
7. 保留已有 `> [!TIP]`、`> [!IMPORTANT]`、`> [!WARNING]` 提示块风格；新增快速抓手、核心前提或易错提醒时也优先使用标准提示块。
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
            "markdown_context_chars": len(markdown_context),
            "full_markdown_chars": full_markdown_chars,
        },
        output=messages,
    )


__all__ = ["build_chapter_patch_messages"]
