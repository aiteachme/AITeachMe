# 11. 部署与存储架构设计

## 1. 文档定位

本文档只讲三件事：

- 本地部署怎么落
- 中心化部署怎么落
- 存储和向量层怎么抽象

数据库主树和表职责只看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。

---

## 2. 本地部署

当前默认方案：

`SQLite + sqlite-vec + 本地文件系统`

当前本地目录在开发环境里的常见落点是：

```text
backend/data/
├─ aiteachme.db
└─ <subject>/
   ├─ raw/
   ├─ raw_markdown/
   ├─ assets/
   ├─ knowledge_markdown/
   │  ├─ _build/
   │  ├─ manifest.json
   │  └─ .build.lock
   ├─ temp/
   └─ debug/
```

说明：

- 这些目录名来自 `backend/app/services/upload_support.py`
- 这是运行时路径名，不套数据库表名规范
- 当前代码真实名字就是 `raw / raw_markdown / assets / knowledge_markdown`

本地方案的优点：

- 启动最简单
- 调试最直接
- 和当前代码最贴合

---

## 3. 中心化部署

推荐方案：

`PostgreSQL + pgvector + OSS/MinIO`

不默认推荐 `MySQL + OSS` 的原因很简单：

- 向量能力不如 PostgreSQL + pgvector 顺手
- JSON、CTE、复杂查询和后续扩展能力更弱
- 很容易被迫再外挂一个独立向量服务

中心化部署的目标不是改业务模型，而是替换底层实现：

- 关系数据进 PostgreSQL
- 文件进 OSS
- 向量进 pgvector
- 锁和发布从本地文件切换到共享租约

---

## 4. 存储抽象

建议统一成四个抽象：

| 抽象 | 负责什么 | 本地实现 | 中心化实现 |
| --- | --- | --- | --- |
| `ArtifactStore` | 原始文件、Markdown、图片、manifest | 本地文件系统 | OSS / MinIO |
| `VectorIndex` | `chunk_embedding` 的写入、删除、查询 | sqlite-vec | pgvector |
| `BuildLock / PublishLease` | subject 级构建锁和发布租约 | 锁文件 | 数据库租约 |
| `DatabaseBootstrap` | 启动时建表、扩展检查、schema 校验、开发期删库重建 | SQLite 初始化 | PostgreSQL 初始化 |

补充约束：

- 开发期默认允许直接删库重建，不为旧表做兼容迁移
- 中心化部署也不额外保留 legacy 表，只保留当前正式 schema

---

## 5. URI 统一

数据库里不应长期保存某台机器的绝对路径，目标应统一成 URI：

| 字段 | 本地示例 | 中心化示例 |
| --- | --- | --- |
| `storage_uri` | `file:///.../raw/12.pdf` | `oss://bucket/subject/raw/12.pdf` |
| `markdown_uri` | `file:///.../raw_markdown/12.md` | `oss://bucket/subject/raw_markdown/12.md` |
| `asset_root_uri` | `file:///.../assets/` | `oss://bucket/subject/assets/` |

---

## 6. 向量实现层

逻辑模型只认：

- `retrieval_chunk`
- `chunk_embedding`

本地物理实现当前是：

- SQLite 虚表 `chunk_embeddings`

需要特别说明：

- `chunk_embeddings_chunks`
- `chunk_embeddings_info`
- `chunk_embeddings_rowids`
- `chunk_embeddings_vector_chunks00`

这些都是 `sqlite-vec` 自动生成的影子表，不属于业务主表。

也就是说：

- 业务主模型里只认 `chunk_embedding`
- 数据库浏览器里看到的那串 `chunk_embeddings_*` 不要写回主树

---

## 7. 一句话结论

本地部署继续用 `SQLite + sqlite-vec + 本地文件系统`，中心化部署默认走 `PostgreSQL + pgvector + OSS/MinIO`。  
业务层只认逻辑对象，不认本地影子表和绝对路径。
