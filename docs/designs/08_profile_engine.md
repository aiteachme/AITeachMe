# 08. Profile 显影引擎

最后更新：2026-04-27

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
| 当前唯一链路 | `backend/app/workflows/profile/pipeline/` |
| 数据访问 | `backend/app/repositories/profile_repo.py` |
| Exam 触发点 | `backend/app/api/exams.py` |

常用入口：

```python
from app.workflows.profile import (
    update_mastery_from_exam,
    schedule_reviews,
    build_course_profile_summary,
    build_user_profile_summary,
)
```

## 主流程

```text
graded exam
  -> update_mastery_from_exam
  -> schedule_reviews
  -> build_course_profile_summary / build_user_profile_summary
```

掌握度、最近表现、薄弱原因、复习计划等结果落在 `user_knowledge_state` 或由其派生。

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
