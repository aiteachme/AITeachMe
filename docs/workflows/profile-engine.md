# 08. Profile 显影引擎

最后更新：2026-05-11

本文是 Profile 的跨模块事实页。目录结构和入口以 `backend/app/workflows/profile/README.md` 为准。

## 当前职责

Profile 负责把学习行为转成可查询的掌握度、薄弱点、复习任务和课程画像摘要。

当前真相表：

- `user_knowledge_state`

它不负责：

- 出题和判卷。
- 生成知识文档。
- 维护旧 `user_profile` / `mistake` 表语义。

## 代码入口

| 职责 | 文件 |
| --- | --- |
| API | `backend/app/api/profile.py` |
| 稳定导入面 | `backend/app/workflows/profile/__init__.py` |
| 画像更新链路 | `backend/app/workflows/profile/update/` |
| 画像快照链路 | `backend/app/workflows/profile/snapshot/` |
| 主动学习计划链路 | `backend/app/workflows/profile/study_plan/` |
| 共享节点与 helper | `backend/app/workflows/profile/common/` |
| 数据访问 | `backend/app/repositories/profile_repo.py` |
| Exam 触发点 | `backend/app/api/exams.py` |

运行入口：

```python
from app.workflows.profile import (
    run_profile_update_workflow,
    run_profile_snapshot_workflow,
    run_profile_study_plan_workflow,
)
```

底层 helper 仍保留给节点和少量兼容调用，但不应作为主流程入口：

```python
from app.workflows.profile import (
    update_mastery_from_exam,
    schedule_reviews,
    build_course_profile_summary,
    build_user_profile_summary,
)
```

## 当前链路

### 判卷后持久化链路

LangSmith root：`profile.update`

```text
graded exam
  -> run_profile_update_workflow
  -> resolve_profile_context
  -> update_mastery
  -> schedule_reviews
  -> analyze_weakness
  -> refresh_course_profile
  -> refresh_user_profile
```

掌握度、最近表现、薄弱原因、复习计划等结果落在 `user_knowledge_state` 或由其派生。

### Profile 页只读快照链路

LangSmith root：`profile.snapshot`

```text
GET /api/v1/courses/{course}/profile/mastery
  -> run_profile_snapshot_workflow
  -> validate_snapshot_context
  -> load_mastery_overview
  -> build_course_profile
  -> build_user_profile
```

这条链路不写 DB，只把掌握度列表、课程画像、用户画像和对话信号组织成 API 返回结果。

### 主动学习计划链路

LangSmith root：`profile.study_plan`

```text
profile study-plan request
  -> run_profile_study_plan_workflow
  -> load_profile_context
  -> build_study_plan
```

这条链路基于画像生成“复习、练习、伴读复盘”的执行建议，不写 DB，不替代 `digest/planner`。

## LangSmith 调试口径

Profile 现在不应该再由 API 层手写串联 helper 作为主流程。只要触发 Profile 链路，都应通过 `run_state_graph(...)` 形成一条 root trace：

- `profile.update`：判卷后更新画像，metadata 带 `profile_trigger=exam_graded`、`exam_paper_id`、`course_id`、`user_id`。
- `profile.snapshot`：Profile 页只读快照，metadata 带 `profile_trigger=profile_mastery_overview`、`course_id`、`user_id`。
- `profile.study_plan`：主动学习计划，metadata 带 `profile_trigger=profile_study_plan`、`course_id`、`user_id`。
- 每个节点 span 都带 `node_key`、`node_description`、`reads`、`writes`、`emits`、`state_inputs`、`state_outputs`。
- 每个节点输出 `*_ms`，root 输出 `workflow_elapsed_ms`，排障优先看这些 timing 字段和 `state.error`。

## 当前主动增强

Profile 页已提供一版轻量“今日学习计划”：

- 根据到期复习任务、薄弱知识点、推荐练习模式、推荐题型和难度生成 3 步执行建议。
- 后端对应链路为 `profile/study_plan`；计划只消费现有画像结果，不替代 Digest Planner 的 confirmed plan。
- 练习入口仍回到 Examine，复盘入口仍回到知识库/伴读链路。

Profile 也会从已有聊天记录中派生轻量对话信号：

- 统计近期主动提问数量、划选内容追问次数。
- 用简单关键词识别用户更偏好“推导步骤、练习安排、重点总结、概念解释”等讲解方式。
- 当前不新增长期记忆表，不调用 LLM 总结聊天，不在聊天链路中隐式改写掌握度。

## API 形态

当前 `/api/v1/courses/{course}/profile` 提供：

- 掌握度概览。
- 待复习任务。
- 完成复习任务。

## 约束

- Profile 以 `knowledge_unit` 为粒度，不依赖未落地的 `teaching_unit`。
- 画像更新应通过明确入口触发，不在聊天链路中隐式写入。
- Interact 可以读取 Profile 摘要辅助教学，但不直接修改画像。
- 未来如引入 BKT/遗忘模型，应扩展 `user_knowledge_state` 或新增明确迁移，不复活旧表。
