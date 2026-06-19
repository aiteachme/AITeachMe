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
    source_slices: Sequence[Mapping[str, Any]] = (),
    evidence_items: Sequence[Mapping[str, Any]] = (),
    plan: str = "",
    docgen_history_brief: str = "",
    learner_profile_text: str = "",
) -> list[dict[str, str]]:
    profile = get_docgen_mode_profile(digest_mode)
    density_policy = dict(profile.example_density_policy)
    chapter_end_min = int(density_policy.get("chapter_end_practice_min_tasks", 2) or 2)
    chapter_end_max = max(chapter_end_min, int(density_policy.get("chapter_end_practice_max_tasks", 4) or 4))
    course_flow = "；".join(profile.course_flow_hints)
    practice_focus = "；".join(profile.practice_focuses)
    content_mix = "\n".join(f"- {key}: {value}" for key, value in profile.content_mix_policy.items())
    coverage_policy = "\n".join(f"- {item}" for item in profile.coverage_policy)
    source_slice_lines = "\n".join(
        "- "
        + " | ".join(
            str(item.get(key) or "").strip()
            for key in ("filename", "section_ref", "section_title", "summary")
            if str(item.get(key) or "").strip()
        )
        for item in list(source_slices or [])[:8]
        if isinstance(item, Mapping)
    )
    evidence_lines = "\n".join(
        "- "
        + " | ".join(
            str(item.get(key) or "").strip()
            for key in ("evidence_id", "source_title", "text")
            if str(item.get(key) or "").strip()
        )
        for item in list(evidence_items or [])[:8]
        if isinstance(item, Mapping)
    )
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
- learner_profile: {learner_profile_text or "none"}

骨架线索：
- glossary_terms: {", ".join(str(item) for item in glossary_terms)}
- claim_targets: {", ".join(str(item) for item in claim_targets)}
- confusion_targets: {", ".join(str(item) for item in confusion_targets)}

本章资料边界（只用于确定本章写什么，不要照抄成长段正文）：
{source_slice_lines or "- none"}

高置信证据（只用于选择要覆盖的重点和例题方向）：
{evidence_lines or "- none"}

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
    "topic": ["..."],
    "concept": ["..."],
    "principle": ["..."],
    "formula_model": ["..."],
    "procedure": ["..."],
    "skill": ["..."],
    "misconception": ["..."],
    "application_case": ["..."]
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
3. `content_role_targets` 是主合同，要按学习图谱 8 类节点列出本章最应该覆盖的目标；每类最多 2 条，空类可省略。
4. `content_role_targets`、`concept_targets`、`example_targets`、`pitfall_targets` 中的每一项都必须是具体课程对象、方法名、题型名或错因名；不要输出“图示”“方法步骤”“单元测试”“重点检查概念理解”“讲后纠错与回顾”“为后续章节打底”“整理”“判定题”“图表分析”等教学脚手架或短泛词。若上游 required_elements 有这类表达，必须改写成真实对象，例如“函数图像读图”“函数值求解例题”“自变量与因变量混淆”“函数综合练习题型”“统计数据整理方法”“几何判定条件识别”“图表分析结论表达”；找不到具体对象就不要列入这些字段。
5. `example_coverage_plan` 列出本章正文中需要用例题、案例、操作示例、变式训练或自测覆盖的重点；target 也必须是具体知识对象或题型，不能写“例题”“案例一”“单元测试”。
6. `chapter_end_practice_plan` 是最终 `## 单元测试` 模块的测试计划：每章默认 {chapter_end_min}-{chapter_end_max} 个小题/案例检查/操作任务/边界辨析/迁移任务；传统题不适合的学科也要转成可判断的任务，并规划答案、判定依据或解析要点。
7. 紧凑节奏先判断本章角色：概念章安排短例子、反例和条件辨析；方法章安排步骤、检查点和例题；训练章围绕真实题型或任务差异安排标准例题、变式检查和错误诊断。
8. 每个 `example_coverage_plan` 和 `chapter_end_practice_plan` 项的 `purpose` 写清这道例题/案例帮助学生学会什么；自测、辨析或思考题同步规划参考答案、判定依据或解题要点。
9. 如果 learner_profile 含“前置诊断信号”或“文档落点”，把相关选择落到 `teaching_outline`、`example_coverage_plan`、`chapter_end_practice_plan`、错因提醒或测后反馈中，不要只复述诊断答案。
10. 旧字段 `concept_targets`、`definition_targets`、`formula_targets`、`example_targets`、`pitfall_targets` 只做兼容输出，各最多 2 条。
11. `retrieval_queries` 最多 2 条。
12. 不允许顺带修改标题。
13. 不要输出媒体请求，这些后续由规则节点派生。
14. 只输出简短、可执行的字段，不要输出长段解释。
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
            "has_learner_profile": bool(learner_profile_text),
            "glossary_count": len(list(glossary_terms or [])),
            "claim_target_count": len(list(claim_targets or [])),
            "source_slice_count": len(list(source_slices or [])),
            "evidence_item_count": len(list(evidence_items or [])),
        },
        output=messages,
    )


__all__ = ["build_chapter_execution_brief_messages"]
