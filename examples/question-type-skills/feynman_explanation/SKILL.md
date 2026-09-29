---
schema: aiteachme.question-skill/v2
package_key: feynman_explanation
version: 2.0.0
name: 费曼解释题
description: 要求学习者用自己的语言解释概念、依据、例子和适用边界。
template_key: generic_text_form_v2
runtime_key: structured_subjective_v1
renderer_key: structured_text_v1
grader_key: rubric_llm_v1
generation_constraints:
  numbered_task_count: 4
capabilities:
  modes:
    - question_bank
    - mastery_drill
    - web_practice
    - paper_exam
    - pdf
  hints: true
  immediate_feedback: true
files:
  generate_prompt: prompts/generate.md
  grade_prompt: prompts/grade.md
  feedback_prompt: prompts/feedback.md
  references: references/cases.json
answer_schema:
  fields:
    - key: explanation
      label: 你的解释
      control: long_text
      required: true
      min_length: 30
      max_length: 4000
      placeholder: 请面向第一次接触该概念的学习者，用自己的语言解释
grading:
  pass_score: 0.6
  rubric:
    - key: accuracy
      label: 概念准确性
      weight: 0.4
      description: 关键概念、关系和结论准确，没有实质性误解。
    - key: reasoning
      label: 解释与依据
      weight: 0.25
      description: 不只复述定义，还说明为什么以及关键因果关系。
    - key: example
      label: 举例能力
      weight: 0.2
      description: 给出有效例子并正确映射到概念。
    - key: boundary
      label: 适用边界
      weight: 0.15
      description: 说明成立条件、限制或反例。
tools:
  bindings: tools/bindings.json
---

# 费曼解释题

用于考查学习者是否真正理解一个知识点，而不是只会背诵定义。正文只说明使用目的；系统实际读取的出题、判分和反馈指引位于 `prompts/`。
