# 08. Profile 引擎

## 1. 目标与职责

Profile 负责把学习过程沉淀成可持续利用的学习状态。它不只是分析页，而是整套教学系统的状态层，主要回答：

- 用户现在会什么、不会什么
- 哪些单元需要复习
- 哪些薄弱点会影响后续学习顺序
- 哪些状态应该送回 Interact 和 Examine

---

## 2. 当前实现落点

当前 Profile 的对外资源组已经收口到 `profile`，底层主线是 workflow-backed 的学习状态层。

### 2.1 当前正式路径

- 前端页面：`frontend/src/pages/AnalysisPage.tsx`
- 后端资源组：`profile`
- 业务入口：`backend/app/services/profile_service.py`
- 工作流编排：`backend/app/workflows/profile/*`
- 关键模型：
  - `user_knowledge_state`
  - `review_task`
  - `user_answer_attempt`
  - `exam_paper`、`exam_paper_item`

补充说明：

- 旧 `user_profile / mistake` 不是主设计
- `assessment` 不再是正式资源组名称

---

## 3. 当前主 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 判卷完成 | `workflows/examine/exam_grade_workflow.py` | 已判卷试卷 | 进入状态回流 |
| 2. 掌握度更新 | `workflows/profile/mastery_updater.py` | `exam_paper_item`、`user_answer_attempt` | `user_knowledge_state` |
| 3. 复习调度 | `workflows/profile/review_scheduler.py` | 更新后的状态 | `review_task` |
| 4. 薄弱分析 | `workflows/profile/weakness_analyzer.py` | 掌握度、答题记录、课程结构 | 薄弱排序结果 |
| 5. profile 查询 | `profile_service` | `subject`、用户 | mastery overview、review tasks、报告读模型 |

---

## 4. 核心设计原则

### 4.1 Profile 是状态层，不是报表层

Profile 的核心价值不在于“画了几张图”，而在于它能否被其他引擎直接消费。

### 4.2 状态要尽量锚定稳定对象

新链路优先锚定：

- `teaching_unit_id`
- `knowledge_node_id`
- `curriculum_version`

这比只依赖 `knowledge_point` 字符串更稳定。

### 4.3 学习状态应该同时有强度、时间性和任务性

当前新链路已经开始把状态拆成：

- 掌握度
- 置信度
- 稳定性
- 遗忘到期时间
- 待复习任务

这比旧的单一正确率画像更适合教学闭环。

### 4.4 状态必须接回其他引擎

Profile 的输出至少要能回到：

- Interact：弱项、复习上下文、错题复盘
- Examine：组卷优先级、薄弱点命中、复习任务驱动的测评

---

## 5. 数据库写入对象

直接写入：

- `user_knowledge_state`
- `review_task`

并消费：

- `user_answer_attempt`
- `exam_paper`
- `exam_paper_item`
- `curriculum_version`

---

## 6. 本地落盘对象

当前 Profile 以数据库为主，没有强依赖的正式本地业务文件。

如需补调试摘要，统一写入：

- `data/<subject>/debug/profile.mastery/<run_or_job_id>/`
- `data/<subject>/debug/profile.review/<run_or_job_id>/`
- `data/<subject>/debug/profile.weakness/<run_or_job_id>/`

建议只保存：

- 状态聚合摘要
- 薄弱排序结果
- 复习任务变更摘要

---

## 7. 关键状态推进

新的状态对象包括：

- `user_knowledge_state`
  - mastery score
  - confidence score
  - stability score
  - repetition count
  - forgetting due
- `review_task`
  - pending
  - completed
  - expired

这让“画像”从静态概览变成了可以驱动复习和出题的可执行状态层。

---

## 8. 节点到表责任

| 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `mastery_updater.py` | `exam_paper`、`exam_paper_item`、`user_answer_attempt`、已有 `user_knowledge_state` | `user_knowledge_state` | 无 |
| `review_scheduler.py` | `user_knowledge_state`、已有 `review_task` | `review_task`、状态相关字段 | 无 |
| `weakness_analyzer.py` | `user_knowledge_state`、`user_answer_attempt`、`curriculum_version`、课程结构对象 | 无 | 无 |
| `profile_service` | `user_knowledge_state`、`review_task`、`user_answer_attempt`、`exam_paper_item` | 无 | 无 |

---

## 9. 开发关注点

### 9.1 不能再把 UserProfile 当成画像真相源

新的学习状态真相源应该围绕 `user_knowledge_state / review_task / user_answer_attempt` 组织。

### 9.2 新状态层是 Interact 和 Examine 的共同输入

`user_knowledge_state` 和 `review_task` 的价值，不只是分析页展示，而是驱动下一轮对话与测评。

### 9.3 当前代码里仍有弱多态目标字段

当前 `user_knowledge_state` 和 `review_task` 仍使用 `granularity + target_id` 过渡表达；目标态应进一步收口到 `teaching_unit_id / knowledge_node_id` 强外键模型。

---

## 10. 总结

Profile 当前已经明确收口到学习状态层：`user_knowledge_state` 负责掌握度真相，`review_task` 负责复习调度，`user_answer_attempt` 负责行为回放。后续开发应继续强化这条主线，不再回到 `user_profile / mistake` 模型。
