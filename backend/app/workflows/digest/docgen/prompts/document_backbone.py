"""Prompt builder for the document-wide semantic backbone."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_document_backbone_messages(
    *,
    course_name: str,
    digest_mode: str,
    task_seeds: Sequence[Mapping[str, object]],
    research_agenda: Mapping[str, object],
    evidence_units: Sequence[Mapping[str, object]],
    file_summaries: Sequence[Mapping[str, object]],
    learner_profile_text: str = "",
    max_retrieval_queries_per_chapter: int = 2,
) -> list[dict[str, str]]:
    """Build one whole-document prompt for semantics and chapter execution briefs."""

    system_prompt = """
你是 AITeachMe 的整本文档准备设计器。
你只输出合法 JSON，不输出 Markdown、解释或额外文本。
你的任务是一次性完成两件事：
1. 统一整本课程的术语、符号、关键主张、前置依赖和易混点；
2. 为每个已确认章节生成具体、可执行的 Writer brief。
你不能修改用户已经确认的章节数量、顺序、标题、目标和覆盖范围，也不是生成最终知识图谱。
""".strip()
    user_prompt = f"""
请为下面的整门课程生成一份紧凑、可执行的 DocumentPreparationBundle。

课程：{course_name or "未命名课程"}
模式：{digest_mode or "systematic"}
学习者与前置诊断信号：
{learner_profile_text or "暂无"}

已确认章节 seed（章节数量、顺序和边界不可修改）：
{_json(list(task_seeds))}

骨架研究线索（只是候选线索，不能仅因出现于此就当成事实）：
{_json(dict(research_agenda))}

资料摘要：
{_json(list(file_summaries))}

高置信证据：
{_json(list(evidence_units))}

请输出与以下结构一致的 JSON：
{{
  "document_backbone": {{
    "canonical_glossary": [
      {{"term":"...","aliases":["..."],"definition":"...","source_hint":"...","target_chapters":[1]}}
    ],
    "concept_dependency_graph": [
      {{"from_concept":"...","to_concept":"...","relation":"prerequisite_for","reason":"..."}}
    ],
    "notation_registry": [
      {{"symbol":"...","meaning":"...","target_chapters":[1],"source_hint":"..."}}
    ],
    "canonical_claim_pool": [
      {{"claim_id":"claim_001","claim_type":"core","claim_text":"...","target_chapter":1,"importance":0.8,"requires_evidence":true,"source_hint":"..."}}
    ],
    "confusion_map": [
      {{"confusion_id":"confusion_001","topic":"...","contrast":"...","resolution_hint":"...","target_chapters":[1]}}
    ],
    "source_trust_summary": {{}},
    "fallback_used": false
  }},
  "chapter_execution_briefs": [
    {{
      "chapter_index": 1,
      "teaching_outline": ["..."],
      "writing_instructions": ["..."],
      "content_role_targets": {{"concept":["..."],"procedure":["..."],"skill":["..."],"misconception":["..."]}},
      "example_coverage_plan": [{{"target":"...","form":"worked_example","purpose":"..."}}],
      "chapter_end_practice_plan": [{{"target":"...","form":"short_answer","purpose":"..."}}],
      "concept_targets": ["..."],
      "definition_targets": ["..."],
      "formula_targets": ["..."],
      "example_targets": ["..."],
      "pitfall_targets": ["..."],
      "retrieval_queries": ["..."],
      "plan_mismatch_warnings": [],
      "fallback_used": false
    }}
  ]
}}

整本骨架要求：
1. 只生成会被两个或更多章节共同使用、或会显著影响跨章一致性的项目；不要把每个 required_element 都复制成术语。
2. 术语定义、符号含义和事实主张必须可信。资料明确提供时优先依据资料，并把文件名、section_ref 或 evidence source_ref 写入 source_hint；资料没有提供但属于稳定通识时可标注 `general_knowledge`。
3. 不确定、课程专属但资料未定义、或可能随上下文改变的内容不要猜；宁可省略。
4. dependency 只表达真实的概念或技能前置关系，不能把章节先后顺序伪装成知识依赖。
5. confusion 必须是确实需要跨章统一辨析的概念边界，不输出泛泛的“容易混淆”。
6. target_chapters 和 target_chapter 只能引用已确认章节编号。
7. canonical_claim_pool 只放需要各章一致遵守的关键主张，不复述章节目标；没有可靠依据时保持为空。
8. source_trust_summary 由系统根据实际来源统计覆盖，请输出空对象；fallback_used 固定为 false。

章节执行 brief 要求：
1. chapter_execution_briefs 必须与已确认章节逐一对应，chapter_index 不得缺失、重复或越界。
2. 已确认 seed 中的 chapter_goal 和 required_elements 是用户确认边界。brief 只能细化怎样讲、怎样举例、怎样练习和怎样检索，不能替换、删除或扩张为另一门课程。
3. teaching_outline 给出 2-4 个本章专属的讲解阶段；writing_instructions 给出 2-5 条 Writer 可直接执行的具体策略。结合学习者诊断决定篇幅、解释层次、例题密度、小测和答案解析粒度。
4. content_role_targets、concept/definition/formula/example/pitfall targets 必须是可在本章正文中落地的具体课程对象；不要写“图示”“讲解”“方法步骤”“多练习”等空泛教学动作。
5. example_coverage_plan 和 chapter_end_practice_plan 应依据诊断中的题目密度与解析要求配置；没有必要时可以保持精简，但不能机械复制同一模板到所有章节。
6. retrieval_queries 每章最多 {max_retrieval_queries_per_chapter} 条，服务于该章确认范围和资料证据定位，不搜索已被其他章节负责的内容。
7. 资料明确提供时，把资料摘要和高置信证据用于讲解顺序、案例与易错点设计；资料没有提供时可基于稳定通识设计教学路径，但不要伪造资料来源或事实依据。
8. 旧方案可能在 seed 的 style_rules 中带有已确认写作提示；存在时必须保留其意图。新方案没有这些提示时，直接根据问卷、全书骨架、章节目标和资料生成。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "document_backbone",
        inputs={
            "course_name": course_name,
            "digest_mode": digest_mode,
            "chapter_count": len(task_seeds),
            "file_summary_count": len(file_summaries),
            "evidence_unit_count": len(evidence_units),
            "has_learner_profile": bool(learner_profile_text),
            "max_retrieval_queries_per_chapter": max_retrieval_queries_per_chapter,
        },
        output=messages,
    )


__all__ = ["build_document_backbone_messages"]
