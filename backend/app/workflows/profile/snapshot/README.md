# Profile Snapshot 链路说明

最后更新：2026-05-11

`profile/snapshot/` 是 Profile 页面读取时触发的只读 lane。

## 主线

```text
validate_snapshot_context
  -> load_mastery_overview
  -> build_course_profile
  -> build_user_profile
```

公开入口：

```python
from app.workflows.profile import run_profile_snapshot_workflow
```

## 边界

- 只组装 API 返回数据，不写 DB。
- 不更新掌握度、不安排复习；那是 `profile/update`。
- 不直接生成主动学习计划；那是 `profile/study_plan`。

## LangSmith

root trace：`profile.snapshot`

metadata 里会带：

- `lane=snapshot`
- `profile_trigger=profile_mastery_overview`
- `course_id`
- `user_id`
