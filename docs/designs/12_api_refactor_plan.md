# 12. API 重构计划

## 1. 文档定位

本文档只讲接口层收敛，不重复讲数据库细节。

它只回答四个问题：

- API 分组最终保留什么
- 每组 API 对应哪几张主表
- `f8099a3` 的对外能力如何保留
- 哪些 legacy 接口必须下线

数据库主设计看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。

---

## 2. API 分组原则

主分组不改，继续保留：

- `/subjects`
- `/files`
- `/knowledge`
- `/chats`
- `/exams`
- `/profile`

重构重点不是改顶层路径，而是：

- 收紧每组接口的职责
- 让接口对应到稳定主表
- 删除 legacy 子接口和 legacy 读写逻辑

---

## 3. API 到主表的正式映射

| API 分组 | 核心能力 | 正式主表 |
| --- | --- | --- |
| `/subjects` | 学科创建、删除、清空、状态查询 | `user`, `subject` |
| `/files` | 上传、列文件、删文件、重新解析 | `raw_file` |
| `/knowledge` | 构建、文档、总览、图谱详情、chunk 上下文、课程详情 | `knowledge_document`, `retrieval_chunk`, `knowledge_node`, `knowledge_edge`, `teaching_unit`, `curriculum_version` |
| `/chats` | 会话、消息、流式问答、引用上下文 | `chat_session`, `chat_message`, `retrieval_chunk`, `user.profile_json`, `subject.profile_json`, `user_knowledge_state`, `exam_paper_item` |
| `/exams` | 出题、组卷、历史、详情、交卷、判卷、题库视图 | `question_template`, `exam_paper`, `exam_paper_item`, `subject.profile_json`, `user_knowledge_state` |
| `/profile` | 掌握度、复习任务、学习报告、错题视图 | `user.profile_json`, `subject.profile_json`, `user_knowledge_state`, `exam_paper_item` |

---

## 4. 必须兼容 `f8099a3` 的接口能力

这里强调的是功能兼容，不是旧表兼容。

### 4.1 `/knowledge`

必须继续支持：

- `POST /knowledge/build`
- `POST /knowledge/docs`
- `POST /knowledge/overview`
- `POST /knowledge/graph/nodes/detail`
- `POST /knowledge/chunks/context`
- `POST /knowledge/units/detail`
- `POST /knowledge/clear`

新的数据落点：

- `docs` -> `knowledge_document`
- `overview` -> `curriculum_version + knowledge_* + teaching_unit`
- `chunks/context` -> `retrieval_chunk`

### 4.2 `/chats`

必须继续支持：

- 会话列表
- 新建会话
- 删除会话
- 历史消息
- 流式对话

新的数据落点：

- 会话和消息 -> `chat_session`, `chat_message`
- 检索引用 -> `retrieval_chunk`
- 教学上下文 -> `user.profile_json + subject.profile_json + user_knowledge_state + exam_paper_item`

明确要求：

- 不再回退到 `user_profile` 或 `mistake`

### 4.3 `/exams`

必须继续支持：

- 生成试卷
- 查历史
- 查试卷详情
- 提交答案
- 触发判卷
- 删除试卷
- 题库视图

新的数据落点：

- 题模板 -> `question_template`
- 试卷 -> `exam_paper`
- 试卷详情 -> `exam_paper_item`
- 作答 -> `exam_paper_item`
- 试卷选题上下文 -> `exam_paper.selection_context_json`
- 组卷偏好与学科级学习画像 -> `subject.profile_json`

明确要求：

- 不再保留 `exam_generate_job`、`exam_grade_job` 持久化表
- job 状态只保留运行时返回对象

### 4.4 `/profile`

当前 backend 的正式 profile contract 只保留：

- `/mastery`
- `/review/tasks`

其中 profile 读模型应明确来自三层：

- `user.profile_json`
- `subject.profile_json`
- `user_knowledge_state`

旧的 `/list`、`/report`、`/mistakes` 不再进入目标态 contract。  
如果未来真的要恢复这类读模型，也只能从新表派生，不允许重新引入 `user_profile`、`mistake`。

明确要求：

- 不再读取 `user_profile`
- 不再读取 `mistake`

---

## 5. 接口层必须删除的 legacy 内容

| 类型 | 需要删除的内容 | 说明 |
| --- | --- | --- |
| 表 | `exam`, `question`, `exam_submission`, `answer_record`, `mistake`, `user_profile` | 这些表不再是接口真相源 |
| API 依赖 | 任何直接读 `user_profile`、`mistake` 的 service/repo | 必须改成新表派生 |
| job 表 | `question_build_job`, `exam_generate_job`, `exam_grade_job` | 只保留运行时状态，不落库 |
| 命名 | `assessment` 作为正式接口域名 | 目标态统一收口到 `exams` |

---

## 6. 接口收敛设计

### 6.1 `/knowledge`

知识总结页继续由一个聚合接口供数：

- `POST /api/v1/subjects/{subject}/knowledge/overview`

返回主块：

- `snapshot`
- `theme_tree`
- `prereq_dag`
- `graph`
- `units`
- `stats`

注意：

- 这里对外仍然可以叫 `snapshot/theme_tree/prereq_dag`
- 但数据库底层已经统一收敛为 `curriculum_version` 单表快照字段

### 6.2 `/profile`

目标态只保留两类正式能力：

- `mastery`
- `review`

### 6.3 `/exams`

继续保留现有路径组：

- `/generate`
- `/history`
- `/{exam_paper_id}`
- `/{exam_paper_id}/submit`
- `/{exam_paper_id}/grade`
- `/question-bank`

保留原因：

- 前端已经围绕这组路径组织
- 这组路径和目标表设计一致
- 问题不在路径，而在内部仍有旧命名和旧上下文表残留

---

## 7. 运行时 job 语义

`f8099a3` 之后，这几个 job 已经不应该再是数据库表：

- 题库生成 job
- 试卷生成 job
- 判卷 job

目标态统一成：

- API 可返回 job 风格状态对象
- 数据库不保存 job 表
- 最终业务产物直接落正式主表

也就是说：

- `generate` 最终产物是 `exam_paper`
- `grade` 最终结果回写 `exam_paper + exam_paper_item + user_knowledge_state + subject.profile_json`
- `build` 最终产物是 `knowledge_document + curriculum_version + knowledge_*`

---

## 8. 实施顺序

### 阶段 1：先把表和 service 真相源收口

- `knowledge` 全部只读新表
- `exams` 全部只读新表
- `profile` 新旧接口都改成新表派生
- `chats` history fallback 去掉旧表依赖

### 阶段 2：再清理接口命名和废弃路径

- 文档和注释里去掉 `assessment`
- 清掉旧 profile legacy 说明
- 标记 deprecated 的接口准备下线

### 阶段 3：最后删表和删生成物

- 删旧 exam/profile 表
- 删 job 表
- 删旧 repo 读写逻辑

---

## 9. 验收标准

- `f8099a3` 的知识文档、知识总览、聊天检索、考试、画像功能都能由新表提供
- 当前正式 `/profile` 接口不再存在任何读取 `user_profile`、`mistake` 的对外 contract
- `/chats` 的弱点和错题上下文不再有 legacy fallback
- `/exams` 不再依赖 `exam_paper_generation_context` 独立表
- `/knowledge/overview` 继续是一口拿全量主数据
- 数据库中不再有旧 exam/profile/job 表作为运行时依赖

---

## 10. 一句话结论

目标态 API 不是推倒重写路径，而是在保留 `subjects/files/knowledge/chats/exams/profile` 六大资源组的前提下，把所有读写真相源收口到新主表，并彻底切断对旧 exam、旧 profile、旧 job 表的依赖。
