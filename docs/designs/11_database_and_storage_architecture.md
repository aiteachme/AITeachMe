# 11. 数据库与存储架构设计

## 1. 文档定位

本文档描述当前代码已经落地的数据库与存储架构，并给出后续中心化部署的推荐方向。

重点回答四个问题：

- 现在数据库里到底存什么
- 现在本地文件系统里到底存什么
- 本地部署推荐怎么配
- 以后中心化部署推荐怎么演进

---

## 2. 当前真实存储边界

AITeachMe 当前不是“纯数据库产品”，而是三层并存：

1. 关系数据库  
   `backend/data/aiteachme.db`，由 SQLite 承担主业务数据。
2. 向量索引  
   同一个 SQLite 文件中通过 `sqlite-vec` 的 `chunk_embeddings` 虚拟表承担。
3. 本地文件系统  
   `backend/data/<subject>/` 下保存原始文件、Markdown、图片、知识文档和调试产物。

当前原则很明确：

- 数据库保存结构化真相
- 本地文件保存正式文本产物和调试友好产物
- 开发阶段允许数据库与本地文件双写

---

## 3. 当前数据库里的表族

### 3.1 工作空间与材料层

| 表 | 作用 |
| --- | --- |
| `subject` | 学科工作空间 |
| `raw_file` | 上传文件、解析状态、文件路径、Markdown 路径、asset 目录 |
| `document` | digest graph 可消费的标准文档 |
| `document_chunk` | 文档切块 |
| `chunk_embeddings` | `document_chunk` 的向量索引 |
| `knowledge_doc` | 已发布知识文档章节索引 |

### 3.2 知识图谱层

| 表 | 作用 |
| --- | --- |
| `knowledge_node` | 图谱节点身份层 |
| `knowledge_revision` | 节点版本正文 |
| `knowledge_alias` | 节点别名 |
| `knowledge_edge` | 图谱边 |
| `edge_revision` | 边版本 |
| `evidence_link` | 节点/边到 `document_chunk` 的证据链 |

### 3.3 课程结构层

| 表 | 作用 |
| --- | --- |
| `teaching_unit` | 教学单元身份层 |
| `teaching_unit_revision` | 教学单元版本 |
| `teaching_unit_membership` | 知识点到教学单元的归属 |
| `taxonomy_anchor` | 分类锚点 |
| `theme_tree_version` | 主题树版本 |
| `theme_tree_node` | 主题树节点 |
| `unit_tree_membership` | 教学单元挂树关系 |
| `prereq_dag_version` | 先修 DAG 版本 |
| `unit_dependency` | 教学单元依赖 |
| `curriculum_snapshot` | 当前课程视图快照 |

### 3.4 对话、测评与学习状态

| 表 | 作用 |
| --- | --- |
| `chat_session` / `chat_message` | 对话会话与消息 |
| `question_template` / `question_template_node_link` | 题目模板与知识点映射 |
| `exam_paper` / `exam_paper_item` | 新 assessment 试卷与题目快照 |
| `user_answer_attempt` | 用户作答记录 |
| `user_knowledge_state` | 掌握度状态 |
| `review_task` | 复习调度任务 |
| `exam_paper_generation_context` | 组卷上下文 |

### 3.5 Legacy 兼容表

当前代码里仍保留旧链路数据表：

- `exam`
- `question`
- `exam_submission`
- `answer_record`
- `mistake`
- `user_profile`

这些表仍然可读写，但新功能优先走 workflow-backed 的 assessment / mastery 表。

---

## 4. 当前本地文件系统里的正式产物

每个 subject 当前的正式产物布局：

```text
backend/data/<subject>/
├─ raw/
├─ raw_markdown/
├─ assets/
└─ knowledge_markdown/
```

含义分别是：

- `raw/`：上传原文件
- `raw_markdown/`：ingest 解析出的原始 Markdown
- `assets/`：当前 subject 下的共享扁平图片/附件目录
- `knowledge_markdown/`：已发布的知识文档

另外：

- `knowledge_markdown/_build/`：知识文档 staging / 中间产物
- `debug/`：调试快照
- `temp/`：临时上传文件

---

## 5. 路径与 URI 的当前策略

### 5.1 本地部署

当前数据库字段里保存的通常是绝对本地路径，例如：

- `raw_file.file_path`
- `raw_file.markdown_path`
- `raw_file.asset_dir`
- `knowledge_doc.markdown_path`

这在当前本地优先阶段是合理的，因为：

- 路径稳定
- 调试方便
- 前后端在同一台机器上开发时最省事

### 5.2 Markdown 里的图片路径

Markdown 正文里的图片引用统一约定为：

`../assets/<flattened_asset_name>`

原因：

- `raw_markdown/` 与 `knowledge_markdown/` 都和 `assets/` 同级
- 所有 Markdown 都可以复用同一套相对路径规则

### 5.3 中心化部署时的演进方向

以后上云时，数据库里不应再把“某台机器上的绝对路径”当作长期真相。

更推荐逐步演进为：

- `storage_backend`: `local` / `s3` / `oss` / `minio`
- `storage_uri`: 对象存储 URI 或规范化 key
- `local_cache_path`: 仅作为运行时缓存，不作为主真相

---

## 6. 本地部署推荐方案

本地部署和单机部署的推荐组合就是：

- SQLite
- sqlite-vec
- 本地文件系统

具体建议：

| 能力 | 当前推荐 |
| --- | --- |
| 关系数据库 | SQLite |
| 向量索引 | sqlite-vec |
| 原始文件 / 图片 / Markdown | 本地文件系统 |
| 调试快照 | 本地文件系统 |

这套组合适合当前阶段的原因：

- 安装简单
- 同机调试效率高
- 结构化数据和正式文本产物都可直接观察
- 不需要先引入对象存储、消息队列、独立向量库

结论上，本地部署现在就是：

`SQLite + sqlite-vec + 本地文件系统`

---

## 7. 中心化部署推荐方案

### 7.1 首选方案

以后做中心化部署，最推荐的主路径是：

`PostgreSQL + pgvector + S3/OSS/MinIO`

原因：

- PostgreSQL 对关系查询、JSON、事务、并发写入更稳
- pgvector 与当前 `chunk_embeddings` 迁移路径最自然
- 对象存储天然适合 `raw/raw_markdown/assets/knowledge_markdown`
- 后续多 worker / 多实例共享数据更容易

### 7.2 `MySQL + OSS` 能不能做

可以做，但不建议作为第一优先方案。

原因：

- MySQL 适合关系数据，但向量能力和检索生态不如 PostgreSQL + pgvector 顺手
- 如果继续用 MySQL，通常还要额外接一个向量存储
- 这样最终往往会演变成：

`MySQL + OSS + Milvus/Qdrant/ES`

这比 `PostgreSQL + pgvector + OSS` 更复杂。

所以：

- 如果已经有成熟 MySQL 基础设施，`MySQL + OSS + 独立向量库` 是可行方案
- 如果从零设计，优先 `PostgreSQL + pgvector + OSS/MinIO`

### 7.3 对象存储选择

可以按环境选择：

- 公有云：OSS / S3 / COS
- 私有化：MinIO

接口层只要尽早统一成“存储后端 + storage uri”抽象，底层就能替换。

---

## 8. 各引擎的数据与文件边界

### 8.1 Ingest

- DB：`raw_file`
- FS：`raw/`、`raw_markdown/`、`assets/`

### 8.2 Digest Docs

- DB：`knowledge_doc`
- FS：`knowledge_markdown/`、`knowledge_markdown/_build/`

### 8.3 Digest Graph

- DB：`document`、`document_chunk`、`chunk_embeddings`、`knowledge_*`、`evidence_link`
- FS：读取 `raw_markdown/` 与 `assets/`

### 8.4 Digest Curriculum

- DB：`teaching_unit*`、`taxonomy_anchor`、`theme_tree*`、`prereq_dag*`、`curriculum_snapshot`
- FS：默认无正式文件写入

### 8.5 Interact / Examine / Profile

- DB：聊天、assessment、mastery 相关表
- FS：必要时读取知识文档或 markdown，但主真相仍在 DB

---

## 9. 当前没有单独持久化的“job 表”

当前代码里：

- Docs workflow 已明确不走 job 表
- Graph / Curriculum 的“job_id / run_id”更多是运行时和日志语义
- repository 里相关 `update_*_job()` 目前是兼容 shim，不再真正落表

这意味着当前数据库设计要以“最终业务表”而不是“中间 job 表”为中心。

如果以后需要中心化后台任务恢复能力，再单独引入统一 `workflow_run` / `task_run` 表会更干净。

---

## 10. 推荐迁移顺序

从当前本地优先架构迁移到中心化部署，建议按下面顺序：

1. 先稳定存储抽象  
   把 `raw_file.file_path/markdown_path/asset_dir` 和 `knowledge_doc.markdown_path` 逐步抽象成 `storage_backend + storage_uri`
2. 再切对象存储  
   让 `raw/raw_markdown/assets/knowledge_markdown` 进入 OSS / S3 / MinIO
3. 再切关系库  
   SQLite 迁到 PostgreSQL
4. 最后切向量层  
   `sqlite-vec` 迁到 `pgvector`

这样迁移成本最低，也最容易保持现有工作流代码稳定。

---

## 11. 当前结论

当前最合理的结论是：

- 本地开发与单机部署：`SQLite + sqlite-vec + 本地文件系统`
- 中心化部署首选：`PostgreSQL + pgvector + OSS/MinIO`
- `MySQL + OSS` 不是不能做，但通常要补一个独立向量库，因此不是首选主路径

在这个基础上，数据库负责结构化真相，本地/对象存储负责正式文件产物，这个边界应继续保持不变。
