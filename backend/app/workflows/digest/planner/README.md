# Planner 链路

最后更新：2026-06-15

职责：把用户目标和资料变成可确认的 `confirmed_plan`。Planner 不生成正文，不写 KG，不更新 Profile。

```text
输入: user_prompt + file_ids + latest_plan + diagnose_answers
输出: latest_plan / confirmed_plan
```

## 主流程

```text
collect_planner_context
  -> understand_goal_and_materials
      -> compose_planner_draft
      -> generate_course_identity
  -> save_planner_draft
```

## 1. `collect_planner_context`

输入：`course_id`, `user_id`, `file_ids`, `user_prompt`, `latest_plan`

动作：读取上传资料、解析结果、历史 plan；资料未解析完成时降级使用文件名和 metadata。

输出：`material_context`, `selected_file_ids`, `digest_mode`, `planner_context_stats`

关键字段：

```text
material_context.source_documents
material_context.material_sections
material_context.material_digest
material_context.material_hints.chapter_candidates
material_context.learning_domain_profile.key_topics
```

## 2. `understand_goal_and_materials`

输入：`material_context`, `user_prompt`, `digest_mode`, `latest_plan`

动作：并行生成目标理解和资料边界。

输出：

```text
planning_note: 用户目标、学习场景、规划判断
material_note: 资料边界、重点、缺失、风险
```

下游：`compose_planner_draft`, `generate_course_identity`, `confirmed_plan`

## 3. `compose_planner_draft`

输入：`material_context`, `planning_note`, `material_note`, `latest_plan`, `diagnose_answers`, `diagnose_status`, `diagnose_note`

动作：先判断是否需要前置诊断；如果不需要或已回答，则生成正式方案。

诊断输出：

```text
planner_stage: diagnosis
diagnose_status: pending
diagnose[]: question, purpose, options, answer
```

正式方案输出：

```text
suggestion
plan
chapters[]
diagnose
diagnose_status
diagnose_note
```

`chapters[]`：

```text
chapter_index
title
objective
required_elements
writing_instructions
```

## 4. `generate_course_identity`

输入：`material_context`, `planning_note`, `material_note`, `user_prompt`

动作：生成课程展示身份。

输出：`generated_course_name`, `generated_course_icon_key`

下游：`plan.course_name`, `plan.course_icon`, `confirmed_plan.course_name`

## 5. `save_planner_draft`

输入：`build_plan_draft`, `generated_course_name`, `generated_course_icon_key`, `diagnose_answers`, `diagnose_status`, `diagnose_note`

动作：规范化 draft；把 `diagnose_answers` 合并到 `diagnose[].answer`；保存 latest plan 和 planner turn。

输出：`plan`, `planner_record`, `planner_turns`, `selected_file_ids`

前端 plan 字段：

```text
course_id
selected_file_ids
course_name
course_icon
user_prompt
digest_mode
planning_note
suggestion
plan
chapters
diagnose
diagnose_status
diagnose_note
status
planner_session_id
confirmed_plan_id
model_override
```

## Diagnose 流程

```text
1. Planner 生成 diagnose
2. 前端展示 question/options
3. 用户提交 diagnose_answers
4. 后端按 question 写入 diagnose[].answer
5. 正式 plan 继续生成
6. confirm 写入 confirmed_plan
7. DocGen load_context 生成 diagnose_brief
8. diagnose_brief 拼入 learner_profile_text
```

影响 DocGen：解释深度、例题密度、练习密度、图示需求、前置知识补充。

不影响：Profile mastery、Examine 出题、KG 落库。

## Confirmed Plan

DocGen 只消费 `confirmed_plan`，核心字段：

```text
confirmed_plan_id
planner_session_id
course_id
selected_file_ids
user_prompt
digest_mode
model_override
course_name
course_icon
planning_note
suggestion
plan
chapters
diagnose
diagnose_status
diagnose_note
planner_context
docgen_history_brief
build_constraints
```

## 修改检查

- 影响 DocGen 的字段必须进入 `confirmed_plan`。
- 改 `diagnose` 要同步前端、Planner store、DocGen `load_context`。
- Planner 不写 `KnowledgeDoc`、`KnowledgeUnit`、`UserKnowledgeState`。
