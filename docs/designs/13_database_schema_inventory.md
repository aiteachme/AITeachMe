# 13. 数据库结构方案

## 1. 设计原则

- 本文档只写正式方案，不做旧方案兼容设计。
- 主干归属统一到 `user_id` / `subject_id`。
- 所有主表统一使用数值主键 `id`。
- `subject.slug` 只作为外部路由标识，不作为内部主关系。
- 文件存储统一使用 `storage_backend + storage_key`。
- 原始资料直接存解析结果，不再额外保留 `raw_file -> document` 这种 1:1 中间主表。
- 向量层只保留一张表：`chunk_embeddings`，但它服务统一检索分块 `retrieval_chunk`，而不是只服务原始资料。
- 标题路径、章节名、主题词只作为弱元信息；统一检索层以语义内容、结构邻接、证据引用为主，不做关键词驱动设计。
- 不再单独拆版本表、快照表、上下文表；能并回主表就并回主表。
- `chat_session` / `chat_message` 保持当前已定稿结构，不在本轮改字段形态。

## 2. 顶层关系

```text
user
  └─ 1:N subject
        ├─ 1:N raw_file
        │     └─ 1:N raw_file_asset
        ├─ 1:N knowledge_document
        ├─ 1:N knowledge_node
        │     ├─ 1:N knowledge_alias
        │     ├─ 1:N knowledge_edge
        │     └─ 1:N knowledge_evidence
        ├─ 1:N teaching_unit
        │     └─ 1:N teaching_unit_membership
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
        ├─ 1:N retrieval_chunk
        │     └─ 1:N chunk_embeddings
        └─ 1:N chat_session
              └─ 1:N chat_message
```

- `retrieval_chunk` 是统一检索层，来源可以是 `raw_file`、`knowledge_document`、`knowledge_node`、`knowledge_edge`、`question_template`、`exam_paper_item`。

## 3. 表设计

### `user`

- 用途：用户主表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `username` | 用户名 |
| `email` | 邮箱 |
| `last_used_ip` | 最近一次使用 IP |
| `profile_json` | 用户画像 JSON |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `subject`

- 用途：学科 / 工作空间主表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `slug` | 对外学科标识 |
| `name` | 学科名 |
| `description` | 学科描述 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `raw_file`

- 用途：原始资料主表。
- 对应文件目录：`raw_files/`、`raw_markdowns/`、`assets/`。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `uid` | 文件唯一业务 ID |
| `original_filename` | 原始资料名 |
| `file_ext` | 扩展名 |
| `mime_type` | MIME 类型 |
| `storage_backend` | 原文件存储后端 |
| `storage_key` | 原文件存储 key |
| `parsed_markdown` | 解析后的原始 Markdown 内容 |
| `parser_used` | 实际使用的解析器 |
| `parse_metadata_json` | 解析元信息 JSON |
| `parse_error_message` | 解析失败原因，可空 |
| `status` | 文件状态 |
| `ingest_status` | ingest 状态 |
| `size_bytes` | 文件大小 |
| `checksum_sha256` | 文件哈希 |
| `estimated_pages` | 页数/页片估计 |
| `detected_language` | 检测语言 |
| `classification_json` | 文件分类结果 JSON |
| `quality_score` | 解析质量分 |
| `image_count` | 提取图片数 |
| `digest_current_step` | digest 当前处理阶段，可空 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `raw_file_asset`

- 用途：原始资料解析出的图片、公式图、附件资源表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `raw_file_id` | 所属原始资料 |
| `asset_name` | 资源文件名 |
| `asset_kind` | `image` / `formula` / `attachment` |
| `storage_backend` | 存储后端 |
| `storage_key` | 存储 key |
| `mime_type` | MIME 类型 |
| `page_num` | 来源页码 |
| `width` | 宽度 |
| `height` | 高度 |
| `ocr_text` | OCR 文本 |
| `created_at` | 创建时间 |

### `retrieval_chunk`

- 用途：统一检索分块表，专门服务后续 RAG、引用定位、重排召回。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 用户 |
| `subject_id` | 学科 |
| `source_type` | `raw_file` / `knowledge_document` / `knowledge_node` / `knowledge_edge` / `question_template` / `exam_paper_item` |
| `source_id` | 来源对象 ID |
| `chunk_role` | `source_excerpt` / `knowledge_section` / `concept_card` / `relation_card` / `question_stem` / `question_explanation` |
| `chunk_index` | 分块序号 |
| `level` | 标题层级 / 结构层级 |
| `title` | 分块标题 |
| `header_path` | 标题路径 |
| `digest_chunk_uid` | 稳定分块业务 ID |
| `build_session_id` | 构建会话 ID |
| `content` | 分块正文 |
| `token_count` | token 数 |
| `page_num` | 来源页码，可空 |
| `metadata_json` | 页码、偏移、标题层级、结构邻接、重排权重等额外元信息 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `chunk_embeddings`

- 用途：唯一向量表，服务统一检索分块 `retrieval_chunk`。
- SQLite 本地模式下直接映射 `sqlite-vec` 虚拟表，保持极简结构，不额外塞关系型元字段。

| 字段 | 说明 |
| --- | --- |
| `chunk_id` | `retrieval_chunk.id`，同时作为主键 |
| `embedding` | 向量值 |

### `knowledge_document`

- 用途：用户可读知识文档表。
- 对应文件目录：`knowledge_markdowns/`。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `doc_type` | `chapter` / `merged` |
| `chapter_index` | 章节序号，合并文档可为空 |
| `title` | 标题 |
| `summary` | 摘要 |
| `content_markdown` | 文档 Markdown 内容 |
| `storage_backend` | 文档存储后端 |
| `storage_key` | 文档存储 key |
| `tags_json` | 章节标签 JSON |
| `source_raw_file_ids_json` | 来源原始资料 ID 列表 |
| `word_count` | 字数统计 |
| `version_no` | 版本号 |
| `status` | `draft` / `published` / `archived` |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `knowledge_node`

- 用途：知识图谱节点表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `node_type` | 节点类型 |
| `canonical_name` | 规范名 |
| `normalized_name` | 归一化名称 |
| `summary` | 节点摘要 |
| `body` | 节点正文 |
| `status` | 状态 |
| `confidence` | 置信度 |
| `merged_into_node_id` | 合并目标节点 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `knowledge_alias`

- 用途：知识节点别名表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `node_id` | 所属节点 |
| `alias` | 别名 |
| `normalized_alias` | 归一化别名 |
| `language` | 语言 |
| `source` | 来源 |
| `confidence` | 置信度 |
| `is_primary` | 是否主别名 |
| `status` | 状态 |
| `created_at` | 创建时间 |

### `knowledge_edge`

- 用途：知识图谱关系边表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `source_node_id` | 起点节点 |
| `target_node_id` | 终点节点 |
| `edge_type` | 边类型 |
| `description` | 关系描述 |
| `weight` | 权重 |
| `confidence` | 置信度 |
| `status` | 状态 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `knowledge_evidence`

- 用途：图谱证据表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `node_id` | 节点 ID，可空 |
| `edge_id` | 边 ID，可空 |
| `retrieval_chunk_id` | 来源检索分块 |
| `quote_text` | 引文文本 |
| `source_span_start` | 起始偏移 |
| `source_span_end` | 结束偏移 |
| `evidence_role` | 证据角色 |
| `extraction_method` | 抽取方式 |
| `field_scope` | 作用字段 |
| `confidence` | 置信度 |
| `is_active` | 是否有效 |
| `created_at` | 创建时间 |

### `teaching_unit`

- 用途：教学单元主表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `canonical_name` | 规范名称 |
| `normalized_name` | 归一化名称 |
| `member_signature` | 成员签名 |
| `summary` | 摘要 |
| `learning_objectives_json` | 学习目标 JSON |
| `status` | 状态 |
| `confidence` | 置信度 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `teaching_unit_membership`

- 用途：知识节点归属教学单元的关系表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `unit_id` | 教学单元 |
| `knowledge_node_id` | 知识节点 |
| `role` | 归属角色 |
| `score` | 归属得分 |
| `created_at` | 创建时间 |

### `curriculum_version`

- 用途：课程结构统一版本表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `version_no` | 版本号 |
| `status` | `draft` / `published` / `archived` |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `curriculum_tree_node`

- 用途：课程主题树节点表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `curriculum_version_id` | 所属课程版本 |
| `parent_tree_node_id` | 父节点 |
| `title` | 节点标题 |
| `normalized_title` | 归一化标题 |
| `node_type` | `chapter` / `section` / `theme` / `unit_bucket` |
| `anchor_type` | 锚点类型 |
| `order_index` | 排序 |
| `summary` | 摘要 |
| `confidence` | 置信度 |
| `is_system` | 是否系统锚点 |
| `created_at` | 创建时间 |

### `curriculum_unit_link`

- 用途：教学单元挂树关系表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `curriculum_version_id` | 所属课程版本 |
| `tree_node_id` | 课程树节点 |
| `teaching_unit_id` | 教学单元 |
| `membership_role` | 挂载角色 |
| `membership_source` | 挂载来源 |
| `score` | 挂载得分 |
| `created_at` | 创建时间 |

### `curriculum_dependency`

- 用途：教学单元先修依赖表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `curriculum_version_id` | 所属课程版本 |
| `source_unit_id` | 前置单元 |
| `target_unit_id` | 后续单元 |
| `dependency_type` | `prerequisite` / `corequisite` |
| `confidence` | 置信度 |
| `supporting_edge_count` | 支撑边数量 |
| `derivation_metadata_json` | 派生元信息 |
| `created_at` | 创建时间 |

### `question_template`

- 用途：题目模板表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `teaching_unit_id` | 关联教学单元 |
| `curriculum_version_id` | 来源课程版本 |
| `question_type` | 题型 |
| `difficulty` | 难度 |
| `stem` | 题干 |
| `stem_hash` | 题干哈希 |
| `options_json` | 选项 JSON |
| `answer` | 标准答案 |
| `explanation` | 解析 |
| `template_version` | 模板版本 |
| `status` | 状态 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `question_template_node_link`

- 用途：题目模板与知识节点关联表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `question_template_id` | 题目模板 |
| `knowledge_node_id` | 知识节点 |
| `coverage_weight` | 覆盖权重 |
| `role` | 关联角色 |
| `created_at` | 创建时间 |

### `exam_paper`

- 用途：试卷主表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 所属用户 |
| `subject_id` | 所属学科 |
| `exam_mode` | 试卷模式 |
| `curriculum_version_id` | 试卷使用的课程版本 |
| `status` | 状态 |
| `total_items` | 题目总数 |
| `submitted_at` | 提交时间 |
| `graded_at` | 判卷时间 |
| `total_score` | 总分 |
| `score_obtained` | 得分 |
| `duration_seconds` | 作答时长 |
| `metadata_json` | 组卷上下文、选题理由等统一元信息 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### `exam_paper_item`

- 用途：试卷题目快照表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `exam_paper_id` | 所属试卷 |
| `question_template_id` | 来源模板 |
| `item_order` | 题目顺序 |
| `snapshot_stem` | 快照题干 |
| `snapshot_options_json` | 快照选项 |
| `snapshot_answer` | 快照答案 |
| `snapshot_explanation` | 快照解析 |
| `snapshot_teaching_unit_id` | 快照教学单元 |
| `snapshot_node_links_json` | 快照知识点关联 |
| `snapshot_difficulty` | 快照难度 |
| `snapshot_question_type` | 快照题型 |
| `created_at` | 创建时间 |

### `user_answer_attempt`

- 用途：用户作答与判题结果表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `exam_paper_item_id` | 试卷题目 |
| `user_id` | 用户 |
| `attempt_no` | 第几次作答 |
| `user_answer` | 用户答案 |
| `is_correct` | 是否正确 |
| `score_obtained` | 本次得分 |
| `score_max` | 满分 |
| `time_spent_seconds` | 作答耗时 |
| `hint_used` | 是否用了提示 |
| `confidence_self_report` | 用户自评信心 |
| `error_cause_label` | 错因标签 |
| `created_at` | 创建时间 |

### `user_knowledge_state`

- 用途：用户掌握度状态表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 用户 |
| `subject_id` | 学科 |
| `granularity` | `unit` / `node` |
| `target_id` | 目标对象 ID |
| `mastery_score` | 掌握度 |
| `confidence_score` | 置信度 |
| `stability_score` | 稳定度 |
| `forgetting_due_at` | 预计遗忘时间 |
| `review_priority` | 复习优先级 |
| `total_attempts` | 总作答次数 |
| `correct_attempts` | 正确次数 |
| `last_attempt_at` | 最近作答时间 |
| `state_version` | 状态版本号 |
| `last_recomputed_at` | 最近重算时间 |
| `updated_at` | 更新时间 |

### `review_task`

- 用途：复习任务表。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 用户 |
| `subject_id` | 学科 |
| `task_type` | `review_unit` / `review_node` / `review_exam` / `prereq_patch` |
| `target_id` | 目标对象 ID |
| `target_granularity` | 目标粒度 |
| `priority` | 优先级 |
| `scheduled_at` | 计划执行时间 |
| `status` | 状态 |
| `interval_days` | 间隔天数 |
| `ease_factor` | 记忆难度因子 |
| `repetition_count` | 重复次数 |
| `reason` | 触发原因 |
| `source_state_id` | 来源掌握度状态 |
| `source_exam_paper_id` | 来源试卷 |
| `created_at` | 创建时间 |
| `completed_at` | 完成时间 |
| `expired_at` | 过期时间 |

### `chat_session`

- 用途：会话主表。
- 说明：这张表已经定稿，继续保留当前思路。

| 字段 | 说明 |
| --- | --- |
| `id` | 会话 ID |
| `subject` | 学科 slug |
| `user_id` | 用户 |
| `title` | 会话标题 |
| `source` | 会话来源 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `last_message_at` | 最后一条消息时间 |

### `chat_message`

- 用途：聊天消息表。
- 说明：这张表已经定稿，继续保留当前思路。

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `subject` | 学科 slug |
| `user_id` | 用户 |
| `session_id` | 会话 ID |
| `turn_id` | 轮次 ID |
| `source` | 消息来源 |
| `anchor_id` | 文档锚点 ID |
| `selected_text` | 用户选中文本 |
| `source_chunk_id` | 来源 chunk |
| `role` | `user` / `assistant` |
| `content` | 消息内容 |
| `contexts` | 检索上下文 JSON |
| `created_at` | 创建时间 |

## 4. 重构时不能丢的信息

- `raw_file.file_path` 收敛为 `raw_file.storage_backend + storage_key`；`raw_file.markdown_path` 收敛为 `raw_file.parsed_markdown`；`raw_file.asset_dir` 收敛为 `raw_file_asset` 记录集合，不能把文件、Markdown、资源三条链路混没了。
- `raw_file.error_message` 的语义并入 `raw_file.parse_error_message`，不能丢失败原因。
- `raw_file.classification_result` 的语义并入 `raw_file.classification_json`，不能丢文件分类结论。
- `raw_file.quality_score` 保留，后续 ingest 质量评估和重试策略要能继续用。
- `document.source_file_id` / `title` / `markdown_content` / `current_step` 分别由 `raw_file.id` / `raw_file.original_filename` / `raw_file.parsed_markdown` / `raw_file.digest_current_step` 承担，不再单独保留 `document` 主表。
- `document_chunk.level`、`digest_chunk_uid`、`build_session_id` 必须进入 `retrieval_chunk`，否则统一构建、引用定位、增量重建都会丢稳定标识。
- `knowledge_doc.tags`、`source_file_ids`、`word_count`、`version` 对应保留到 `knowledge_document.tags_json`、`source_raw_file_ids_json`、`word_count`、`version_no`。
- `knowledge_revision.title/summary/body` 直接并入 `knowledge_node.canonical_name`、`summary`、`body`；`edge_revision.description/weight/confidence` 直接并入 `knowledge_edge`。
- `teaching_unit_revision.title/summary/learning_objectives_json` 直接并入 `teaching_unit`。
- `taxonomy_anchor.normalized_title/confidence/is_system` 并入 `curriculum_tree_node`，不能只留一个 `anchor_type`。
- `theme_tree_version`、`prereq_dag_version`、`curriculum_snapshot` 三层版本语义统一收敛到 `curriculum_version`，但树结构、依赖结构、发布态三类信息都必须保留。
- `exam_paper_generation_context` 可以合并进 `exam_paper.metadata_json`，但 `selection_reason_json`、`target_theme_tree_node_id`、`weakness_state_ids_json`、`review_task_ids_json`、`excluded_template_ids_json` 这些键不能丢。

## 5. 直接结论

- 原始资料主表：`raw_file`
- 知识文档主表：`knowledge_document`
- 图谱主表：`knowledge_node`、`knowledge_edge`
- 课程主表：`teaching_unit`、`curriculum_version`
- 测评主表：`question_template`、`exam_paper`
- 掌握度主表：`user_knowledge_state`、`review_task`
- 检索层主表：`retrieval_chunk`
- 向量表：只保留 `chunk_embeddings` 一张，统一服务原始资料、知识文档、知识图谱、题目检索
- 不再设计旧方案兼容表，也不再单独拆版本表、快照表、上下文表
