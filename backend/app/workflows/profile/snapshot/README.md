# Profile Snapshot 链路

最后更新：2026-06-15

`profile/snapshot/` 是 Profile 页面读取用的只读链路。

```text
输入: course_id + user_id
输出: mastery overview + course_profile + user_profile
```

## 主流程

```text
validate_snapshot_context
  -> load_mastery_overview
  -> build_course_profile
  -> build_user_profile
```

## 1. `validate_snapshot_context`

输入：

```text
course_id
user_id
top_n
```

动作：

```text
校验 course_id/user_id。
```

输出：

```text
course_id
user_id
top_n
error
```

## 2. `load_mastery_overview`

输入：

```text
course_id
user_id
top_n
```

动作：

```text
读取当前课程下的 UserKnowledgeState。
按掌握度和复习优先级整理知识点状态。
```

输出：

```text
knowledge_unit_states
weak_knowledge_unit_count
```

`knowledge_unit_states[]`：

```text
id
knowledge_unit_id
knowledge_unit_name
knowledge_unit_type
mastery_score
confidence_score
stability_score
forgetting_due_at
review_priority
total_attempts
correct_attempts
last_attempt_at
state_version
updated_at
```

## 3. `build_course_profile`

输入：

```text
course_id
user_id
UserKnowledgeState
recent exam items
pending reviews
```

动作：

```text
现场构建课程画像。
不写 course.profile_json。
```

输出：

```text
course_profile
```

## 4. `build_user_profile`

输入：

```text
user_id
active courses
recent exams
pending reviews
```

动作：

```text
现场构建用户画像。
不写 user.profile_json。
```

输出：

```text
user_profile
```

## API 返回

```text
MasteryOverviewResponse:
  course_id
  user_id
  weak_knowledge_unit_count
  knowledge_unit_states
  course_profile
  user_profile
```

## 边界

```text
只读。
不更新 mastery。
不安排复习。
不写 profile_json。
不生成 study plan。
```

## 修改检查

- 新增页面字段要同步 `schemas/profile.py`。
- 不能在 snapshot 中写库。
- 若要持久化画像，应放到 `profile.update`。
