# Profile Update 链路

最后更新：2026-06-15

职责：考试批改后更新掌握度、复习任务、薄弱点和画像摘要。

```text
输入: exam_paper_id
输出: UserKnowledgeState + course.profile_json + user.profile_json
```

## 主流程

```text
resolve_profile_context
  -> update_mastery
  -> schedule_reviews
  -> analyze_weakness
  -> refresh_course_profile
  -> refresh_user_profile
```

## 1. `resolve_profile_context`

输入：`course_id`, `user_id`, `exam_paper_id`, `top_n`

动作：校验考试卷、课程、用户，补齐上下文。

输出：`course_id`, `user_id`, `exam_paper_id`, `error`

## 2. `update_mastery`

输入：`exam_paper_id`, `ExamPaperItem`, `QuestionKnowledgeUnitLink`

读取答题字段：

```text
is_correct
difficulty
question_type
answered_at
time_spent_seconds
hint_used
confidence_self_report
error_cause_label
```

读取知识点绑定：

```text
knowledge_unit_id
coverage_weight
```

动作：按 `knowledge_unit_id` 聚合 attempts；用 `coverage_weight` 分摊贡献；计算本次表现；和历史掌握度合并；upsert `UserKnowledgeState`。

输出：`mastery_result`, `updated_state_ids`, `mastery_updated`

写入字段：

```text
mastery_score
confidence_score
stability_score
review_priority
total_attempts
correct_attempts
last_attempt_at
source_exam_paper_id
state_version
last_recomputed_at
stats_json
```

核心生成规则：

```text
mastery_score: 历史掌握度 + 本次考试表现加权合并
confidence_score: min(1, total_attempts / 10)
stability_score: 连续正确表现换算
review_priority: 初始 1 - mastery_score
stats_json: 题型/难度/错因/提示/用时/自评统计
```

## 3. `schedule_reviews`

输入：`updated_state_ids`, `mastery_score`, `stability_score`, SM-2 字段

动作：计算 `forgetting_due_at`；掌握度足够则 `idle`，不足则生成 `pending` 复习。

输出：`review_task_ids`, `review_scheduled`

更新字段：

```text
forgetting_due_at
review_status
scheduled_review_at
review_interval_days
review_ease_factor
review_repetition_count
review_reason
review_priority
```

## 4. `analyze_weakness`

输入：`course_id`, `user_id`, `UserKnowledgeState`, `top_n`

动作：按掌握度、近期错误率、遗忘风险计算弱点优先级。

输出：`weaknesses`, `weaknesses_ranked`

`weaknesses[]`：`knowledge_unit_id`, `mastery_score`, `priority`, `reason`

## 5. `refresh_course_profile`

输入：`UserKnowledgeState`, recent exam items, pending reviews, conversation signals

动作：生成课程级画像，写入 `course.profile_json`。

输出：`course_profile`

`course_profile`：

```text
avg_mastery
weak_knowledge_unit_count
pending_review_count
due_review_count
recommended_question_types
recommended_exam_mode
recommended_question_count
difficulty_focus
focus_knowledge_unit_ids
question_type_accuracy
difficulty_accuracy
profile_text
notes
```

## 6. `refresh_user_profile`

输入：active courses, course profiles, recent exams, pending reviews, conversation signals

动作：生成用户级画像，写入 `user.profile_json`。

输出：`user_profile`

`user_profile`：

```text
active_course_count
active_course_ids
recent_course_ids
preferred_question_types
preferred_exam_modes
dominant_exam_mode
explanation_style
pace_preference
consistency_level
pending_review_count
due_review_count
profile_text
notes
```

## 下游

```text
UserKnowledgeState -> Profile snapshot / Review tasks / Examine 优先知识点
course.profile_json + user.profile_json -> Profile 页面 / study_plan / DocGen learner_profile_text
```

## 修改检查

- 改 mastery 公式要关注 `coverage_weight`。
- 改 review 字段要同步 Profile 页面和 study plan。
- 改 profile_json 要同步 DocGen `learner_profile.py`。
