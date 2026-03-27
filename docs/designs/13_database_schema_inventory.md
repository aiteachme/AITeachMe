# 13. 数据库结构主文档

## 1. 文档定位

本文档是数据库唯一主文档，只回答五个问题：

- 目标数据库主树是什么
- 为什么主树要这样设计
- 每张核心表到底存什么
- 这套表如何覆盖 `f8099a3` 版本的真实功能
- 哪些旧表必须删，哪些能力必须保

部署与存储实现看 [11_database_and_storage_architecture.md](./11_database_and_storage_architecture.md)。  
接口层收敛看 [12_api_refactor_plan.md](./12_api_refactor_plan.md)。

---

## 2. 数据库必须满足的能力

目标表设计必须稳定支撑下面这些能力：

- 用户与学科空间管理
- 原始资料上传、解析、资源抽取
- 知识文档构建、重建、版本切换
- RAG 检索、聊天引用、chunk 上下文回溯
- 知识图谱构建与证据绑定
- 教学单元与课程结构发布
- 出题、组卷、交卷、判卷
- 掌握度、薄弱点、复习任务
- 学科清空与删除

这里的“兼容旧版本”指兼容这些功能，不是保留旧表。

---

## 3. 目标主树

```text
user
  └─ 1:N subject
        ├─ 1:N raw_file
        │     └─ 1:N raw_file_asset
        ├─ 1:N retrieval_chunk
        │     └─ 1:N chunk_embedding
        ├─ 1:N knowledge_document
        ├─ 1:N knowledge_node
        │     ├─ 1:N knowledge_alias
        │     ├─ 1:N knowledge_edge
        │     └─ 1:N knowledge_evidence
        ├─ 1:N teaching_unit
        │     └─ 1:N teaching_unit_membership
        ├─ 1:N curriculum_blueprint_node
        ├─ 1:N curriculum_version
        │     ├─ 1:N curriculum_tree_node
        │     ├─ 1:N curriculum_unit_link
        │     └─ 1:N curriculum_dependency
        ├─ 1:N question_template
        │     └─ 1:N question_template_node_link
        ├─ 1:N exam_paper
        │     └─ 1:N exam_paper_item
        │           └─ 1:N user_answer_attempt
        ├─ 1:N user_knowledge_state
        ├─ 1:N review_task
        └─ 1:N chat_session
              └─ 1:N chat_message
```

说明：

- `user -> subject` 是全库根结构。
- `subject` 才是真正的工作空间边界，不再让业务主表直接散挂在 `user` 下。
- 这张图只画 1:N 主干，不展开所有跨边 FK；像 `knowledge_document -> curriculum_version`、`knowledge_evidence -> knowledge_edge` 这类关系以后文表定义为准。
- `chunk_embedding` 是逻辑向量对象；本地 SQLite 可落到 `sqlite-vec` 虚表，中心化部署可落到 PostgreSQL 向量能力。
- `chunk_embeddings_*` 这类影子表不属于业务主树。

---

## 4. 根设计原则

- 表名统一用单数 `snake_case`
- 主关系优先用强外键，不优先用字符串和弱多态
- 少表优先，但不能为了少表把不同生命周期的对象揉烂
- 先区分“业务主表”和“支持表”，不要把所有桥接表都当成同一层级的大表
- 不做 legacy 兼容，不保留旧表旧字段
- 兼容旧功能，不兼容旧命名
- 版本记录内嵌到正式主表，不为重建再拆一层 job 表
- 本地部署和中心化部署共用同一套逻辑模型
- `速成课 / 系统课` 共用同一套主表，只改模式字段、提示词和生成深度
- 为未来 `tools / memory / skills` 预留扩展口，但不提前加空表

### 4.1 还能不能再减表

可以再减一点，但空间已经不大了。

更准确地说：

- 现在这版不是“绝对完美”
- 但主业务表已经比较接近稳定形态
- 真正还能继续减的，主要只剩 3 张支持表
- `chunk_embedding` 不应和业务主表混着统计

建议把这套结构分成三层理解：

#### A. 不能再减的主业务表

这些表不要再减：

- `user`
- `subject`
- `raw_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_node`
- `knowledge_edge`
- `teaching_unit`
- `curriculum_version`
- `question_template`
- `exam_paper`
- `exam_paper_item`
- `user_answer_attempt`
- `user_knowledge_state`
- `review_task`
- `chat_session`
- `chat_message`

原因是它们分别承担：

- 不同生命周期
- 不同查询入口
- 不同状态流转
- 不同删除边界

继续合并，后面很容易重新长回旧项目那种“字段越来越乱、表越来越暧昧”的状态。

#### B. 属于支持层，不要和主业务表一起数

这些表存在是合理的，但不应该和主业务表混在一起数：

- `raw_file_asset`
- `chunk_embedding`
- `knowledge_evidence`
- `teaching_unit_membership`
- `curriculum_tree_node`
- `curriculum_unit_link`
- `curriculum_dependency`
- `question_template_node_link`

其中：

- `chunk_embedding` 更接近向量后端映射
- `*_membership / *_link / *_dependency` 本质是桥接关系
- `question_template_node_link` 是模板覆盖信息，不是用户直接操作的主对象

#### C. 真正还能继续减的 3 张支持表

如果现在第一目标是“再少几张表”，优先只考虑下面 3 张：

1. `knowledge_alias`
   可临时并入 `knowledge_node.aliases_json`
2. `question_template_node_link`
   可临时并入 `question_template.node_refs_json`
3. `curriculum_blueprint_node`
   如果第一阶段暂时不做人工蓝图编辑，可先不单独落表，让 `curriculum_tree_node` 临时承接 `blueprint_key`

这 3 张表的共同点是：

- 都不是当前用户直接操作的主对象
- 都属于“为了查询更稳、后续扩展更顺”而存在的支持结构
- 都可以在 MVP 第一阶段先合并，再在第二阶段拆回独立表

### 4.2 推荐的最小落地版

如果现在就要一套更浓缩、但又不伤主链路的目标态，建议这样取舍：

- 正式保留当前主树里的全部主业务表
- `chunk_embedding` 继续只当存储层逻辑对象，不算业务主表
- `knowledge_alias / question_template_node_link / curriculum_blueprint_node` 标记为“可延后支持表”

也就是说：

- 推荐稳定态：保留文档当前整套主树
- 推荐第一阶段最小落地态：少落 3 张支持表
- 不推荐再继续减 `retrieval_chunk / knowledge_document / exam_paper_item / user_answer_attempt / review_task`

---

## 5. 为什么主树要这样设计

### 5.1 `subject` 必须是主边界

`f8099a3` 和当前代码里大量查询都以 `subject` 为过滤键。  
真正的工作空间不是 `user`，而是“用户的某个学科”。

所以正式设计统一成：

- `user` 管所有者
- `subject` 管学科空间
- 原始资料、知识文档、图谱、课程、考试、聊天都挂在 `subject` 下

### 5.2 `raw_file` 和 `knowledge_document` 不能合并

这两个对象生命周期不同：

- `raw_file` 是原始输入和解析产物
- `knowledge_document` 是 digest 生成的教学讲义

把它们揉成一张表，会把“来源材料”和“生成产物”再次缠在一起。

### 5.3 `retrieval_chunk` 必须保留

聊天检索、知识图谱证据、chunk 上下文回溯，本质都依赖统一 chunk 层。  
所以旧的 `document_chunk` 必须收敛为 `retrieval_chunk`，而不是直接删掉。

### 5.4 `curriculum_blueprint_node` 稳定态建议保留，但允许第一阶段延后物理落表

它不是装饰表，而是 `taxonomy_anchor` 的正式替代。  
它要承担：

- 稳定课程骨架
- 人工修正锚点
- 跨版本对齐键

如果没有这层，课程树每次重建都更容易漂移。

但更务实地讲：

- 稳定态建议保留这张表
- 如果第一阶段只追求最少表，且暂时不做人工蓝图编辑，可以先不单独落这张表
- 这时要由 `curriculum_tree_node` 临时承接 `blueprint_key` 一类稳定锚点语义

### 5.5 `curriculum_version` 不是普通版本号

它不是简单记录“课程第几版”，而是正式发布包。  
它必须承接旧 `curriculum_snapshot` 的语义：

- 当前课程树
- 当前先修依赖
- 当前课程发布上下文

### 5.6 `user_profile` 和 `mistake` 不再单独保留

这两个旧表的能力并没有消失，只是要换成新表派生：

- `user_profile` -> `user_knowledge_state`
- `mistake` -> `user_answer_attempt + exam_paper_item`

也就是说保留能力，不保留旧表。

---

## 6. 必须兼容 `f8099a3` 的能力映射

| `f8099a3` 中的真实能力 | 旧依赖 | 目标设计 |
| --- | --- | --- |
| 上传与解析原始资料 | `raw_file` | `raw_file + raw_file_asset` |
| 章节化知识文档与 merged 文档 | `knowledge_doc + knowledge_docs/*.md` | `knowledge_document` |
| 聊天检索与原文引用 | `document_chunk + chunk_embeddings` | `retrieval_chunk + chunk_embedding` |
| 图谱节点、边、证据 | `knowledge_* + evidence_link` | `knowledge_node + knowledge_alias + knowledge_edge + knowledge_evidence` |
| 教学单元与课程树 | `teaching_unit* + theme_tree* + prereq_dag* + curriculum_snapshot` | `teaching_unit* + curriculum_blueprint_node + curriculum_version*` |
| 出题、组卷、交卷、判卷 | `question_template + exam_paper* + user_answer_attempt` | 保留同名主结构 |
| 试卷选题上下文 | `exam_paper_generation_context` | 并入 `exam_paper.selection_context_json` |
| 掌握度与复习任务 | `user_knowledge_state + review_task` | 保留同名主结构 |
| 旧画像列表 / 报告 / 错题列表 | `user_profile + mistake` | 改为新表派生读模型，不保留旧表 |
| interact 历史里的弱点和错题 fallback | `user_profile + mistake` fallback | 由 `user_knowledge_state + user_answer_attempt` 提供，不再回退旧表 |

结论：

- `f8099a3` 的有效业务能力必须全部覆盖
- `f8099a3` 的旧表、旧命名、旧 fallback 不需要保留

---

## 7. 核心表设计

下面按域给出正式目标表。

### 7.1 用户与学科根表

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `user` | `id` | `username`, `email`, `last_seen_ip`, `profile_json`, `deployment_scope`, `created_at`, `updated_at` | 顶层拥有者。`profile_json` 只放用户画像、偏好和轻量配置。 |
| `subject` | `id`, `user_id -> user.id` | `slug`, `name`, `normalized_name`, `description`, `preferred_digest_mode`, `preferred_digest_note`, `detected_discipline`, `detected_sub_discipline`, `settings_json`, `status`, `created_at`, `updated_at` | 学科空间根。未来学科级 prompt、memory、tool 开关优先放这里。 |

补充：

- `slug` 对外稳定，用于 API 路径。
- 数据库内部仍以 `id` 作为正式外键。
- `subject` 保存 workspace 级稳定先验，负责承接“这门课到底是什么”的长期判断，不只是一段展示名。

### 7.2 材料层

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `raw_file` | `id`, `subject_id -> subject.id` | `uid`, `filename`, `filetype`, `storage_uri`, `markdown_uri`, `asset_root_uri`, `content_hash`, `user_note`, `ingest_status`, `error_message`, `file_size_bytes`, `estimated_pages`, `detected_language`, `detected_discipline`, `detected_sub_discipline`, `detected_content_type`, `material_profile_json`, `parse_metadata_json`, `quality_score`, `image_count`, `created_at`, `updated_at` | 原始资料主表。兼容现有上传、解析、文档识别、digest 模式判断输入。 |
| `raw_file_asset` | `id`, `raw_file_id -> raw_file.id` | `filename`, `asset_kind`, `storage_uri`, `mime_type`, `page_number`, `width`, `height`, `ocr_text`, `created_at` | 资源文件表。为本地文件系统和 OSS 都保留清晰归属。 |

这层要显式承接知识文档模式决策的三类输入：

- `subject.name / description / detected_*` 提供稳定学科先验
- `raw_file.detected_* + material_profile_json` 提供材料自动识别证据
- `raw_file.user_note` 承接用户上传时的附加提示

### 7.3 检索层

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `retrieval_chunk` | `id`, `subject_id -> subject.id`, `raw_file_id -> raw_file.id` | `chunk_uid`, `source_title`, `header_path`, `order_index`, `anchor_id`, `chunk_role`, `content`, `quote_text`, `char_count`, `source_page_from`, `source_page_to`, `build_session_id`, `is_active`, `created_at`, `updated_at` | 统一 chunk 主表。直接替代旧 `document + document_chunk` 的有效能力。 |
| `chunk_embedding` | `id`, `retrieval_chunk_id -> retrieval_chunk.id` | `embedding_model`, `vector_dim`, `vector_ref`, `is_current`, `updated_at` | 逻辑向量对象。物理实现由本地 `sqlite-vec` 或中心化向量后端决定。 |

`retrieval_chunk` 必须显式承担这几件事：

- 聊天检索
- 图谱证据来源
- 原文上下文回溯
- 引用锚点

所以这里不能只保留纯文本，还要保留：

- `source_title`
- `header_path`
- `anchor_id`
- `raw_file_id`

### 7.4 知识文档层

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `knowledge_document` | `id`, `subject_id -> subject.id`, `curriculum_version_id -> curriculum_version.id`, `root_document_id -> knowledge_document.id`, `parent_document_id -> knowledge_document.id` | `package_key`, `version_no`, `build_session_id`, `is_current`, `document_role`, `title`, `summary`, `order_index`, `digest_mode`, `mode_confidence`, `mode_decision_json`, `content_markdown`, `markdown_uri`, `manifest_json`, `source_scope_json`, `build_kind`, `published_at`, `superseded_at`, `created_at`, `updated_at` | 知识文档唯一正式表。直接替代旧 `knowledge_doc`。 |

约束：

- 不再拆 `knowledge_document_version`
- 通过 `package_key + version_no + is_current` 管版本
- `document_role` 建议固定为 `package / chapter / section / merged`

### 7.5 知识图谱层

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `knowledge_node` | `id`, `subject_id -> subject.id`, `merge_target_id -> knowledge_node.id` | `canonical_name`, `normalized_name`, `node_type`, `summary`, `body_markdown`, `confidence`, `status`, `created_at`, `updated_at` | 正式节点表。这里直接吸收旧 `knowledge_revision` 的正文语义。 |
| `knowledge_alias` | `id`, `knowledge_node_id -> knowledge_node.id` | `alias`, `normalized_alias`, `alias_type`, `confidence`, `created_at` | 节点别名。减表优先时可先并入 `knowledge_node.aliases_json`。 |
| `knowledge_edge` | `id`, `subject_id -> subject.id`, `source_node_id -> knowledge_node.id`, `target_node_id -> knowledge_node.id` | `edge_type`, `description`, `confidence`, `status`, `created_at`, `updated_at` | 正式边表。这里直接吸收旧 `edge_revision` 的描述语义。 |
| `knowledge_evidence` | `id`, `retrieval_chunk_id -> retrieval_chunk.id`, `knowledge_node_id -> knowledge_node.id`, `knowledge_edge_id -> knowledge_edge.id` | `quote_text`, `locator_json`, `evidence_role`, `field_scope`, `strength`, `is_active`, `created_at` | 证据表。要求 `knowledge_node_id` 和 `knowledge_edge_id` 二选一。 |

这里明确不用 `target_type + target_id` 这种弱多态，原因很简单：

- 数据库层完整性更强
- 后续查询和删除更稳定
- 更符合你希望的 1:N 主树思路

### 7.6 教学单元与课程结构

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `teaching_unit` | `id`, `subject_id -> subject.id` | `title`, `normalized_title`, `unit_signature`, `summary`, `body_markdown`, `learning_objectives_json`, `difficulty`, `status`, `created_at`, `updated_at` | 教学单元。这里直接吸收旧 `teaching_unit_revision` 的正文语义。 |
| `teaching_unit_membership` | `id`, `teaching_unit_id -> teaching_unit.id`, `knowledge_node_id -> knowledge_node.id` | `role`, `order_index`, `weight`, `created_at` | 单元和知识点绑定表。 |
| `curriculum_blueprint_node` | `id`, `subject_id -> subject.id`, `parent_id -> curriculum_blueprint_node.id` | `blueprint_key`, `title`, `normalized_title`, `node_type`, `order_index`, `source_type`, `is_manual`, `is_system`, `status`, `note`, `created_at`, `updated_at` | 稳定课程蓝图骨架。正式替代 `taxonomy_anchor`。若第一阶段追求最少表，可延后物理落表。 |
| `curriculum_version` | `id`, `subject_id -> subject.id` | `version_no`, `build_session_id`, `status`, `is_current`, `source_kind`, `summary`, `build_context_json`, `published_at`, `superseded_at`, `created_at`, `updated_at` | 正式课程发布包。正式替代 `curriculum_snapshot`。 |
| `curriculum_tree_node` | `id`, `curriculum_version_id -> curriculum_version.id`, `curriculum_blueprint_node_id -> curriculum_blueprint_node.id`, `parent_id -> curriculum_tree_node.id` | `title`, `node_type`, `order_index`, `level`, `summary` | 某个课程版本下的目录树节点。若 `curriculum_blueprint_node` 延后落表，这里要临时承接 `blueprint_key` 语义。 |
| `curriculum_unit_link` | `id`, `curriculum_version_id -> curriculum_version.id`, `curriculum_tree_node_id -> curriculum_tree_node.id`, `teaching_unit_id -> teaching_unit.id` | `role`, `order_index`, `weight` | 课程树和教学单元连接表。 |
| `curriculum_dependency` | `id`, `curriculum_version_id -> curriculum_version.id`, `source_unit_id -> teaching_unit.id`, `target_unit_id -> teaching_unit.id` | `dependency_type`, `confidence`, `note` | 某个课程版本内的先修依赖。 |

这里最重要的决定：

- `curriculum_version` 统一承接旧 `theme_tree_version + prereq_dag_version + curriculum_snapshot`
- `curriculum_blueprint_node` 在稳定态保留，不建议长期省略

### 7.7 出题、考试、学习状态

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `question_template` | `id`, `subject_id -> subject.id`, `teaching_unit_id -> teaching_unit.id`, `curriculum_version_id -> curriculum_version.id` | `question_type`, `difficulty`, `stem`, `stem_hash`, `options_json`, `answer`, `explanation`, `template_version`, `status`, `selection_hints_json`, `created_at`, `updated_at` | 出题模板表。必须兼容 `f8099a3` 的现有 question bank 能力。 |
| `question_template_node_link` | `id`, `question_template_id -> question_template.id`, `knowledge_node_id -> knowledge_node.id` | `coverage_weight`, `role`, `created_at` | 模板覆盖知识点。减表优先时可先并入 `question_template.node_refs_json`。 |
| `exam_paper` | `id`, `user_id -> user.id`, `subject_id -> subject.id`, `curriculum_version_id -> curriculum_version.id` | `title`, `exam_mode`, `status`, `total_items`, `total_score`, `score_obtained`, `duration_seconds`, `selection_context_json`, `submitted_at`, `graded_at`, `created_at`, `updated_at` | 试卷主表。这里直接吸收旧 `exam_paper_generation_context` 的上下文语义。 |
| `exam_paper_item` | `id`, `exam_paper_id -> exam_paper.id`, `question_template_id -> question_template.id` | `item_order`, `question_type`, `difficulty`, `stem_snapshot`, `options_snapshot_json`, `answer_snapshot`, `explanation_snapshot`, `teaching_unit_id`, `node_refs_json`, `score`, `created_at` | 题目快照表。必须兼容 `f8099a3` 的 detail/history/question-bank 读取。 |
| `user_answer_attempt` | `id`, `exam_paper_item_id -> exam_paper_item.id`, `user_id -> user.id` | `attempt_no`, `answer_content`, `is_correct`, `score_obtained`, `score_max`, `time_spent_seconds`, `hint_used`, `confidence_self_report`, `error_cause_label`, `feedback_text`, `created_at` | 作答记录。既服务判卷，也服务错题、画像、聊天历史。 |
| `user_knowledge_state` | `id`, `user_id -> user.id`, `subject_id -> subject.id`, `teaching_unit_id -> teaching_unit.id`, `knowledge_node_id -> knowledge_node.id` | `mastery_score`, `confidence_score`, `stability_score`, `forgetting_due_at`, `review_priority`, `total_attempts`, `correct_attempts`, `last_attempt_at`, `state_version`, `last_recomputed_at`, `stats_json`, `updated_at` | 掌握度主表。要求 `teaching_unit_id` 和 `knowledge_node_id` 二选一。 |
| `review_task` | `id`, `user_id -> user.id`, `subject_id -> subject.id`, `teaching_unit_id -> teaching_unit.id`, `knowledge_node_id -> knowledge_node.id`, `source_state_id -> user_knowledge_state.id`, `source_exam_paper_id -> exam_paper.id` | `task_type`, `priority`, `scheduled_at`, `status`, `interval_days`, `ease_factor`, `repetition_count`, `reason`, `created_at`, `completed_at`, `expired_at` | 复习任务。要求 `teaching_unit_id` 和 `knowledge_node_id` 二选一。 |

这里的关键要求是：

- 旧 `mistake` 功能由 `user_answer_attempt + exam_paper_item` 派生
- 旧 `user_profile` 功能由 `user_knowledge_state` 聚合派生
- 不再新增 `exam_generate_job`、`exam_grade_job` 这类持久化 job 表

### 7.8 聊天层

| 表名 | 主键 / 外键 | 核心字段 | 说明 |
| --- | --- | --- | --- |
| `chat_session` | `id`, `subject_id -> subject.id`, `user_id -> user.id` | `title`, `source`, `created_at`, `updated_at`, `last_message_at` | 会话容器。 |
| `chat_message` | `id`, `chat_session_id -> chat_session.id`, `subject_id -> subject.id`, `user_id -> user.id`, `source_chunk_id -> retrieval_chunk.id` | `turn_id`, `source`, `anchor_id`, `selected_text`, `role`, `content`, `contexts_json`, `created_at` | 聊天消息表。保留 `subject_id/user_id` 冗余索引字段，兼顾按学科清理和现有查询模式。 |

`chat_message.contexts_json` 必须继续保留，原因是：

- 当前聊天引用展示依赖它
- `f8099a3` 的返回结构已经使用这个字段
- 它适合存引用快照，不适合再额外拆很多表

---

## 8. 版本策略

### 8.1 知识文档

版本直接内置在 `knowledge_document`：

- `package_key`
- `version_no`
- `build_session_id`
- `is_current`

不再拆 `knowledge_document_version`。

### 8.2 课程结构

课程版本由 `curriculum_version` 统一表达：

- 课程树
- 单元挂载
- 先修依赖
- 当前发布上下文
- 同一轮 digest 重建批次

不再保留 `theme_tree_version / prereq_dag_version / curriculum_snapshot` 三张版本表。

### 8.3 检索 chunk

`retrieval_chunk` 不单独拆版本表，只保留：

- `build_session_id`
- `is_active`

这已经足够支撑重建、切换和清理。

### 8.4 统一重建批次

为了支持用户反复重建知识文档、图谱和课程结构，但又不额外加一层 job 表，目标态统一采用轻量批次字段：

- `retrieval_chunk.build_session_id`
- `knowledge_document.build_session_id`
- `curriculum_version.build_session_id`

这三个字段足够回答：

- 这批产物是不是同一轮构建出来的
- 哪些旧版本应该被 supersede
- 失败重建时应该回滚哪一批 staging 产物

---

## 9. 这套表为什么还能扩展

### 9.1 不会因为模式变化爆表

`速成课 / 系统课` 只需要落到这些字段：

- `subject.preferred_digest_mode`
- `subject.preferred_digest_note`
- `subject.detected_discipline`
- `raw_file.material_profile_json`
- `raw_file.user_note`
- `knowledge_document.digest_mode`
- `knowledge_document.mode_decision_json`

不需要拆两套文档表、两套路径表、两套考试表。

### 9.2 不会因为部署方式变化改业务表

业务层只认这些逻辑字段：

- `storage_uri`
- `markdown_uri`
- `asset_root_uri`
- `chunk_embedding.vector_ref`

本地是文件路径和 sqlite-vec，中心化是 OSS 和 PostgreSQL 向量能力，业务主表不用变。

### 9.3 不会因为 mastery 算法升级推翻结构

未来不管是历史统计、BKT、IRT 还是别的模型，主落点都还是：

- `user_knowledge_state`
- `review_task`

变化只会进入：

- `stats_json`
- `state_version`
- 调度参数字段

### 9.4 为 `tools / memory / skills` 留了合理扩展口

当前不提前加新表。未来如果真的要加，也有稳定挂点：

- 用户级偏好和长期配置：`user.profile_json`
- 学科级配置：`subject.settings_json`
- 聊天级上下文：`chat_session`
- 聊天级消息快照：`chat_message`

如果未来真的需要事件级工具日志，再新增 `chat_tool_event` 一类子表，也只会挂在 `chat_message` 或 `chat_session` 下，不会推翻主树。

---

## 10. 旧表收敛

| 当前表 / 概念 | 目标表 / 概念 | 动作 |
| --- | --- | --- |
| `document` | 语义并回 `retrieval_chunk` | 删除 |
| `document_chunk` | `retrieval_chunk` | 重命名并补字段 |
| `chunk_embeddings` | `chunk_embedding` | 逻辑下沉为向量实现层 |
| `knowledge_doc` | `knowledge_document` | 重命名 |
| `knowledge_revision` | `knowledge_node` | 合并 |
| `edge_revision` | `knowledge_edge` | 合并 |
| `evidence_link` | `knowledge_evidence` | 重命名并改强外键 |
| `teaching_unit_revision` | `teaching_unit` | 合并 |
| `taxonomy_anchor` | `curriculum_blueprint_node` | 重命名并补稳定键语义 |
| `theme_tree_version + prereq_dag_version + curriculum_snapshot` | `curriculum_version` | 合并 |
| `theme_tree_node` | `curriculum_tree_node` | 重命名 |
| `unit_tree_membership` | `curriculum_unit_link` | 重命名 |
| `unit_dependency` | `curriculum_dependency` | 重命名 |
| `exam_paper_generation_context` | `exam_paper.selection_context_json` | 合并 |
| `exam / question / exam_submission / answer_record / mistake` | 不进入目标态 | 删除 |
| `user_profile` | 由 `user_knowledge_state` 派生替代 | 删除 |
| 各类 `*_job`、`*_lock`、`*_snapshot` 兼容表 | 不进入目标态 | 删除 |

补充：

- 如果采用“第一阶段最小落地态”，可暂不单独落 `knowledge_alias`
- 可暂不单独落 `question_template_node_link`
- 可暂不单独落 `curriculum_blueprint_node`
- 但这三类语义必须分别并入 `knowledge_node`、`question_template`、`curriculum_tree_node`

---

## 11. 实施优先级

建议落库顺序：

1. `user / subject / raw_file / raw_file_asset / retrieval_chunk / knowledge_document`
2. `knowledge_node / knowledge_alias / knowledge_edge / knowledge_evidence / teaching_unit / teaching_unit_membership`
3. `curriculum_blueprint_node / curriculum_version / curriculum_tree_node / curriculum_unit_link / curriculum_dependency`
4. `question_template / question_template_node_link / exam_paper / exam_paper_item / user_answer_attempt / user_knowledge_state / review_task`
5. `chat_session / chat_message`

原因：

- 先把材料、chunk、文档三大底座立稳
- 再上图谱和课程
- 再上考试和画像
- 最后把聊天完全切到新 chunk 和新画像能力

---

## 12. 一句话结论

目标态数据库不是“把旧表全都留着，再外面包一层新名字”，而是用一棵更稳定的主树，完整覆盖 `f8099a3` 的有效能力，同时彻底删除旧 exam、旧 profile、旧 revision、旧 snapshot 和旧 job 表。
