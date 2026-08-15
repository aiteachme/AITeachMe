# Examine Exam Grade 链路

最后更新：2026-06-15

职责：批改考试、生成逐题反馈，并基于批改结果生成考试学习指南。

```text
输入: ExamPaperItem + user answer
输出: grade_decisions + ExamStudyGuideResponse
```

## 主流程

```text
START
  -> mode == grade_exam  -> grade_exam
  -> mode == study_guide -> generate_study_guide
```

## 两种模式

| mode | 入口 | 输出 |
| --- | --- | --- |
| `grade_exam` | `run_exam_grade_workflow` | `grade_decisions` |
| `study_guide` | `run_exam_study_guide_workflow` | `ExamStudyGuideResponse` |

## 1. `grade_exam`

输入：

```text
course_id
course_name
items: list[ExamPaperItem]
```

`ExamPaperItem` 关键字段：

```text
item_order
question_type
difficulty
stem_snapshot
options_snapshot_json
answer_snapshot
explanation_snapshot
answer_content
score
time_spent_seconds
hint_used
confidence_self_report
```

动作：按题并发判分。

输出：

```text
grade_decisions
```

`grade_decisions[]`：

```text
is_correct
score_obtained
score_max
feedback_text
error_cause_label
grading_mode
```

## 2. 客观题判定

适用题型：

```text
single_choice
multiple_choice
multi_choice
true_false
```

输入：

```text
answer_snapshot
answer_content
question_type
stem_snapshot
options_snapshot_json
explanation_snapshot
```

动作：

```text
1. 规则判断对错
2. LLM 生成反馈和错因标签
3. LLM 失败时使用默认反馈
```

输出：

```text
is_correct
score_obtained = score 或 0
score_max = score
feedback_text
error_cause_label
grading_mode = objective_rule
```

关键规则：

| 题型 | 判定方式 |
| --- | --- |
| 单选 | 标准答案和用户答案规范化后相等 |
| 多选 | 标准答案集合和用户答案集合相等 |
| 判断 | 中英文真假表达归一化后相等 |

## 3. 主观题判定

适用题型：

```text
fill_blank
short_answer
未知题型
```

输入：

```text
stem_snapshot
answer_snapshot
explanation_snapshot
answer_content
score
```

动作：

```text
1. 未作答直接判 0 分
2. 已作答调用 LLM 结构化判分
3. LLM 失败时退回文本精确匹配
```

输出：

```text
is_correct
score_obtained
score_max
feedback_text
error_cause_label
grading_mode = subjective_llm 或 subjective_fallback
```

关键字段：

| 字段 | 作用 |
| --- | --- |
| `score_obtained` | Profile 掌握度更新的核心得分证据 |
| `error_cause_label` | 错因统计和学习指南会使用 |
| `grading_mode` | 标记本题是规则判分、LLM 判分还是兜底判分 |

## 4. API 写回判卷结果

位置：`_grade_exam`

输入：`grade_decisions`

动作：把判卷结果写回试卷和题目快照。

输出：

```text
ExamPaper.status = graded
ExamPaper.total_score
ExamPaper.score_obtained
ExamPaper.graded_at
ExamPaperItem.is_correct
ExamPaperItem.score_obtained
ExamPaperItem.score_max
ExamPaperItem.feedback_text
ExamPaperItem.error_cause_label
ExamPaperItem.graded_at
```

## 5. 触发 Profile 更新

入口：`run_profile_update_workflow`

输入：

```text
exam_paper_id
user_id
course_id
```

Profile 会继续读取：

```text
ExamPaperItem.is_correct
ExamPaperItem.score_obtained
ExamPaperItem.score_max
ExamPaperItem.question_type
ExamPaperItem.difficulty
ExamPaperItem.time_spent_seconds
ExamPaperItem.hint_used
ExamPaperItem.confidence_self_report
QuestionKnowledgeUnitLink.knowledge_unit_id
QuestionKnowledgeUnitLink.coverage_weight
```

输出：

```text
UserKnowledgeState
review_task_ids
course.profile_json
user.profile_json
```

## 6. `generate_study_guide`

输入：

```text
exam_paper_id
course_id
course_name
exam_title
score_summary
wrong_question_summaries
knowledge_unit_performance
pending_reviews
generated_at
```

输入来源：

| 字段 | 来源 |
| --- | --- |
| `score_summary` | 当前试卷得分、题量、正确/错误数量 |
| `wrong_question_summaries` | 当前试卷错题与未作答摘要 |
| `knowledge_unit_performance` | 当前试卷关联知识点的题数、得分率与累计画像上下文 |
| `pending_reviews` | 当前试卷相关的 Profile 待复习任务（内部原因码先转换为中文） |

动作：等待当前试卷完成 Profile 同步后再生成复盘；重点知识点按本卷关联题目的加权得分率排序并由后端校准。累计画像仍传给 LLM，用于判断问题是偶发还是持续以及调整建议优先级，但不作为重点知识点的展示指标。各分区在代码层限制数量：优势最多 2 条、重点知识点最多 3 个、优先补漏最多 3 条、下一步最多 3 条。

输出：`ExamStudyGuideResponse`

```text
exam_paper_id
course_name
generated_at
overall_summary
strengths
priority_gaps
action_steps
review_tasks
focus_units
```

`review_tasks` 仅为旧客户端兼容字段，新指南固定返回空数组；待复习信息已合并进 `action_steps`。

`focus_units[]`：

```text
knowledge_unit_id
knowledge_unit_name
paper_attempts
paper_correct_attempts
paper_score_obtained
paper_score_max
paper_score_rate
mastery_score
reason
```

`paper_*` 是本卷展示与排序指标；`mastery_score` 仅保留累计画像兼容与个性化上下文，客户端重点知识点卡片不显示该值。

## 7. 学习指南缓存

位置：`_study_guide_detail`

输入：`ExamStudyGuideResponse`

动作：写入或读取 `ExamStudyGuideCache`，避免重复生成。缺少当前本卷指标版本、包含旧 `review_tasks`、内部状态码、无效知识点编号或超量分区的旧缓存会自动失效并重新生成。

输出：

```text
ExamStudyGuideCache.guide_json
ExamStudyGuideCache.status
ExamStudyGuideCache.generated_at
```

## 模型策略

模型调用统一走 `lib/model_policy.py`。

整卷逐题判分统一走 `run_llm_tasks`。

LangSmith 追踪字段由 `graph.py` 的 `NODE_TRACE_DETAILS` 维护。
