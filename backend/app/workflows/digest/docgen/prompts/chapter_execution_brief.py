"""Prompts for chapter-level execution brief generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_chapter_execution_brief_messages(
    *,
    course_name: str,
    digest_mode: str,
    chapter: Mapping[str, Any],
    locked_title: str,
    intent_core: Mapping[str, Any],
    glossary_terms: Sequence[str],
    claim_targets: Sequence[str],
    confusion_targets: Sequence[str],
    plan: str = "",
    docgen_history_brief: str = "",
) -> list[dict[str, str]]:
    profile = get_docgen_mode_profile(digest_mode)
    course_flow = "；".join(profile.course_flow_hints)
    practice_focus = "；".join(profile.practice_focuses)
    content_mix = "\n".join(f"- {key}: {value}" for key, value in profile.content_mix_policy.items())
    coverage_policy = "\n".join(f"- {item}" for item in profile.coverage_policy)
    system_prompt = """
你是 AITeachMe 的知识文档章节执行简报设计器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
你的任务是生成“最小可执行脚手架”，不是写完整教学大纲。
""".strip()
    prompt = f"""
请为下面这一章生成简短执行简报。

主题：{course_name}
模式：{profile.prompt_label}
锁定标题：{locked_title}

学习大纲：
- chapter_index: {chapter.get("chapter_index")}
- objective: {chapter.get("objective")}
- required_elements: {", ".join(str(item) for item in chapter.get("required_elements", []))}

文档级写作意图：
{dict(intent_core or {})}

Planner handoff:
- plan: {plan or "not provided"}
- docgen_history_brief: {docgen_history_brief or "none"}

骨架线索：
- glossary_terms: {", ".join(str(item) for item in glossary_terms)}
- claim_targets: {", ".join(str(item) for item in claim_targets)}
- confusion_targets: {", ".join(str(item) for item in confusion_targets)}

模式参考，不是固定目录：
- 写作优先级：{profile.prompt_priority}
- 课程化节奏：{course_flow}
- 例题/练习方向：{practice_focus}
- 内容角色比例参考：
{content_mix}
- 例题覆盖要求：
{coverage_policy}

请输出 JSON：
{{
  "chapter_index": 1,
  "teaching_outline": ["..."],
  "content_role_targets": {{
    "core_knowledge": ["..."],
    "method_demo": ["..."],
    "explanation_support": ["..."],
    "principle_reasoning": ["..."],
    "practice_assessment": ["..."],
    "knowledge_organization": ["..."],
    "application_extension": ["..."]
  }},
  "example_coverage_plan": [
    {{"target": "...", "example_type": "worked_example_or_case", "purpose": "...", "min_examples": 1}}
  ],
  "chapter_end_practice_plan": [
    {{"target": "...", "example_type": "chapter_end_practice", "purpose": "...", "min_examples": 1}}
  ],
  "concept_targets": ["..."],
  "definition_targets": ["..."],
  "formula_targets": ["..."],
  "example_targets": ["..."],
  "pitfall_targets": ["..."],
  "retrieval_queries": ["..."],
  "plan_mismatch_warnings": []
}}

要求：
1. 这是最小执行简报，不是完整教学大纲。
2. `teaching_outline` 最多 3 条，要写成教学动作，不要写固定章节标题。
3. `content_role_targets` 是主合同，要按 7 类学习内容角色列出本章最应该覆盖的目标；每类最多 2 条，空类可省略。
4. `example_coverage_plan` 必须列出本章正文中需要用例题、案例、操作示例、变式训练或自测覆盖的重点；密度要按章节角色决定，不要让每章都长成同一种练习模板。
5. `chapter_end_practice_plan` 是章末短练习收束：每章默认 2-4 个小题/案例检查/操作任务/边界辨析/迁移任务；传统题不适合的学科也要转成可判断的任务，并规划答案、判定依据或解析要点。
6. 快速复习节奏要先由模型根据本章材料判断本章角色：只有天然适合集中练习或任务训练的章节，才围绕真实题型或任务差异规划更多标准例题、变式检查和错误诊断；概念、定义、过渡或铺垫章节只规划必要的短例子、反例、条件辨析或小任务。`content_role_targets.knowledge_organization` 只在本章确实需要时说明分类、任务整理、方法对照或判断表应覆盖哪些对象。
7. 每个 `example_coverage_plan` 和 `chapter_end_practice_plan` 项的 `purpose` 要说明这道例题/案例帮助学生学会什么，不要写成“复习一下”；如果输出的是自测、辨析或思考题，也必须规划参考答案、判定依据或解题要点，不能只给问题。
8. 旧字段 `concept_targets`、`definition_targets`、`formula_targets`、`example_targets`、`pitfall_targets` 只做兼容输出，各最多 2 条。
9. `retrieval_queries` 最多 2 条。
10. 不允许顺带修改标题。
11. 不要输出媒体请求，这些后续由规则节点派生。
12. 只输出简短、可执行的字段，不要输出长段解释。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "chapter_execution_brief",
        inputs={
            "course_name": course_name,
            "digest_mode": digest_mode,
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "has_plan": bool(plan),
            "has_docgen_history": bool(docgen_history_brief),
            "glossary_count": len(list(glossary_terms or [])),
            "claim_target_count": len(list(claim_targets or [])),
        },
        output=messages,
    )


__all__ = ["build_chapter_execution_brief_messages"]
