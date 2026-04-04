# 08. Profile 引擎

## 1. 文档定位

Profile 负责把学习过程沉淀成可被其他引擎直接消费的状态层，同时定义运行时学习记忆该如何与结构化画像协同。

它需要同时回答四类问题：

- 这个用户在这门课里哪些地方已经掌握、哪些地方薄弱
- 这门课下一步更适合怎么练、怎么测、怎么复习
- 这个用户跨学科更稳定的学习偏好是什么
- 这些状态如何进一步沉淀成可读、可编辑、可被 Interact 消费的运行时档案

从本版开始，本文档同时描述两件事，但会明确分开：

- 当前代码已经落地的真相源与闭环
- 下一阶段推荐落地的 runtime memory / markdown 档案设计

这样后续改 Interact、Examine、memory、runtime file layout 时，可以围绕同一份文档持续收敛，而不是把“现状”和“目标态”混在一句话里。

---

## 2. 当前已落地的真相源与闭环

### 2.1 当前已经真正闭环的主线

当前已经跑通的 Profile 主线是：

1. 判卷完成，回写 `exam_paper` / `exam_paper_item`
2. `workflows/profile/mastery_updater.py` 基于答题结果更新 `user_knowledge_state`
3. `workflows/profile/review_scheduler.py` 基于掌握度和复习状态安排复习任务
4. 同一轮判卷事务里刷新 `subject.profile_json`
5. 同一轮判卷事务里刷新 `user.profile_json`
6. `/api/v1/subjects/{subject}/profile/mastery` 返回细粒度状态 + 学科级画像 + 用户级画像

也就是说，当前真正稳定的闭环是：

`做题 -> 判卷 -> mastery state -> review -> subject/user summary -> 再影响下一轮出题`

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

### 2.3 当前真实真相源

当前需要明确区分“真相源”和“派生摘要”：

#### A. 结构化真相源

- `exam_paper_item`
  承载题目作答、对错、错因、题型、难度、命中的 node refs 等原始学习行为。
- `user_knowledge_state`
  承载按 `teaching_unit_id` 或 `knowledge_node_id` 聚合后的掌握状态与复习状态。
- `chat_message`
  承载聊天历史、引用上下文、滑选来源等对话事实。

#### B. 聚合摘要层

- `subject.profile_json`
  学科级学习/出题先验。
- `user.profile_json`
  跨学科轻量用户画像。

#### C. 运行时伴生层

- `learning_logs`
  事件型学习日志。
- `LEARNER.md`
  当前已经存在的人类可读运行时档案。

其中 A 是业务真相源，B 是缓存式聚合摘要，C 是运行时伴生信息，不应反向篡改 A。

---

## 3. 当前已确认的问题

这部分不是否定现有实现，而是明确接下来需要修的设计缝隙。

### 3.1 Interact 文档描述超前于当前代码

当前 `docs/designs/06_interact_engine.md` 和旧的 profile 描述中，容易给人一种“Interact 已经稳定读取 `user.profile_json`、`subject.profile_json`、`LEARNER.md`、memory store”的印象。

但按当前代码核对，Interact 主 workflow 实际稳定消费的是：

- 最近聊天历史
- 薄弱点摘要
- 近期错题摘要
- RAG 检索片段
- `selected_context`

也就是说，`Profile -> Interact` 的主消费链还没有真正完整打通；当前最强闭环仍然是 `Examine -> Profile -> Examine`。

### 3.2 `shared/infra/context.py` 已有能力，但还没成为主路径

仓库里已经有通用的教学上下文组装器，能够统一读取：

- memory store 聚合画像
- `LEARNER.md`
- 相关 recall 结果
- 知识检索结果

但 Interact 主 workflow 目前没有直接复用这套能力，而是维持了自己的一套 prompt 组装逻辑。

这意味着当前存在两个事实：

- AI 平台底座能力已经具备
- 主业务流程还没有完全接上

### 3.3 `LEARNER.md` 目前不是 Profile 真状态的稳定镜像

当前判卷后会：

- 写 learning log
- 同步 memory store 聚合画像到 `LEARNER.md`
- 追加少量“最近学习主题 / 教学备注”

但它还不是以下对象的稳定镜像：

- `subject.profile_json`
- `user.profile_json`
- `user_knowledge_state`

所以现在的 `LEARNER.md` 更接近“运行时补充文档”，而不是“结构化画像的可读投影”。

### 3.4 `app.shared.*` 才是规范入口，`app.teaching.*` 应视为兼容层

当前仓库已经明确：

- `app/shared/*` 是新的 canonical import path
- `app/teaching/*` 仍有一整套兼容副本

新设计应统一以 `app.shared.*` 为准，不再让 `app.teaching.*` 反向驱动 Profile / Memory 方案。

### 3.5 滑选上下文属于 profile memory 的输入事实，但还没有完全持久化到主链路

`selected_context` 和 `source_chunk_id` 已经进入请求模型和 prompt 组装，但主 workflow 持久化路径仍存在缺口。

这意味着：

- “滑选了什么” 已经是对话输入事实
- 但它还没有稳定成为后续 runtime memory 提炼的输入事实

这一点必须在后续 Interact / Memory 联动里补齐。

---

## 4. 推荐的 Profile 分层模型

推荐把 Profile 看成“结构化三层 + 运行时记忆侧链”，而不是只看数据库里的三张摘要。

### 4.1 L0 学习事实层

这一层记录原始行为和上下文事实：

- `exam_paper_item`
- `chat_message`
- `chat_message.contexts_json`
- `chat_message.selected_text`
- `chat_message.source_chunk_id`
- `learning_logs`

这一层的目标不是做推荐，而是给后续聚合、诊断和回放提供可追溯事实。

### 4.2 L1 细粒度掌握层：`user_knowledge_state`

这是当前最稳定、也是最应该继续坚持的结构化真相源，直接绑定：

- `teaching_unit_id`
- `knowledge_node_id`

并保存：

- `mastery_score`
- `confidence_score`
- `stability_score`
- `forgetting_due_at`
- `review_*` 复习调度字段
- `stats_json` 行为统计摘要

### 4.3 L2 学科级画像：`subject.profile_json`

这是 owner-scoped 的 `user + subject` 学科画像摘要，用来表达：

- 这门课当前更适合怎么练
- 这门课当前更适合怎么考
- 当前应优先聚焦哪些 unit / node

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

### 4.4 L3 用户级画像：`user.profile_json`

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

### 4.5 L4 运行时记忆文档层

这一层不是数据库真相源，而是给 Interact 和人工查看服务的可读档案层。

推荐目标态统一为两份主文档：

- `LEARNING_PROFILE.md`
  用户级、跨学科、偏稳定。
- `LEARNING_SUBJECT_PROFILE.md`
  学科级、依赖当前用户和当前 subject、偏动态。

同时保留一份兼容视图：

- `LEARNER.md`

推荐语义：

- `user.profile_json / subject.profile_json / user_knowledge_state` 负责结构化真相
- `LEARNING_PROFILE.md / LEARNING_SUBJECT_PROFILE.md` 负责可读投影与运行时教学备注
- `LEARNER.md` 负责兼容旧 prompt / 旧工具 / 旧脚本，不再作为未来唯一主文件名

---

## 5. 运行时文件设计

### 5.1 推荐目录布局

在不改变当前 runtime root 的前提下，推荐后续统一落在：

```text
backend/data/users/<user_id>/
├─ profile/
│  ├─ LEARNING_PROFILE.md
│  ├─ LEARNER.md
│  └─ subjects/
│     └─ <subject>/
│        └─ LEARNING_SUBJECT_PROFILE.md
└─ logs/
   └─ learning_events.jsonl        # 可选未来增强
```

### 5.2 为什么默认仍放 `backend/data/`，而不是直接切到 `.atm/`

你当前设想里提到了 `.atm/`。从产品角度这是合理的，但本仓库当前已经统一通过 runtime data root 管理运行时文件，默认语义仍是 `backend/data/`。

因此本设计文档先给出一个更稳的约束：

- 先统一“文件名和语义”
- 暂不在 Profile 设计层直接切换“运行时根目录”

如果未来真的要切到 `.atm/`，应该通过 runtime root 配置迁移完成，而不是在各业务模块里写死一套新的 home-dir 路径语义。

### 5.3 各文件负责什么

#### `LEARNING_PROFILE.md`

适合放：

- 长期学习目标
- 跨学科稳定偏好
- 更稳定的表达风格与节奏偏好
- 跨学科反复出现的学习障碍
- 对老师有价值的长期教学备注

不适合放：

- 每个知识点的精确掌握度
- 高频变动的 review task 列表
- 可由数据库直接重建的大量明细

#### `LEARNING_SUBJECT_PROFILE.md`

适合放：

- 当前学科阶段总结
- 当前聚焦单元 / 聚焦知识点
- 高频错因模式
- 当前推荐练习方式 / 题型 / 难度
- 当前复习与教学策略建议

不适合放：

- 整张知识图谱逐点镜像
- 所有历史试卷明细
- 所有聊天原文

#### `LEARNER.md`

建议定位为兼容层：

- 可由 `LEARNING_PROFILE.md` 派生
- 可继续被旧 prompt / 旧工具读取
- 但新设计不再把它当作唯一主档案

---

## 6. 目标态读写责任边界

### 6.1 Profile 的职责

Profile 负责：

- 更新 `user_knowledge_state`
- 调度 review
- 刷新 `subject.profile_json`
- 刷新 `user.profile_json`
- 生成或刷新用户级 / 学科级运行时画像文档

Profile 不负责：

- 直接生成整段自由教学对话
- 持有完整聊天历史
- 替代知识库检索

### 6.2 Interact 的职责

Interact 应该读取：

- 最近聊天历史
- `selected_context`
- RAG citations
- 薄弱点摘要
- 近期错题摘要
- `subject.profile_json`
- `user.profile_json`
- `LEARNING_SUBJECT_PROFILE.md`
- `LEARNING_PROFILE.md`
- recall 出来的高价值 memory entries

Interact 应该写入：

- `chat_session`
- `chat_message`
- 与本轮对话相关的 learning log
- 经过提炼的 memory entries

Interact 不应做的事：

- 直接把原始整段聊天无脑 append 到 markdown 画像文件
- 绕过 Profile 自己维护另一套“掌握度真相”

### 6.3 Examine 的职责

Examine 应该读取：

- `user_knowledge_state`
- `subject.profile_json`
- `user.profile_json`
- 当前学科运行时画像文档

Examine 应该写入：

- `exam_paper` / `exam_paper_item`
- 判卷结果
- mastery / review / summary
- learning log
- 触发 profile runtime docs 刷新

### 6.4 Markdown 文档的写入策略

推荐统一采用：

`结构化真相先落库 -> Profile 聚合 -> Profile 生成 markdown 文档`

而不是：

`Interact / Examine 各自直接 append 各自理解的一段文字`

原因：

- 保证文档内容和结构化真相源一致
- 减少多处 prompt / 多处服务对同一文件争写
- 避免把偶发、低置信度的单轮对话误写成长期画像

---

## 7. 当前主 Pipeline 与目标补强点

### 7.1 当前已经稳定的 pipeline

| 步骤 | 当前主模块 | 输入 | 输出 |
| --- | --- | --- | --- |
| 1. 判卷完成 | `workflows/examine/answer_grader.py` | `exam_paper_item.answer_content` + 知识上下文 | `exam_paper_item.is_correct / feedback / error_cause` |
| 2. 掌握度更新 | `workflows/profile/mastery_updater.py` | 判卷后的 `exam_paper_item` | `user_knowledge_state` |
| 3. 复习调度 | `workflows/profile/review_scheduler.py` | 更新后的 state | pending review 状态 |
| 4. 学科画像聚合 | `workflows/profile/subject_profile.py` | state + 最近答题快照 | `subject.profile_json` |
| 5. 用户画像聚合 | `workflows/profile/user_profile.py` | 各学科摘要 + 最近答题快照 | `user.profile_json` |
| 6. 画像读取 | `profile_service` | 当前学科 state + 两层摘要 | `/profile/mastery` 返回值 |

补充说明：

- `complete_review_task()` 也会在同一轮服务事务里刷新 `subject.profile_json` 与 `user.profile_json`
- 当前不单独起持久化 job 表，仍优先用现有服务入口 + workflow 组织

### 7.2 下一阶段建议补强的 pipeline

推荐补成：

`聊天 / 做题 -> learning fact -> mastery / summary -> runtime docs refresh -> Interact 再读入`

更具体一点：

1. 聊天或判卷产生学习事实
2. 结构化事实先写 `chat_message / exam_paper_item / learning_logs`
3. Profile 刷新 `user_knowledge_state / subject.profile_json / user.profile_json`
4. Profile 统一生成 `LEARNING_PROFILE.md / LEARNING_SUBJECT_PROFILE.md / LEARNER.md`
5. Interact 新一轮上下文读取这三层结构化摘要与 markdown 档案

---

## 8. 画像如何影响其他引擎

### 8.1 对 Examine 的影响

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
- `focus_node_ids`
- `notes`

`question_builder.py` 的确定性回退模板也会读取 `difficulty_focus`，因此即使 LLM 回退，Profile 对出题仍然有效。

另外，`exams/generate.difficulty` 现在支持显式覆盖：

- 传 `easy / medium / hard / mixed` 时，优先覆盖 profile 自动推断
- 不传时，继续使用 `subject.profile_json.difficulty_focus`

### 8.2 对 Interact 的影响

当前已经稳定生效的输入是：

- 薄弱点摘要
- 近期错题摘要
- 最近聊天历史
- RAG citations
- `selected_context`

下一阶段目标应补上：

- `subject.profile_json`
- `user.profile_json`
- `LEARNING_SUBJECT_PROFILE.md`
- `LEARNING_PROFILE.md`
- recall memory entries

这里要特别强调：

- 当前 Interact 还没有稳定完整消费这些 profile memory 层
- 文档目标态必须和代码分开描述，避免误导后续实现

### 8.3 对 Digest 的影响

当前 Digest 侧主要还停留在“可读取这些摘要层”的设计空间，尚未像 Examine 一样形成稳定消费逻辑。

因此目前 Profile 和其他引擎的最强闭环，优先还是 Examine。

---

## 9. 数据与字段约定

### 9.1 `user.profile_json`

当前把它当成轻量聚合缓存，而不是强 schema 的大对象中心。

约定：

- 只放跨学科稳定摘要
- 不放 unit/node 级细粒度状态
- 不承担历史版本职责

### 9.2 `subject.profile_json`

当前把它当成学科内的学习/出题先验缓存。

约定：

- 以当前用户在该学科下的状态为准
- `focus_teaching_unit_ids / focus_node_ids` 只引用当前稳定主对象
- 不额外拆 history/version 表

### 9.3 `user_knowledge_state.stats_json`

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

### 9.4 Markdown 画像文件

约定：

- 它们是运行时伴生文档，不是数据库主表
- 它们必须可由结构化真相源重建
- 它们可以承载“教学备注”和“人类可读组织”，但不承载强事务语义

---

## 10. 边界与迁移建议

### 10.1 当前阶段不新增额外 profile API 面

当前继续坚持：

- 不新增 `/profile/summary`
- 不新增 `/profile/runtime-docs`
- 前端继续以 `/profile/mastery` 为主读模型入口

后续 runtime docs 若要暴露给前端，也应该优先作为现有接口的附属字段或内部消费，不宜过早扩 API 面。

### 10.2 当前阶段不新增新的 profile summary 主表

在现有实现基础上，继续坚持：

- `user.profile_json`
- `subject.profile_json`
- `user_knowledge_state`

这三层已经足够作为结构化主干，不必再为 markdown 文档新增一套 profile 主表。

### 10.3 新代码统一走 `app.shared.*`

后续无论是：

- memory store
- learner docs
- context builder
- teaching functions

都应以 `app.shared.*` 为规范入口。

### 10.4 对 `.atm/` 的处理

如果未来确实希望：

- CLI 模式
- 桌面本地单用户模式
- 家目录级长期陪伴档案

都共享同一套运行时目录，那么推荐通过 runtime root 配置切换到 `.atm/`，而不是在 Profile 文档层提前把业务语义绑死在 `.atm/`。

---

## 11. 一句话结论

当前 Profile 最稳的部分仍然是：

- `user_knowledge_state`
- `subject.profile_json`
- `user.profile_json`

下一阶段最值得推进的不是再造一套新表，而是把这三层结构化状态，稳定投影到两份 runtime markdown 档案中：

- `LEARNING_PROFILE.md`
- `LEARNING_SUBJECT_PROFILE.md`

并让 Interact / Examine 都围绕这套“结构化真相 + 可读档案”的组合来读写，而不是各自维护一套零散记忆逻辑。

## 0. 2026-04 Profile 闭环修正

- 本批没有新增 schema，也没有新增 profile summary 主表，仍保持 `user.profile_json / subject.profile_json / user_knowledge_state` 三层结构。
- `update_mastery_from_exam()` 的核心收益来自更精确的 `exam_paper_item.node_refs_json`：node mastery 现在只会由真正命中的节点回写，不再把同单元其它 membership 节点一起拉动。
- unit mastery 仍按 `exam_paper_item.teaching_unit_id` 聚合，node mastery 按精确 `node_refs_json` 聚合；这一点是 Examine/Profile 闭环信号纯度的关键约束。
- `subject.profile_json.focus_teaching_unit_ids / focus_node_ids` 仍继续作为 Examine 的出题先验，但本批没有改动对外 API，也没有新增额外画像读取接口。

