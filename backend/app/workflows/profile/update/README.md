# Profile Update 链路说明

最后更新：2026-05-11

`profile/update/` 是判卷后触发的画像持久化 lane。

## 主线

```text
resolve_profile_context
  -> update_mastery
  -> schedule_reviews
  -> analyze_weakness
  -> refresh_course_profile
  -> refresh_user_profile
```

公开入口：

```python
from app.workflows.profile import run_profile_update_workflow
```

## 边界

- 会写 `user_knowledge_state`、复习字段、`course.profile_json`、`user.profile_json`。
- 不负责 Profile 页只读聚合；那是 `profile/snapshot`。
- 不负责主动学习计划；那是 `profile/study_plan`。
- API 层不要直接串 `update_mastery_from_exam(...) + schedule_reviews(...)` 绕过本 lane。

## LangSmith

root trace：`profile.update`

metadata 里会带：

- `lane=update`
- `profile_trigger=exam_graded`
- `exam_paper_id`
- `course_id`
- `user_id`
