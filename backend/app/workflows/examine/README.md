# Examine 工作流

最后更新：2026-06-15

`examine/` 负责考试引擎：从知识图谱生成题目，再根据用户答案判卷，并把结果交给 Profile 更新掌握度。

```text
KnowledgeUnit + KnowledgeRelation + Profile mastery
  -> question_build
  -> ExamPaper / ExamPaperItem / QuestionKnowledgeUnitLink
  -> exam_grade
  -> profile.update
  -> study_guide
```

## 目录

```text
examine/
  question_build/   # 生成结构化题目
  exam_grade/       # 判卷和学习指南
  prewarm.py        # 默认隐藏练习卷预生成
  exports.py        # 稳定导出面
```

对应文档：

- [question_build/README.md](question_build/README.md)
- [exam_grade/README.md](exam_grade/README.md)

## 三条链路

| 链路 | 触发 | 写库 | 输出 |
| --- | --- | --- | --- |
| `question_build` | 生成试卷 | 间接由 API 写库 | `generated_questions`, `question_blueprints` |
| `exam_grade.grade_exam` | 提交试卷或单题判分 | 间接由 API 写库 | `grade_decisions` |
| `exam_grade.study_guide` | 查看考试学习指南 | 是，写缓存 | `ExamStudyGuideResponse` |

## 总流程

## 1. 准备考试上下文

入口：`POST /courses/{course_id}/exams/generate`

输入：`course_id`, `user_id`, `exam_mode`, `num_questions`, `user_prompt`, `sample_file_ids`

动作：读取课程、可出题 `KnowledgeUnit`、知识图谱边、Profile 掌握度、待复习/薄弱知识点。

输出：

```text
exam_units
knowledge_graph_edges
mastery_by_unit_id
priority_unit_ids
question_count
system_constraints
```

## 2. 生成题目

入口：`run_question_build_workflow`

输入：上一步输出 + `course_name`, `course_description`, `course_user_intent`

动作：筛知识点、规划题型要求、分配考查知识点、生成题目。

输出：

```text
question_blueprints
generated_questions
failed_questions
candidate_unit_ids
scope/filter diagnostics
```

关键字段：

```text
generated_questions[].item_order
generated_questions[].question_type
generated_questions[].difficulty
generated_questions[].stem
generated_questions[].options
generated_questions[].correct_answer
generated_questions[].explanation
generated_questions[].knowledge_unit_refs
```

## 3. API 落库成试卷

位置：`backend/app/api/exams.py`

输入：`generated_questions`, `question_blueprints`

动作：写入题库模板、试卷题目快照、题目和知识点的加权关系。

输出：

```text
QuestionTemplate
ExamPaper
ExamPaperItem
QuestionKnowledgeUnitLink
paper_preview_json
selection_context_json
```

关键字段：

```text
QuestionKnowledgeUnitLink.knowledge_unit_id
QuestionKnowledgeUnitLink.coverage_weight
ExamPaperItem.selection_context_json.blueprint
ExamPaperItem.score
```

## 4. 用户作答

输入：`exam_paper_item_id`, `answer_content`, `time_spent_seconds`, `hint_used`, `confidence_self_report`

动作：API 保存用户答案和作答行为。

输出：待判卷的 `ExamPaperItem`

## 5. 判卷

入口：`run_exam_grade_workflow`

输入：`course_id`, `course_name`, `items`

动作：客观题规则判定，主观题 LLM 判分；所有题生成反馈和错因标签。

输出：

```text
grade_decisions[].is_correct
grade_decisions[].score_obtained
grade_decisions[].score_max
grade_decisions[].feedback_text
grade_decisions[].error_cause_label
grade_decisions[].grading_mode
```

## 6. API 写回判卷结果

位置：`_grade_exam`

输入：`grade_decisions`

动作：更新 `ExamPaperItem` 和 `ExamPaper` 得分、状态、批改时间。

输出：

```text
ExamPaper.status = graded
ExamPaper.score_obtained
ExamPaper.total_score
ExamPaperItem.is_correct
ExamPaperItem.feedback_text
ExamPaperItem.error_cause_label
```

## 7. 更新 Profile

入口：`run_profile_update_workflow`

输入：`exam_paper_id`, `user_id`, `course_id`

动作：根据题目知识点覆盖权重、得分、错因、题型、难度更新掌握度和复习任务。

输出：

```text
UserKnowledgeState
review_task_ids
course.profile_json
user.profile_json
```

## 8. 生成学习指南

入口：`run_exam_study_guide_workflow`

输入：考试得分摘要、错题摘要、Profile 薄弱点、待复习项。

动作：生成考试后的复盘建议，并缓存到 `ExamStudyGuideCache`。

输出：

```text
overall_summary
strengths
priority_gaps
action_steps
review_tasks
focus_units
```

## 与其他模块的边界

Examine 读取 Digest 生成的 `KnowledgeUnit` 和 `KnowledgeRelation`，但不生成知识图谱。

Examine 不直接读取 Planner 的 `diagnose` 字段；`diagnose` 主要进入 Digest DocGen。

Examine 负责产出 Profile 所需的考试证据：题目、知识点覆盖、作答、判分、错因。

Profile 负责把这些证据沉淀成长期画像。
