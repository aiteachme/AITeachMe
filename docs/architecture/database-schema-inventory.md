# 数据库结构清单（当前实现）

本文档描述当前代码和迁移实际维护的数据库结构。历史方案中出现过的
`curriculum / teaching_unit / taxonomy_anchor / theme_tree_node / unit_dependency`
已经从当前实现中移除，不应再作为“现有表”引用。

## 当前业务表

### 用户、系统与课程

- `user`：用户主表；除注册状态外保存 `role`、显示名称、头像、邮箱验证时间和游客合并目标。`runtime_settings_json` 仅保留旧版本地设置兼容数据，当前有效本地覆盖由 `system_runtime_settings` 管理。
- `email_confirmation`：邮箱验证记录。
- `course`：课程空间主表，保存标题、描述、学习意图、文档摘要、LLM 上下文与构建锁字段。
- `system_runtime_settings`：系统级运行设置覆盖与状态快照表；这是一张单行表，正常只有 `id = "runtime"` 一行。同一行保存当前有效 settings 快照哈希与来源，避免额外快照表。

### 认证、身份与游客迁移

- `auth_identity`：Google、QQ、微信等第三方身份绑定；以 provider、应用标识和 provider subject 唯一定位外部身份，不保存 provider access/refresh token。
- `auth_session`：可撤销的 HttpOnly Cookie 会话；仅持久化会话 token 哈希、CSRF token、过期/撤销时间和设备摘要。
- `oauth_flow`：一次性 OAuth `state`、nonce、PKCE verifier、登录/绑定模式和安全返回路径；回调消费后不可重放。
- `auth_rate_limit_bucket`：登录、验证码和 OAuth 发起的数据库级限流窗口。
- `user_merge_job`：游客资产确认迁移的持久化任务，保存迁移状态、资产计数、课程映射、进度和失败信息。

### AI 额度

- `credit_account`：用户额度账户，保存总余额、冻结余额、累计赠送/消费和并发版本。
- `credit_ledger`：不可删除的额度增减账本，记录业务引用、幂等键、操作管理员、原因以及操作前后余额快照。
- `credit_reservation`：DocGen 和人工出卷等长任务的额度预占记录；业务引用和幂等键均有唯一约束，终态为结算或释放。

### 跨课程记忆与学习日志

- `memory_entries`：用户长期记忆条目，按用户、标签和更新时间查询。
- `learning_logs`：跨课程学习事件日志，保存事件类型、课程、摘要和结构化元数据。

这两张记忆表现在属于正式 SQLModel/Alembic schema；不再由 SQLite 专用原始 SQL 在运行时单独维护。

### 文件、切片与知识文档

- `raw_file`：用户文件库中的原始文件和解析状态。`user_id` 是文件归属，`course` 仅保留兼容语义。
- `course_file`：用户文件到课程的多对多绑定表。
- `retrieval_chunk`：解析后的检索切片，包含向量索引元数据、`document_id` 与可选 `digest_chunk_uid`。
- `knowledge_document`：DocGen 发布后的知识文档章节与合并文档记录，使用 `version_no / is_current / status` 表达当前发布态。

### 知识图谱

- `knowledge_unit`：当前图谱节点表，对外 API 使用 KnowledgeUnit 命名；旧设计中的 `knowledge_node` 不再是物理表名。
- `knowledge_edge`：当前图谱边表，连接两个 `knowledge_unit`。
- `knowledge_graph_sync_run`：每次知识文档同步到图谱的运行记录，保存文档版本、图谱修订、状态和质量指标。
- `knowledge_graph_source_ref`：图谱节点/关系的轻量溯源记录，可追到同步批次、知识文档章节、源文件和摘录。

当前 MVP 将别名、证据、轻量 revision 内容并入 JSON 字段：

- `knowledge_unit.aliases_json`
- `knowledge_unit.evidence_refs_json`
- `knowledge_edge.evidence_refs_json`

这能减少表数量并降低导入导出复杂度。新增的 `knowledge_graph_source_ref` 只承接图谱同步溯源，不替代 alias/evidence 的兼容字段。规模化后如果需要高频 alias/evidence 查询，再单独设计规范化表。

### Examine、Profile 与 Chat

- `question_type_registry`：题型注册表。
- `question_template`：题目模板。
- `exam_paper`、`exam_paper_item`：试卷与试卷题目。
- `course_initial_exam_job`：每门课程一次的可恢复首次诊断考卷任务，并持久化构建时选择的模型层级。
- `mastery_drill_session`、`mastery_drill_attempt`：可恢复的闯关会话与逐次作答历史。
- `question_knowledge_unit_link`：题目模板或试卷题目与 `knowledge_unit` 的加权覆盖关系，供出题、判题和掌握度回写使用。
- `exam_study_guide_cache`：试卷判分后生成的学习指南缓存，避免重复生成并支持异步返回。
- `user_knowledge_state`：用户对某个 `knowledge_unit` 的掌握度状态。
- `chat_session`、`chat_message`：伴读对话会话与消息；Planner 已确认构建方案内联在对应 `chat_session.meta_json.confirmed_plan` 中，轻量历史保存在 `chat_session.meta_json.confirmed_plan_history`。

## 已移除或未来演进

以下结构不是当前数据库表：

- `curriculum`
- `teaching_unit`
- `taxonomy_anchor`
- `theme_tree_node`
- `unit_dependency`
- `graph_digest_job / curriculum_derive_job / question_build_job / exam_generate_job / exam_grade_job`
- `confirmed_build_plan`：已收敛进 Planner `chat_session.meta_json.confirmed_plan`。

`backend/app/shared/infra/database/core.py` 会主动清理部分旧表和旧字段，避免本地 SQLite 或历史 PostgreSQL schema 误保留过时结构。后续如果 Examine/Profile 确实需要课程版本、教学单元或主题树，应另起 schema 设计和迁移，不混入现有 P0 收敛。

## 版本与构建状态

- `knowledge_document.version_no` 是当前知识文档发布版本号。
- `knowledge_unit.build_revision_no` 与 `knowledge_edge.build_revision_no` 是图谱构建修订号，不再声明必须等于不存在的 `curriculum.version_no`。
- `/knowledge/build/runtime` 会额外暴露 `graph_metrics.revision_no` 与 `graph_metrics.last_synced_doc_version_no`，用于追踪某次图谱同步对应的图谱修订和文档版本。
- `knowledge_graph_sync_run.doc_version_no` 与 `graph_revision_no` 是图谱溯源的数据库落点；`knowledge_graph_source_ref.sync_run_id` 负责把节点/关系证据挂到同一批同步上。
- 构建运行态不落业务 job 表；当前由 content store 中的 `KnowledgeBuildRuntimeEnvelope` 维护 `docgen_runtime` 与 `graph_runtime`，旧 `build_status.json` 仅作为兼容读写。

## 设计约束

- 不手动新增旧课程结构表。
- API、导入导出和前端展示都以 `knowledge_document + knowledge_unit + knowledge_edge + knowledge_graph_source_ref` 为当前 Digest/图谱产物。
- PostgreSQL 生产 schema 由 `backend/migrations/versions/` 下的 Alembic migration 维护；本地 SQLite 由模型创建并清理历史结构。
- 新增表、字段、唯一约束或外键时，必须同时检查 `backend/app/shared/infra/database/core.py` 的 `_SCHEMA_MODELS`、云端检查脚本和本文清单是否需要同步。
