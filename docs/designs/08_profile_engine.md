TODO 加个学习人格！mbti
TODO 当然除了加点花哨的内容，还是要有具体有用的内容？比如profile里会有好几个字段，然后学习状态表会有对知识点的理解的介绍，然后要有本地存的文件类似USER.md这种

TODO 这里结合上记忆曲线？具体记忆曲线也展示一下什么的
TODO 还能结合上什么？结合上BKT？一些数学理论啥的？


# 08. Profile 引擎

## 1. 目标与职责

Profile 负责把学习过程沉淀成可持续利用的画像和学习状态。它不只是分析页，而是整套教学系统的状态层，主要回答：

- 这个用户整体是什么样的学习者
- 这个用户在当前学科下是什么状态
- 用户现在会什么、不会什么
- 哪些薄弱点会影响后续学习顺序
- 哪些状态应该送回 Interact、Digest 和 Examine

---

## 2. 当前实现落点

当前 Profile 的对外资源组已经收口到 `profile`，目标主线是 workflow-backed 的三层 profile 体系。

### 2.1 当前正式路径


TODO 这里文档层面是不是还有好多要重构的。。。。

- 前端页面：`frontend/src/pages/ProfilePage.tsx`
- 后端资源组：`profile`
- 业务入口：`backend/app/services/profile_service.py`
- 工作流编排：`backend/app/workflows/profile/*`
- 关键模型：
  - `user.profile_json`
  - `subject.profile_json`
  - `user_knowledge_state`
  - `exam_paper`
  - `exam_paper_item`

补充说明：

- 旧 `user_profile / mistake` 不是主设计
- `assessment` 不再是正式资源组名称
- 当前代码已重点落到 `user_knowledge_state`
- 用户级和学科级 profile JSON 是这轮文档明确补齐的目标层

---

## 3. 当前主 Pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 判卷完成 | `workflows/examine/exam_grade_workflow.py` | 已判卷试卷 | 进入状态回流 |
| 2. 掌握度更新 | `workflows/profile/mastery_updater.py` | `exam_paper_item` | `user_knowledge_state` |
| 3. 学科级画像聚合 | `profile_service / 后续 profile 聚合模块` | 学习状态、答题快照、学科上下文 | `subject.profile_json` |
| 4. 用户级画像归并 | `profile_service` 或后续 workflow | 学科画像、长期偏好、显式设置 | `user.profile_json` |
| 5. profile 查询 | `profile_service` | `subject`、用户 | mastery overview、subject profile、user profile |

---

## 4. 核心设计原则

### 4.1 Profile 是状态层，不是报表层

Profile 的核心价值不在于“画了几张图”，而在于它能否被其他引擎直接消费。

### 4.2 Profile 不是一张表，而是三层结构

目标态的 Profile 应分三层：

- 用户级长期画像：`user.profile_json`
- 学科级学习画像：`subject.profile_json`
- 细粒度学习状态：`user_knowledge_state`

这三层分别回答：

- 这个人整体是什么样的学习者
- 他在这门学科里当前应该怎么教、怎么考
- 他在具体知识点和教学单元上到底掌握到什么程度


TODO 上面这几点正是我想说的

### 4.3 状态要尽量锚定稳定对象

新链路优先锚定：

- `teaching_unit_id`
- `knowledge_node_id`
- `curriculum`

这比只依赖 `knowledge_point` 字符串更稳定。

### 4.4 学科级画像要服务生成，不只是展示

`subject.profile_json` 不应该只是分析页的一段说明，它至少要能给：

- `Digest`：教学模式、压缩偏好、讲解风格
- `Interact`：讲解策略、举例密度、对话语气
- `Examine`：题型偏好、难度权重、考试目标

### 4.5 学习状态应该同时有强度、时间性和复习性

当前新链路已经开始把状态拆成：

- 掌握度
- 置信度
- 稳定性
- 遗忘到期时间
- 待复习状态

这比旧的单一正确率画像更适合教学闭环。

### 4.6 状态必须接回其他引擎

Profile 的输出至少要能回到：

- Interact：弱项、复习上下文、错题复盘
- Digest：难点密度、压缩偏好、教材风格偏好
- Examine：组卷优先级、薄弱点命中、复习驱动的测评

---

## 5. 数据库写入对象

直接写入：

- `user.profile_json`
- `subject.profile_json`
- `user_knowledge_state`

并消费：

- `exam_paper`
- `exam_paper_item`
- `curriculum`

说明：

- 复习调度字段并回 `user_knowledge_state`
- 行为回放由 `exam_paper_item` 承载，不再额外拆 `user_answer_attempt`

---

## 6. 本地落盘对象

当前 Profile 以数据库为主，没有强依赖的正式本地业务文件。

如需补调试摘要，统一写入：

- `data/<subject>/debug/profile.mastery/<run_or_job_id>/`
- `data/<subject>/debug/profile.subject/<run_or_job_id>/`
- `data/<subject>/debug/profile.user/<run_or_job_id>/`
- `data/<subject>/debug/profile.weakness/<run_or_job_id>/`

建议只保存：

- 状态聚合摘要
- 薄弱排序结果
- 学科画像变更摘要
- 用户画像变更摘要

---

## 7. 关键状态推进

新的 profile 对象包括：

- `user.profile_json`
  - 跨学科偏好
  - 长期 memory
  - 交互风格
  - 可选 MBTI / 学习风格标签
- `subject.profile_json`
  - 学科目标
  - 题型偏好
  - 当前弱项摘要
  - digest / interact / examine 共用先验
- `user_knowledge_state`
  - mastery score
  - confidence score
  - stability score
  - repetition count
  - forgetting due

这让“画像”从静态概览变成了可以驱动复习和出题的可执行状态层。

---

## 8. 节点到表责任

| 模块 | 读 DB | 写 DB | 写 FS |
| --- | --- | --- | --- |
| `mastery_updater.py` | `exam_paper`、`exam_paper_item`、已有 `user_knowledge_state` | `user_knowledge_state` | 无 |
| `profile_service / 后续 profile 聚合模块` | `user_knowledge_state`、`exam_paper_item`、`subject` | `subject.profile_json` | 无 |
| `weakness_analyzer.py` | `user_knowledge_state`、`exam_paper_item`、`curriculum`、课程结构对象 | 无 | 无 |
| `profile_service` | `user`、`subject`、`user_knowledge_state`、`exam_paper_item` | `user.profile_json`（显式设置场景） | 无 |

---

## 9. 开发关注点

### 9.1 不能再把旧 `user_profile` 当成画像真相源

新的 profile 真相源应该围绕 `user.profile_json / subject.profile_json / user_knowledge_state / exam_paper_item` 组织。

### 9.2 三层 profile 是 Interact、Digest 和 Examine 的共同输入

- `user.profile_json` 提供全局学习者画像
- `subject.profile_json` 提供学科内教学与组卷先验
- `user_knowledge_state` 提供细粒度掌握状态

### 9.3 当前代码已切到显式目标外键

当前 `user_knowledge_state` 已显式使用 `teaching_unit_id / knowledge_node_id` 强外键表达目标。后续重点不再是保留弱多态兼容，而是继续把所有读模型、查询和下游调用统一收口到这组字段。

---

## 10. 总结

Profile 当前应明确收口到三层：`user.profile_json` 负责用户级长期画像，`subject.profile_json` 负责学科级学习画像，`user_knowledge_state` 负责细粒度掌握状态，`exam_paper_item` 负责行为快照回放。后续开发应继续强化这条主线，不再回到 `user_profile / mistake` 模型。
