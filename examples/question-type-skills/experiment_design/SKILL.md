---
schema: aiteachme.question-skill/v2
package_key: experiment_design
version: 2.0.0
name: 实验设计题
description: 让学习者围绕一个知识问题提出可检验的实验方案。
template_key: generic_text_form_v2
runtime_key: structured_subjective_v1
renderer_key: structured_text_v1
grader_key: rubric_llm_v1
capabilities:
  modes:
    - question_bank
    - mastery_drill
    - web_practice
    - paper_exam
    - pdf
  hints: false
  immediate_feedback: false
files:
  generate_prompt: prompts/generate.md
  grade_prompt: prompts/grade.md
  feedback_prompt: prompts/feedback.md
  references: references/cases.json
answer_schema:
  fields:
    - key: hypothesis
      label: 实验假设
      control: long_text
      required: true
      min_length: 10
      max_length: 2000
      placeholder: 写出可检验的实验假设
    - key: procedure
      label: 实验步骤
      control: long_text
      required: true
      min_length: 20
      max_length: 4000
      placeholder: 按顺序描述实验步骤和测量方法
    - key: controls
      label: 变量与对照
      control: long_text
      required: true
      min_length: 10
      max_length: 2000
      placeholder: 说明自变量、因变量、控制变量和对照组
    - key: interpretation
      label: 结果解释
      control: long_text
      required: true
      min_length: 10
      max_length: 2000
      placeholder: 说明如何根据结果判断假设
grading:
  pass_score: 0.7
  rubric:
    - key: testability
      label: 可检验性
      weight: 0.25
      description: 假设明确、可观察并且能够通过实验验证。
    - key: procedure_validity
      label: 步骤有效性
      weight: 0.35
      description: 步骤能够产生与问题相关的可靠观察或测量。
    - key: variable_control
      label: 变量控制
      weight: 0.25
      description: 正确区分自变量、因变量、控制变量和对照。
    - key: interpretation
      label: 结果解释
      weight: 0.15
      description: 能根据不同结果清楚说明是否支持假设。
tools:
  bindings: tools/bindings.json
---

# 实验设计题

这是一个 V2 通用文本表单示例。它使用自由定义的四个字段，运行时和渲染器仍然复用平台已经发布的能力。
