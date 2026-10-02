---
schema: aiteachme.question-skill/v2
package_key: oral_defense
version: 2.0.0
name: 结构化答辩题
description: 要求学习者提出结论、给出课程依据，并说明结论的适用边界或反例。
template_key: generic_text_form_v2
runtime_key: structured_subjective_v1
renderer_key: structured_text_v1
grader_key: rubric_llm_v1
capabilities:
  modes: [question_bank, mastery_drill, web_practice, paper_exam, pdf]
  hints: true
  immediate_feedback: true
files:
  generate_prompt: prompts/generate.md
  grade_prompt: prompts/grade.md
  feedback_prompt: prompts/feedback.md
  references: references/cases.json
answer_schema:
  fields:
    - key: claim
      label: 你的结论
      control: short_text
      required: true
      min_length: 5
      max_length: 500
    - key: evidence
      label: 主要依据
      control: long_text
      required: true
      min_length: 20
      max_length: 3000
    - key: boundary
      label: 适用边界或反例
      control: long_text
      required: true
      min_length: 10
      max_length: 2000
grading:
  pass_score: 0.6
  rubric:
    - key: claim_quality
      label: 结论质量
      weight: 0.25
      description: 结论明确、准确并直接回应问题。
    - key: evidence_quality
      label: 依据质量
      weight: 0.35
      description: 依据来自课程知识且能够支持结论。
    - key: reasoning_quality
      label: 推理完整性
      weight: 0.25
      description: 从依据到结论的推理连贯，没有关键跳步。
    - key: boundary_quality
      label: 边界意识
      weight: 0.15
      description: 能指出适用条件、限制或有效反例。
tools:
  bindings: tools/bindings.json
---

# 结构化答辩题

把答辩拆成结论、依据和边界三个可评分字段，使用通用文本表单进行单次作答。
