# Profile 工作流

最后更新：2026-06-15

`profile/` 负责把考试表现变成用户画像和课程画像。

```text
Examine 批改结果
  -> profile.update
  -> UserKnowledgeState
  -> course.profile_json / user.profile_json
  -> profile.snapshot / study_plan / DocGen learner_profile
```

## 目录

```text
profile/
  common/       # 掌握度、复习、薄弱点、画像文本、共享节点
  update/       # 考试批改后更新画像
  snapshot/     # Profile 页面只读快照
  study_plan/   # 基于画像生成学习建议
```

对应文档：

- [update/README.md](update/README.md)
- [snapshot/README.md](snapshot/README.md)
- [study_plan/README.md](study_plan/README.md)

## 三条 Lane

| lane | 触发 | 是否写库 | 输出 |
| --- | --- | --- | --- |
| `profile.update` | 考试批改后 | 是 | 掌握度、复习任务、弱点、用户/课程画像 |
| `profile.snapshot` | Profile 页面读取 | 否 | mastery overview、course profile、user profile |
| `profile.study_plan` | 获取学习建议 | 否 | review/practice/reflect 三步计划 |

## 核心表

`UserKnowledgeState`：

```text
user_id
course_id
knowledge_unit_id
mastery_score
confidence_score
stability_score
forgetting_due_at
review_priority
total_attempts
correct_attempts
last_attempt_at
review_status
scheduled_review_at
review_interval_days
review_ease_factor
review_repetition_count
review_reason
source_exam_paper_id
state_version
last_recomputed_at
stats_json
updated_at
```

字段定位：

| 字段 | 含义 |
| --- | --- |
| `mastery_score` | 当前知识点掌握度，0 到 1 |
| `confidence_score` | 统计置信度，主要由尝试次数决定 |
| `stability_score` | 稳定度，主要由连续正确表现决定 |
| `forgetting_due_at` | 预计需要复习的时间 |
| `review_priority` | 复习优先级 |
| `stats_json` | 题型、难度、错因、用时、提示、自评等统计 |

## 总数据流

```text
1. Examine 生成题目
   输出: QuestionKnowledgeUnitLink(knowledge_unit_id, coverage_weight)

2. 用户答题并批改
   输出: ExamPaperItem(is_correct, difficulty, question_type, time_spent...)

3. profile.update
   输入: exam_paper_id
   输出: UserKnowledgeState + profile_json

4. profile.snapshot
   输入: course_id, user_id
   输出: 页面展示用 mastery overview

5. profile.study_plan
   输入: course_profile, user_profile
   输出: 今日/下一步学习动作

6. DocGen
   输入: user.profile_json + course.profile_json
   输出: learner_profile_text，作为生成文档的个性化上下文
```

## 与 Digest 的关系

Profile 不规划文档结构，那是 `digest/planner`。

Profile 不生成知识文档，那是 `digest/docgen`。

Profile 不抽知识图谱，那是 `digest/kg_doc_sync`。

Profile 的输出会被 DocGen 读取：

```text
user.profile_json
course.profile_json
  -> load_docgen_learner_profile_context
  -> learner_profile_text
  -> user_profile.prompt_addendum
```

## 修改检查

- 改掌握度计算时同步 `update/README.md`。
- 改 API 返回字段时同步 `schemas/profile.py` 和前端页面。
- 改画像字段时同步 DocGen `learner_profile.py`。
- `snapshot` 和 `study_plan` 默认不写库。
