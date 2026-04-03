# 11. 部署与存储架构设计

## 1. 文档定位

本文档只讲三件事：

- 本地部署怎么落
- 中心化部署将来怎么落
- 当前存储抽象应该围绕什么边界设计

数据库主树请看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。

---

## 2. 当前默认部署

当前默认部署仍然是：

`SQLite + sqlite-vec + 本地文件系统`

典型本地目录如下：

```text
backend/data/
├─ aiteachme.db
└─ <subject>/
   ├─ raw_files/
   ├─ raw_markdowns/
   ├─ assets/
   │  └─ <file_id>/
   ├─ knowledge_markdowns/
   │  ├─ _build/
   │  ├─ manifest.json
   │  └─ .build.lock
   ├─ temp/
   └─ debug/
```

说明：

- 这些目录名来自 `utils/path_helpers.py`
- 当前代码真实目录名是复数形式
- `assets/` 是 subject 根目录，单文件资产继续按 `<file_id>/` 分桶

---

## 3. 当前数据库与文件系统的分工

### 3.1 数据库存什么

数据库负责结构化真相：

- `raw_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_node / knowledge_edge`
- `curriculum / theme_tree_node / unit_dependency`
- `question_template / exam_paper / exam_paper_item`
- `user_knowledge_state`

### 3.2 文件系统存什么

文件系统负责正文和产物：

- 原始文件
- 材料层 Markdown
- 资产文件
- 已发布知识文档正文
- staging / debug / temp

---

## 4. 当前存储表示

当前代码里已经同时存在两套表示：

### 4.1 本地绝对路径

例如 `RawFile` 中的：

- `file_path`
- `markdown_path`
- `asset_dir`

### 4.2 派生 storage key

为兼容远程 ingest / 未来对象存储，当前通过 helper 提供：

- `to_storage_key(path)`
- `resolve_storage_key_path(storage_key)`

典型 local storage key 形式：

- `<subject>/raw_files/12.pdf`
- `<subject>/raw_markdowns/12.md`
- `<subject>/assets/12/figure_001.png`
- `<subject>/knowledge_markdowns/merged_knowledge_base.md`

结论：

- 当前真实实现仍是本地路径优先
- `storage_key` 已经是未来对象存储抽象的过渡桥

---

## 5. 中心化部署目标

未来中心化部署推荐目标：

`PostgreSQL + pgvector + OSS/MinIO`

迁移时只替换底层实现，不改变业务主对象：

- 关系数据：SQLite -> PostgreSQL
- 向量：sqlite-vec -> pgvector
- 文件：本地文件系统 -> OSS / MinIO

---

## 6. 推荐存储抽象

建议围绕四个抽象层设计：

| 抽象 | 负责什么 | 本地实现 | 中心化实现 |
| --- | --- | --- | --- |
| `ArtifactStore` | 原始文件、Markdown、图片、manifest | 本地文件系统 | OSS / MinIO |
| `VectorIndex` | `retrieval_chunk` 向量读写 | sqlite-vec | pgvector |
| `BuildLock / PublishLease` | subject 级构建锁与发布锁 | 锁文件 | DB / Redis 租约 |
| `DatabaseBootstrap` | 启动建表、扩展检查 | SQLite 初始化 | PostgreSQL 初始化 |

---

## 7. 向量层说明

逻辑模型只认：

- `retrieval_chunk`
- `retrieval_chunk.embedding_model`
- `retrieval_chunk.vector_ref`

本地物理实现当前是：

- `chunk_embeddings`
- sqlite-vec 自动生成的若干影子表

这些影子表不是业务主表，不应该写回设计主树。

---

## 8. 版本与发布约束

当前数据库和存储层还必须遵守两个约束：

1. `curriculum` 是课程构建主表，不回退到多张 version 表。
2. 知识文档、知识图谱、课程结构在同一轮 digest 中共享同一版号语义。

也就是说，存储层迁移可以做，版本语义不能重新分叉。

---

## 9. 一句话结论

当前正式运行模式还是本地优先：

- DB：SQLite
- Vector：sqlite-vec
- Artifact：本地文件系统

但 `storage_key` 和统一的路径 helper 已经把未来迁移到 PostgreSQL + pgvector + OSS/MinIO 的边界预留出来了。
## 10. 知识运行时产物

- 知识文档的运行时存储现包含 `manifest.json`、`.build.lock` 和 `build_status.json`。
- `build_status.json` 记录当前或最近一次知识构建的生命周期，是本地 artifact store 契约的一部分。
- 这套运行时存储的规范实现位于 `app.utils.docgen_store`；不再保留 service 层的 shim 入口。
- 该设计不引入新的全局 `app/common` 层；共享编排继续留在 `workflows/common`，路径与存储辅助能力继续留在 `utils/`。
