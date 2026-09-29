---
schema: aiteachme.question-skill/v2
package_key: scenario_interview
version: 2.0.0
name: 情境面试题
description: 通过具体情境考查问题分析、处理步骤、最终结论和表达质量。
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
    - key: analysis
      label: 问题分析
      control: long_text
      required: true
      min_length: 20
      max_length: 2500
    - key: steps
      label: 处理步骤
      control: long_text
      required: true
      min_length: 20
      max_length: 3000
    - key: conclusion
      label: 最终回答
      control: short_text
      required: true
      min_length: 5
      max_length: 800
grading:
  pass_score: 0.6
  rubric:
    - key: analysis_quality
      label: 分析质量
      weight: 0.35
      description: 识别主要问题、条件和风险，没有遗漏决定性信息。
    - key: step_quality
      label: 步骤质量
      weight: 0.35
      description: 处理步骤有顺序、可执行并体现课程方法。
    - key: conclusion_quality
      label: 结论质量
      weight: 0.2
      description: 最终回答准确且与分析和步骤一致。
    - key: communication
      label: 表达质量
      weight: 0.1
      description: 表达清楚、简洁并能让面试者复核思路。
tools:
  bindings: tools/bindings.json
---

# 情境面试题

把开放式面试题转换为三个稳定字段，便于网页、纸质考卷和评分器共享同一题目合同。
