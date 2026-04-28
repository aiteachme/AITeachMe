"""Prompts for chapter-level execution brief generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def build_chapter_execution_brief_messages(
    *,
    subject_name: str,
    digest_mode: str,
    chapter: Mapping[str, Any],
    locked_title: str,
    intent_core: Mapping[str, Any],
    glossary_terms: Sequence[str],
    claim_targets: Sequence[str],
    confusion_targets: Sequence[str],
) -> list[dict[str, str]]:
    profile = get_docgen_mode_profile(digest_mode)
    course_flow = "；".join(profile.course_flow_hints)
    practice_focus = "；".join(profile.practice_focuses)
    system_prompt = """
你是 AITeachMe 的 DocGen 章节执行 brief 设计器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
你的任务是生成“最小可执行脚手架”，不是写完整教学大纲。
""".strip()
    prompt = f"""
请为下面这一章生成简短执行 brief。

主题：{subject_name}
模式：{profile.mode}（{profile.prompt_label}）
锁定标题：{locked_title}

章节合同：
- chapter_index: {chapter.get("chapter_index")}
- objective: {chapter.get("objective")}
- required_elements: {", ".join(str(item) for item in chapter.get("required_elements", []))}

文档级写作意图：
{dict(intent_core or {})}

骨架线索：
- glossary_terms: {", ".join(str(item) for item in glossary_terms)}
- claim_targets: {", ".join(str(item) for item in claim_targets)}
- confusion_targets: {", ".join(str(item) for item in confusion_targets)}

模式参考，不是固定目录：
- 写作优先级：{profile.prompt_priority}
- 课程化节奏：{course_flow}
- 例题/练习方向：{practice_focus}

请输出 JSON：
{{
  "chapter_index": 1,
  "teaching_outline": ["..."],
  "concept_targets": ["..."],
  "definition_targets": ["..."],
  "formula_targets": ["..."],
  "example_targets": ["..."],
  "pitfall_targets": ["..."],
  "retrieval_queries": ["..."],
  "plan_mismatch_warnings": []
}}

要求：
1. 这是最小执行 brief，不是完整教学大纲。
2. `teaching_outline` 最多 3 条，要写成教学动作，不要写固定章节标题。
3. `concept_targets`、`definition_targets`、`formula_targets`、`example_targets`、`pitfall_targets` 各最多 2 条；`example_targets` 要优先体现本模式的例题/练习方向。
4. `retrieval_queries` 最多 2 条。
5. 不允许顺带修改标题。
6. 不要输出媒体请求或练习策略，这些后续由规则节点派生。
7. 只输出简短、可执行的字段，不要输出长段解释。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "chapter_execution_brief",
        inputs={
            "subject_name": subject_name,
            "digest_mode": digest_mode,
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "glossary_count": len(list(glossary_terms or [])),
            "claim_target_count": len(list(claim_targets or [])),
        },
        output=messages,
    )


__all__ = ["build_chapter_execution_brief_messages"]
