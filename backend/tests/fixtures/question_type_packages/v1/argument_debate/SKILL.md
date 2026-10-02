---
schema: aiteachme.question-skill/v1
package_key: argument_debate
version: 1.0.0
name: 结构化辩论题
description: 要求学习者明确立场、提供依据、准确呈现反方观点并作出回应。
template_key: argument_debate_v1
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
    - key: stance
      label: 你的立场
      control: short_text
      required: true
      min_length: 5
      max_length: 500
    - key: evidence
      label: 主要论据
      control: long_text
      required: true
      min_length: 20
      max_length: 2500
    - key: counterargument
      label: 最有力的反方观点
      control: long_text
      required: true
      min_length: 15
      max_length: 2000
    - key: rebuttal
      label: 你的回应
      control: long_text
      required: true
      min_length: 20
      max_length: 2500
grading:
  pass_score: 0.6
  rubric:
    - key: stance_quality
      label: 立场清晰度
      weight: 0.2
      description: 立场明确、可辩护且回应题目中的争点。
    - key: evidence_quality
      label: 论据质量
      weight: 0.3
      description: 论据准确、相关并能支持立场。
    - key: counterargument_quality
      label: 反方理解
      weight: 0.25
      description: 公平而准确地呈现最有力的反方观点。
    - key: rebuttal_quality
      label: 回应质量
      weight: 0.25
      description: 回应直接处理反方核心依据，而非回避或曲解。
tools:
  bindings: tools/bindings.json
---

# 结构化辩论题

V1 只记录一轮完整论证，不模拟多角色对话。题目必须存在可由课程知识支持的真实争点。
