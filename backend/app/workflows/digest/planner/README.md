# Planner 链路

最后更新：2026-08-13

职责：把用户目标和资料变成可确认的 `confirmed_plan`。Planner 不生成正文，不写 KG，不更新 Profile。

```text
输入: user_prompt + file_ids + latest_plan + diagnose_answers
输出: latest_plan / confirmed_plan
```

## 主流程

```text
collect_planner_context
  -> compose_planner_draft
  -> save_planner_draft
```

## 1. `collect_planner_context`

输入：`course_id`, `user_id`, `file_ids`, `user_prompt`, `latest_plan`

动作：读取上传资料、解析结果、历史 plan；短资料直接拼接，长资料按 Planner 上下文预算抽取结构、摘要和代表性片段并保留 `section_ref`；资料未解析完成时降级使用文件名和 metadata。读取完成后，并行整理目标边界和临时课程身份。临时名称只接受用户明确写出的课程主题，不能从“覆盖 A、B、C”里取 A 冒充整门课程；正式展示名称由 LLM 根据完整范围生成。整个准备节点不调用 LLM。

输出：`material_context`, `selected_file_ids`, `digest_mode`, `planner_context_stats`, `planning_note`, `material_note`, `generated_course_name`, `generated_course_icon_key`

关键字段：

```text
material_context.source_documents
material_context.material_sections
material_context.material_digest
material_context.material_hints.chapter_candidates
material_context.learning_domain_profile.key_topics
planning_note
material_note
```

## 2. `compose_planner_draft`

输入：`material_context`, `planning_note`, `material_note`, `latest_plan`, `diagnose_answers`, `diagnose_status`, `diagnose_note`

动作：先判断是否需要前置诊断；如果不需要或已回答，则生成正式方案。

首次创建时，Planner 用一次轻量 LLM 调用，根据课程目标、资料边界和最近对话同时生成可展示的课程短标题与四道个性化前置诊断题。用户回答或跳过后，再用一次 LLM 调用生成正式方案。两次调用属于两个独立的人机交互轮次，不恢复意图识别、资料二次总结或独立课程身份生成等冗余链路。

诊断输出：

```text
planner_stage: diagnosis
diagnose_status: pending
diagnose[]: question, purpose, options, answer
```

正式方案输出：

```text
course_name
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
```

正式方案 LLM 只生成用户需要确认的 `course_name / plan / suggestion` 和每章 `title / objective / required_elements`。其中 `required_elements` 表示确认覆盖的具体概念、方法、题型或易错对象，不负责开篇方式、讲解顺序、资料落点、例题数量、练习或小测策略；这些执行决策由 DocGen 在拥有完整资料路由和诊断答案后统一生成。Planner 本地只做标签/JSON 解析、显式章数校验、去编号等格式规范；字段缺失、重复章节、章数不符或出现长 OCR/代码碎片时调用一次 LLM repair，不用固定模板补教学语义，也不合并或改写模型章节。

`writing_instructions` 只作为历史 confirmed plan 的可选兼容字段保留；新 Planner 不再生成或要求该字段。

## 3. `save_planner_draft`

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

影响 DocGen：解释深度、例题密度、练习密度、测后反馈、前置知识补充。

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
