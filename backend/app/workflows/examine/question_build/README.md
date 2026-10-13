# Examine Question Build 链路

最后更新：2026-06-15

职责：把课程知识点、知识图谱、用户要求和 Profile 掌握度变成结构化题目。

```text
输入: course + KnowledgeUnit + KG edges + mastery + priority + user_prompt
输出: question_blueprints + generated_questions + failed_questions
```

## 主流程

```text
filter_knowledge_units
  -> plan_question_requirements
  -> allocate_knowledge_units
  -> generate_questions
```

## 入口

`run_question_build_workflow`

输入：

```text
course_id
course_name
course_description
course_user_intent
exam_mode
course_context
user_prompt
system_constraints
question_count
units
knowledge_graph_edges
mastery_by_unit_id
priority_unit_ids
```

输出：

```text
candidate_unit_ids
question_requirement_plans
question_blueprints
generated_questions
failed_questions
```

## 1. `filter_knowledge_units`

输入：

```text
units
knowledge_graph_edges
mastery_by_unit_id
priority_unit_ids
user_prompt
question_count
course_name / course_description / course_user_intent
```

动作：用 LLM 结合知识图谱边、薄弱知识点、复习优先级和用户范围，筛出本轮组卷候选知识点。

输出：

```text
units                  # 已缩小范围的 KnowledgeUnit 列表
candidate_unit_ids
candidate_unit_limit
input_unit_count
candidate_unit_count
knowledge_graph_edge_count
scope_include_terms
scope_exclude_terms
scope_strict
filter_strategy
filter_rationale
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `candidate_unit_ids` | 后续只能优先围绕这些知识点出题 |
| `scope_include_terms` | 用户明确想考或模型识别出的包含范围 |
| `scope_exclude_terms` | 本轮应避开的范围 |
| `scope_strict` | 是否严格限制在用户指定范围内 |
| `filter_rationale` | 为什么选这些知识点 |

## 2. `plan_question_requirements`

输入：

```text
exam_mode
question_count
user_prompt
```

动作：先确定每一道题的题型和生成要求，不分配具体知识点。

输出：

```text
question_requirement_plans
question_requirement_rationale
```

`question_requirement_plans[]`：

```text
item_order
question_type
generation_prompt
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `question_type` | 题型：`single_choice`, `multiple_choice`, `true_false`, `fill_blank`, `short_answer` |
| `generation_prompt` | 这一题的生成约束，比如考法、表达、难度倾向 |

## 3. `allocate_knowledge_units`

输入：

```text
units                  # 第 1 步筛过的候选知识点
question_requirement_plans
mastery_by_unit_id
exam_mode
user_prompt
system_constraints
course_name / course_description / course_user_intent
```

动作：把每一道题的题型要求和候选知识点匹配，生成可执行题目蓝图。

输出：

```text
question_blueprints
```

`question_blueprints[]`：

```text
item_order
knowledge_unit_ids
question_type
difficulty
rationale
generation_prompt
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `knowledge_unit_ids` | 一题可覆盖 1 到 4 个知识点，第一个通常是主知识点 |
| `difficulty` | `easy`, `medium`, `hard` |
| `rationale` | 为什么这一题考这些知识点 |
| `generation_prompt` | 合并题型计划后的最终出题提示 |

## 4. `generate_questions`

输入：

```text
question_blueprints
units
course_name
course_description
course_user_intent
system_constraints
```

动作：按蓝图并发生成结构化题目；允许部分失败，失败题进入 `failed_questions`。

输出：

```text
generated_questions
generated_question_count
failed_questions
failed_question_count
```

`generated_questions[]`：

```text
item_order
question_type
difficulty
stem
options
correct_answer
correct_indices
explanation
knowledge_unit_refs
```

`knowledge_unit_refs[]`：

```text
knowledge_unit_id
coverage_weight
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `stem` | 题干 |
| `options` | 选择题选项，不带 A/B/C/D 标签 |
| `correct_indices` | 选择题标准答案下标，后端会转成 A/B/C/D |
| `correct_answer` | 非选择题标准答案，或后端规范化后的选择题答案 |
| `explanation` | 解析 |
| `coverage_weight` | 该题对某知识点的覆盖权重，后续 Profile 更新会用 |

## API 落库

位置：`backend/app/api/exams.py`

输入：`generated_questions`, `question_blueprints`

动作：

```text
1. upsert QuestionTemplate
2. create ExamPaperItem
3. replace QuestionKnowledgeUnitLink for template
4. replace QuestionKnowledgeUnitLink for paper item
5. 更新 paper_preview_json 和 selection_context_json
```

写入字段：

```text
QuestionTemplate.stem / answer / explanation / options_json
ExamPaperItem.stem_snapshot / answer_snapshot / explanation_snapshot
ExamPaperItem.selection_context_json.blueprint
QuestionKnowledgeUnitLink.knowledge_unit_id
QuestionKnowledgeUnitLink.coverage_weight
```

## 下游使用

```text
generated_questions
  -> ExamPaperItem
  -> exam_grade 判卷
  -> profile.update 计算掌握度
  -> study_guide 生成复盘建议
```

`question_build` 不直接更新 Profile；它只负责把题目和知识点覆盖关系准备好。

`question_build` 不读取 Planner `diagnose`；它读取的是用户出题提示、知识图谱和 Profile 掌握度。

## 模型策略

模型调用统一走 `lib/model_policy.py`。

并发题目生成统一走 `run_llm_tasks`。

LangSmith 追踪字段由 `graph.py` 的 `NODE_TRACE_DETAILS` 维护。
