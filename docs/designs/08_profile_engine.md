# 08. Profile 引擎

## 1. 文档定位

Profile 负责把学习过程沉淀成可被其他引擎直接消费的状态层。

它当前回答三类问题：

- 这个用户在这门课里哪些地方已经掌握、哪些地方薄弱
- 这门课当前更适合用什么方式继续练、继续测
- 这个用户跨学科更稳定的学习偏好是什么

本篇只描述当前代码已经落地的实现，不再把目标态和现状混写。

---

## 2. 当前已落地范围

### 2.1 已经真正闭环的主线

当前已经跑通的 Profile 主线是：

1. 判卷完成，回写 `exam_paper` / `exam_paper_item`
2. `workflows/profile/mastery_updater.py` 基于答题结果更新 `user_knowledge_state`
3. `workflows/profile/review_scheduler.py` 基于掌握度和复习状态安排复习任务
4. 同一轮判卷事务里刷新 `subject.profile_json`
5. 同一轮判卷事务里刷新 `user.profile_json`
6. `/api/v1/subjects/{subject}/profile/mastery` 返回细粒度状态 + 学科级画像 + 用户级画像

也就是说，当前 Profile 已经不是只剩 `user_knowledge_state` 一层，而是先用 `user_knowledge_state` 做真相源，再向上聚合出 subject-level 和 user-level 摘要层。

### 2.2 当前正式入口

- 前端页面：`frontend/src/pages/ProfilePage.tsx`
- 后端资源组：`profile`
- API：
  - `GET /api/v1/subjects/{subject}/profile/mastery`
  - `GET /api/v1/subjects/{subject}/profile/mastery/unit/{teaching_unit_id}`
  - `GET /api/v1/subjects/{subject}/profile/mastery/node/{knowledge_node_id}`
  - `GET /api/v1/subjects/{subject}/profile/review/tasks`
  - `POST /api/v1/subjects/{subject}/profile/review/tasks/{task_id}/complete`
- 业务入口：`backend/app/services/profile_service.py`
- 工作流：`backend/app/workflows/profile/*`

当前没有额外新增 `profile/summary` 之类的接口，摘要层继续并入现有 `mastery` 读模型返回，保持 API 面简单。

---

## 3. 三层 Profile 结构

### 3.1 L1 用户级画像：`user.profile_json`

这是跨学科的轻量画像摘要，当前用于表达更稳定的学习偏好，不承载细粒度知识状态。

当前实现中主要包括：

- `preferred_question_types`
- `preferred_exam_modes`
- `dominant_exam_mode`
- `explanation_style`
- `pace_preference`
- `consistency_level`
- `pending_review_count`
- `due_review_count`
- `notes`

这层当前是自动聚合摘要，不是完整的“用户设置中心”。

运行时补充（2026-04）：

- 用户级 profile 之外，系统还会维护一份 `backend/data/users/<user_id>/LEARNER.md`
- `LEARNER.md` 不作为数据库主表，而是作为人类可读、可手工编辑的运行时画像补充
- 当前对话上下文会自动把 `LEARNER.md` 一起注入，不再只依赖 memory store 聚合出的 `UserProfile`

模式语义补充（2026-04）：

- 用户级画像里的考试形态已归一到两类：`web_practice`（测验）和 `paper_exam`（考试卷）
- 历史值 `diagnostic/practice/weakpoint_boost/review/mock_final/real_exam` 在聚合时会自动归一，不再作为目标态推荐值

### 3.2 L2 学科级画像：`subject.profile_json`

这是 owner-scoped 的 `user + subject` 学科画像摘要，用来表达“这门课下一步更适合怎么练、怎么考”。

当前实现中主要包括：

- `avg_unit_mastery`
- `avg_node_mastery`
- `weak_unit_count`
- `weak_node_count`
- `pending_review_count`
- `due_review_count`
- `preferred_question_types`
- `recommended_question_types`
- `recommended_exam_mode`
- `recommended_question_count`
- `difficulty_focus`
- `focus_teaching_unit_ids`
- `focus_node_ids`
- `question_type_accuracy`
- `difficulty_accuracy`
- `notes`

模式语义补充（2026-04）：

- `recommended_exam_mode` 目标态只输出 `web_practice` 或 `paper_exam`
- 当掌握度较稳、薄弱点较少时会更倾向推荐 `paper_exam`；否则优先推荐 `web_practice`

### 3.3 L3 细粒度状态：`user_knowledge_state`

这是当前最底层、也最稳定的真相源，直接绑定：

- `teaching_unit_id`
- `knowledge_node_id`

并保存：

- `mastery_score`
- `confidence_score`
- `stability_score`
- `forgetting_due_at`
- `review_*` 复习调度字段
- `stats_json` 行为统计摘要

当前所有上层画像都以这层状态和最近答题快照为基础聚合出来。

---

## 4. 当前主 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 判卷完成 | `workflows/examine/answer_grader.py` | `exam_paper_item.answer_content` + 知识上下文 | `exam_paper_item.is_correct / feedback / error_cause` |
| 2. 掌握度更新 | `workflows/profile/mastery_updater.py` | 判卷后的 `exam_paper_item` | `user_knowledge_state` |
| 3. 复习调度 | `workflows/profile/review_scheduler.py` | 更新后的 state | pending review 状态 |
| 4. 学科画像聚合 | `workflows/profile/subject_profile.py` | state + 最近答题快照 | `subject.profile_json` |
| 5. 用户画像聚合 | `workflows/profile/user_profile.py` | 各学科摘要 + 最近答题快照 | `user.profile_json` |
| 6. 画像读取 | `profile_service` | 当前学科 state + 两层摘要 | `/profile/mastery` 返回值 |

补充说明：

- `complete_review_task()` 也会在同一轮服务事务里刷新 `subject.profile_json` 与 `user.profile_json`。
- 当前不单独起持久化 job 表，仍优先用现有服务入口 + workflow 组织。

---

## 5. 画像如何影响其他引擎

### 5.1 对 Examine 的影响

当前 `build_exam_style_profile()` 已经会综合：

- 样卷 markdown
- `style_prompt` / `focus_prompt` / `user_prompt`
- `subject.profile_json`
- `user.profile_json`

并产出 `ExamStyleProfile`，其中当前已会影响：

- `preferred_question_types`
- `recommended_question_count`
- `difficulty_focus`
- `focus_teaching_unit_ids`
- `notes`

`question_builder.py` 的确定性回退模板也会读取 `difficulty_focus`，因此即使 LLM 回退，Profile 对出题仍然有效。

另外，`exams/generate.difficulty` 现在支持显式覆盖：

- 传 `easy / medium / hard / mixed` 时，优先覆盖 profile 自动推断
- 不传时，继续使用 `subject.profile_json.difficulty_focus`

### 5.2 对 Interact 的影响

当前 Interact 主链路现在会消费：

- 薄弱点摘要
- 近期错题摘要
- 掌握度状态
- `UserProfile` 聚合摘要
- `LEARNER.md` 运行时档案

所以当前 Interact 已经不再只是“读数据库画像摘要”，而是会把 runtime learner markdown 一起带进 prompt；但更深层的策略节点联动仍有继续增强空间。

### 5.3 对 Digest 的影响

当前 Digest 侧主要还停留在“可读取这些摘要层”的设计空间，尚未像 Examine 一样形成明确消费逻辑。

因此目前 Profile 和其他引擎的最强闭环，优先还是 Examine。

---

## 6. 数据与字段约定

### 6.1 `user.profile_json`

当前把它当成轻量聚合缓存，而不是强 schema 的大对象中心。

约定：

- 只放跨学科稳定摘要
- 不放 unit/node 级细粒度状态
- 不承担历史版本职责

### 6.2 `subject.profile_json`

当前把它当成学科内的学习/出题先验缓存。

约定：

- 以当前用户在该学科下的状态为准
- `focus_teaching_unit_ids / focus_node_ids` 只引用当前稳定主对象
- 不额外拆 history/version 表

### 6.3 `user_knowledge_state.stats_json`

当前用于承载轻量行为统计摘要，主要包括：

- `question_type_counts`
- `difficulty_counts`
- `error_cause_counts`
- `hint_used_count`
- `avg_time_spent_seconds`
- `avg_confidence_self_report`
- `last_question_type`
- `last_difficulty`
- `last_error_cause_label`

注意：

- 它当前是行为摘要字段，不是新的真相源表
- 是否写入这些统计，取决于答题链路是否采集到了对应字段

---

## 7. 当前边界

### 7.1 画像层依然是“当前态优先”

当前三层 Profile 都优先服务当前学习闭环，不为历史版本追溯过度设计。

### 7.2 用户级画像还是轻量层

`user.profile_json` 目前更接近“学习偏好摘要”，不是完整的个人设置页、也不是长期记忆仓库。

补充：

- `LEARNER.md` 是用户级画像的运行时伴生文档，不替代 `user.profile_json`
- 当前建议语义是：`user.profile_json` 负责稳定聚合摘要，`LEARNER.md` 负责人类可读补充与长期教学备注

### 7.3 学科级画像不是全局公共学科画像

`subject.profile_json` 当前是 owner-scoped 的学习画像，语义上仍然依赖当前用户的作答和复习记录。

### 7.4 行为字段仍是渐进增强

`exam_paper_item.time_spent_seconds / hint_used / confidence_self_report` 已有字段位，但只有在前端或调用链实际采集时，才会继续影响 `stats_json` 与上层画像。

---

## 8. 总结

当前 Profile 已经明确收口到三层：

- `user.profile_json` 负责跨学科轻量用户画像
- `subject.profile_json` 负责学科级学习/出题先验
- `user_knowledge_state` 负责细粒度掌握状态

真正的真相源仍然是 `user_knowledge_state + exam_paper_item`，而 `user.profile_json / subject.profile_json` 是建立在这条主线上的聚合摘要层。当前最完整的闭环已经是：

`做题 -> 判卷 -> state 更新 -> review 调度 -> subject/user profile 刷新 -> 再影响下一轮出题`

同时当前还多了一条 runtime 档案侧链：

`做题 -> learning log / LEARNER.md 补写 -> Interact 上下文自动读入`
## 0. 2026-04 Profile 闭环修正

- 本批没有新增 schema，也没有新增 profile summary 主表，仍保持 `user.profile_json / subject.profile_json / user_knowledge_state` 三层结构。
- `update_mastery_from_exam()` 的核心收益来自更精确的 `exam_paper_item.node_refs_json`：node mastery 现在只会由真正命中的节点回写，不再把同单元其它 membership 节点一起拉动。
- unit mastery 仍按 `exam_paper_item.teaching_unit_id` 聚合，node mastery 按精确 `node_refs_json` 聚合；这一点是 Examine/Profile 闭环信号纯度的关键约束。
- `subject.profile_json.focus_teaching_unit_ids / focus_node_ids` 仍继续作为 Examine 的出题先验，但本批没有改动对外 API，也没有新增额外画像读取接口。
