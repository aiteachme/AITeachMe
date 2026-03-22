# 08. Profile 引擎

## 1. 目标与职责

Profile 负责把学习过程沉淀成可持续利用的学习状态。它不只是分析页，而是整套教学系统的状态层，主要回答：

- 用户现在会什么、不会什么
- 哪些单元需要复习
- 哪些薄弱点会影响后续学习顺序
- 哪些状态应该送回 Interact 和 Examine

---

## 2. 当前实现落点

当前 Profile 同样处于双轨期。

### 2.1 legacy 路径

- 前端页面：`frontend/src/pages/AnalysisPage.tsx`
- 后端资源组：`profile`
- 业务入口：`backend/app/services/profile_service.py`
- 关键模型：`user_profile`、`mistake`

### 2.2 workflow-backed 新路径

- 后端资源组：`assessment`
- 业务入口：`backend/app/services/assessment_service.py`
- 工作流编排：`backend/app/workflows/profile/*`
- 关键模型：
  - `user_knowledge_state`
  - `review_task`
  - 以及由 Examine 触发的 `user_answer_attempt`

---

## 3. 当前主 Pipeline

### 3.1 legacy 画像链路

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 测评结果回流 | legacy `exams_service` | 判卷结果 | 知识点级统计 |
| 2. 画像更新 | `profile_repo.upsert_profile` | knowledge point、attempt/correct | `user_profile` |
| 3. 薄弱点查询 | `profile_service` | `subject` | 薄弱点列表、学习报告 |
| 4. 错题本查询 | `profile_service.list_mistakes` | `subject` | `mistake` 列表 |

### 3.2 workflow-backed 新状态链路

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 判卷完成 | `workflows/examine/exam_grade_workflow.py` | 已判卷试卷 | 进入状态回流 |
| 2. 掌握度更新 | `workflows/profile/mastery_updater.py` | `exam_paper_item`、`user_answer_attempt` | `user_knowledge_state` |
| 3. 复习调度 | `workflows/profile/review_scheduler.py` | 更新后的状态 | `review_task` |
| 4. 薄弱分析 | `workflows/profile/weakness_analyzer.py` | 掌握度、答题记录、课程结构 | 薄弱排序结果 |
| 5. assessment 查询 | `assessment_service` | `subject`、用户 | mastery overview、review tasks |

---

## 4. 核心设计原则

### 4.1 Profile 是状态层，不是报表层

Profile 的核心价值不在于“画了几张图”，而在于它能否被其他引擎直接消费。

### 4.2 状态要尽量锚定稳定对象

新链路优先锚定：

- `teaching_unit_id`
- 知识节点链接
- `curriculum_snapshot`

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

### 5.1 legacy 链路

直接写入：

- `user_profile`
- `mistake`

### 5.2 workflow-backed 新链路

直接写入：

- `user_knowledge_state`
- `review_task`

并消费：

- `user_answer_attempt`
- `exam_paper`
- `exam_paper_item`
- `curriculum_snapshot`

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

### 7.1 legacy 路径

主要依赖：

- `user_profile.mastery`
- `mistake`

来表达学习状态和错题积累。

### 7.2 workflow-backed 新路径

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
| `weakness_analyzer.py` | `user_knowledge_state`、`user_answer_attempt`、`curriculum_snapshot`、课程结构对象 | 无 | 无 |
| legacy `profile_service` 链路 | `user_profile`、`mistake` | `user_profile` | 无 |

---

## 9. 开发关注点

### 9.1 不能再把 UserProfile 当成唯一画像对象

`user_profile` 仍在线，但已经不是系统唯一、也不是长期最值得强化的学习状态层。

### 9.2 新状态层是 Interact 和 Examine 的共同输入

`user_knowledge_state` 和 `review_task` 的价值，不只是分析页展示，而是驱动下一轮对话与测评。

### 9.3 文档必须明确双轨现状

任何设计文档如果继续只讲 `UserProfile + Mistake`，都会和当前数据库与 workflow 真相失配。

---

## 10. 总结

Profile 当前已经从“掌握度统计页”演进成双轨状态层：

- legacy 链路继续服务现有 `profile` API
- workflow-backed 新链路已经落到 `user_knowledge_state` 与 `review_task`

后续开发应优先强化新链路，同时继续在文档中准确说明两套状态对象各自的责任、读写边界和消费方，避免前端、后端和设计文档再出现状态模型漂移。
