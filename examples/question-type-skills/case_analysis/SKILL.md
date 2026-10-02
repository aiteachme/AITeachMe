---
schema: aiteachme.question-skill/v2
package_key: case_analysis
version: 2.0.0
name: 案例分析题
description: 先提出处理建议，再说明案例中的依据与限制。
template_key: generic_text_form_v2
runtime_key: structured_subjective_v1
renderer_key: structured_text_v1
grader_key: rubric_llm_v1
capabilities:
  modes: [question_bank, mastery_drill, web_practice, paper_exam, pdf]
  hints: false
  immediate_feedback: false
files:
  generate_prompt: prompts/generate.md
  grade_prompt: prompts/grade.md
  references: references/cases.json
answer_schema:
  fields:
    - key: recommendation
      label: 处理建议
      control: short_text
      required: true
      min_length: 5
      max_length: 300
      placeholder: 用一句话概括建议
    - key: reasoning
      label: 依据与限制
      control: long_text
      required: true
      min_length: 10
      max_length: 3000
      placeholder: 结合案例事实说明理由，并指出不确定之处
grading:
  pass_score: 0.7
  rubric:
    - key: relevance
      label: 建议的针对性
      weight: 0.4
      description: 建议直接回应案例问题并可执行。
    - key: justification
      label: 论证质量
      weight: 0.6
      description: 使用案例事实和课程知识支持建议，承认推断限制。
tools:
  bindings: tools/bindings.json
---

# 案例分析题

两字段示例刻意采用“建议在前、论证在后”的顺序，验证字段按 key 存储，
并验证短文本与长文本可在同一个通用表单中工作。平台无需识别这个包名。
