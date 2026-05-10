# Profile Study Plan 链路说明

最后更新：2026-05-11

`profile/study_plan/` 是 Profile 的主动学习计划 lane。

这个目录不用 `planning/` 命名，原因是避免和 `digest/planner` 混淆：

- `digest/planner`：面向资料和知识文档，规划“学什么、怎么组织内容”。
- `profile/study_plan`：面向用户画像和当前掌握度，规划“今天/本周怎么执行学习动作”。

## 主线

```text
load_profile_context
  -> build_study_plan
```

公开入口：

```python
from app.workflows.profile import run_profile_study_plan_workflow
```

## 当前能力

当前是轻量确定性计划：

- 先处理高优先级复习。
- 再按课程画像推荐题型、题量、难度做定向练习。
- 最后按用户讲解偏好进入伴读复盘。

## 边界

- 不写 DB。
- 不调用 LLM。
- 不生成 Digest confirmed plan。
- 不替代 Examine 出题；只给出下一步练习建议。

## LangSmith

root trace：`profile.study_plan`

metadata 里会带：

- `lane=study_plan`
- `profile_trigger=profile_study_plan`
- `course_id`
- `user_id`
