"""Prompt builders for DocGen content review."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def build_chapter_review_messages(
    *,
    chapter_title: str,
    digest_mode: str,
    chapter_task: dict,
    markdown: str,
    claim_ledger: dict,
    claim_evidence_map: dict,
    conflict_report: dict,
    rule_review: dict,
) -> list[dict[str, str]]:
    """Build messages for read-only chapter review."""

    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的内容质检员，只负责复核，不负责改写。
你必须严格检查章节是否符合用户已确认的章节合同、是否有证据支撑、是否越界、是否适合学习。
你不能新增事实，不能替正文打补丁，不能要求推翻已确认计划。
如果问题可以局部修，输出 action_type 为 `section_patch` 或 `evidence_patch`；只有整章严重不可用时才输出 `regenerate_chapter`。
证据不足时优先输出 action_type 为 `evidence_patch`，不要轻易要求整章重写。
""".strip()
    user_prompt = f"""
请复核下面这一章，并输出结构化结果。

章节标题：{chapter_title}
文档模式：{mode_label}

章节执行合同：
{chapter_task}

规则复核基线：
{rule_review}

主张台账：
{claim_ledger}

主张证据映射：
{claim_evidence_map}

冲突报告：
{conflict_report}

章节 Markdown：
{markdown}

复核要求：
1. 判断是否覆盖执行合同中的关键点。
2. 判断主张是否有足够证据支撑。
3. 判断是否越过章节边界或推翻已确认计划。
4. 判断是否适合学生学习，不要只看格式。
5. 检查 7 类学习内容角色是否按章节合同合理覆盖：核心知识、方法示范、解释辅助、原理推理、练习评估、知识组织、应用拓展。
6. 如果是速成课，重点检查例题、案例、变式、自测或实践任务是否足够支撑“会做题/会操作/会判断/会避坑”；例题密度不足时输出 `section_patch`。
7. 如果是系统课，重点检查核心知识点是否都有例题、案例、操作示例或练习任务覆盖；知识点缺少例题覆盖时输出 `section_patch`。
8. 检查展示质量：标题层级、加粗/高亮闭合、callout、表格、公式、代码块、Mermaid 是否可渲染；纯格式问题输出 `surface_patch`，不要升级为整章重写。
9. 检查知识图谱相关内容是否只使用 7 类学习节点与 8 类关系；关系方向明显错误时输出 `section_patch`。
10. 复核动作必须可执行，写清 `target_anchor`、`instruction`、`constraints`、`expected_effect`。
11. 只做复核判断，不输出修补后的正文。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "chapter_review",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "markdown_chars": len(markdown),
            "chapter_task_keys": sorted(chapter_task.keys()),
        },
        output=messages,
    )


__all__ = ["build_chapter_review_messages"]
