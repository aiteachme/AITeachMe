"""Prompt builders for DocGen repair patches."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_chapter_patch_messages(
    *,
    chapter_title: str,
    actions: list[dict],
    markdown_context: str,
    full_markdown_chars: int,
    repair_round: int = 1,
    max_patch_chars: int = 2200,
    quantity_contract: dict | None = None,
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的章节修补器。
你只能根据给定复核动作列表产出一段局部补丁片段，由系统负责插入或替换指定小节。
禁止新增、删除或重排章节；禁止引入没有证据支撑的新事实；禁止输出整章 Markdown。
如果复核动作是 evidence_patch，你只能使用章节已有正文、已有来源口径和复核动作中的线索补强表达：
- 能安全补证据说明时，补到相关小节附近。
- 不能确认来源时，收窄断言、补充条件或不确定性提示。
- 不要编造书名、页码、URL、实验结果或外部事实。
可见标题保持课程讲义口吻，必要时去掉草稿痕迹或内部修补口吻。
修补内容优先融入现有相关小节，避免新增生硬的“修补说明”小节。
标题必须由本章上下文自然命名，禁止把关键词拼成固定标题，禁止输出泛化目录标题、学习动作标题、内部检查标题、序号占位题型或证据整理标题。
唯一例外：如果复核动作要求修复章末测试模块，必须输出一份完整的 `## 单元测试` 替换块；系统会替换旧模块或在缺失时追加。
如果动作要求补入 forbidden_scope 或明显属于其它章节的主题，只能返回 no_change，并把对应 action 放入 unresolved_action_ids。
""".strip()
    user_prompt = f"""
章节标题：{chapter_title}

复核动作列表：
{actions}

用户确认的当前章数量与写作边界（优先于模式默认）：
{quantity_contract or {}}

当前修补轮次：第 {repair_round} 轮

当前章节相关上下文：
{markdown_context}

原章节总长度：{full_markdown_chars} 字符

输出要求：
1. 只返回一段局部 Markdown 补丁，不要返回完整章节。补充缺失内容时 operation=append；修正已有正文、题干或答案错误时 operation=replace_section，返回 target_anchor 所指小节的完整替换内容，并原样保留该小节标题和题目数量；不得保留旧的错误答案后再追加相反结论。
2. 不要包裹 ```markdown 代码块，不要输出解释。
3. 尽量在这一段 patch 内一次性处理所有可安全处理的复核动作。
4. 如果无法安全修补，返回 no_change。
5. 如果修复章末单元测试，patch 必须从唯一的 `## 单元测试` 开始并包含整个新测试模块。每题严格使用 `> [!QUESTION] **Q01｜题型｜难度｜考点：具体考点**`，题干非空；下一块必须是独立的 `> [!ANSWER]`，内部先写独立的 `> **答案**` 再写答案，必要时写 `> **解析步骤**`。不得把答案留在 QUESTION 中，不得合并多题答案，不得输出游离答案。只有选择题使用 A-D 四个选项；判断、填空、短答、步骤和迁移任务不得显示选项。输出前遮住旧答案逐题独立复算，确保正确选项唯一、完整答案属于 A-D 之一、题解每一步成立且结论与答案一致。
6. 除固定章末 `## 单元测试` 外，新增标题必须具体说明本章知识对象、方法、题型或操作任务；不要使用固定表头、泛标题或序号占位题型名。
7. 普通新增片段尽量控制在 1200 字符；本次完整替换块最多 {max_patch_chars} 字符，必须保留目标模块中的题干、答案和解析。append 不要复制已有小节；replace_section 只返回目标小节，不能跨越其边界。不要一次输出多个已有二级标题。
8. 完整例题、案例和章末练习不要放进大块 callout；提示块只用于短提示、短警告或短重点。
9. 在结构化字段 covered_action_ids 中列出这段 patch 实际覆盖的 repair_action_key；无法安全处理的放入 unresolved_action_ids。
10. 修补公式、定理或应用方法时必须保留适用条件和边界：定义域、区间、端点、分母、符号、旋转轴与半径距离不得省略；不要重复已有题干或练习。
11. 保留用户明确规定的小节、示例和练习数量，以及正文篇幅和主题边界；不要为了补充内容额外增加同类示例或题目。正文小节数量不含固定的章末单元测试；需要补充说明时融入已有小节。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "chapter_patch",
        inputs={
            "chapter_title": chapter_title,
            "action_count": len(actions),
            "action_types": [str(action.get("action_type") or "") for action in actions],
            "chapter_index": actions[0].get("chapter_index") if actions else None,
            "repair_round": repair_round,
            "markdown_context_chars": len(markdown_context),
            "full_markdown_chars": full_markdown_chars,
        },
        output=messages,
    )


__all__ = ["build_chapter_patch_messages"]
