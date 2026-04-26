# 11. 数据库与存储架构

最后更新：2026-04-27

本文只记录数据库和文件存储的当前分工。运行目录看 `10_repo_structure_and_runtime_files.md`，云端迁移看 `16_cloud_db_migrations.md`。

## 1. 一句话

数据库保存结构化业务状态；ContentStore 保存二进制、Markdown、构建资产和可复原文件。业务代码不直接依赖本地路径或 S3 URL。

## 2. 数据库存什么

- 用户、学科、系统设置。
- 原始文件元数据和解析状态。
- 检索 chunk、知识文档、知识单元、知识边。
- 图谱同步记录和来源引用。
- 聊天、试卷、题目、掌握度、复习任务。

当前数据库结构清单以 `13_database_schema_inventory.md` 为准。

## 3. ContentStore 存什么

- 原始上传文件。
- 解析后的 Markdown。
- 解析资产目录。
- DocGen 发布文档和封面。
- 构建中间态、manifest、临时资产。

业务入口：

| 职责 | 文件 |
| --- | --- |
| ContentStore facade | `backend/app/shared/infra/storage/` |
| 本地实现 | `local_store.py` |
| S3 实现 | `s3_store.py` |
| key/scope 构建 | `paths.py` / storage scope helpers |

## 4. local/cloud 分工

| 维度 | 本地 | 云端 |
| --- | --- | --- |
| 数据库 | SQLite | PostgreSQL + pgvector |
| schema 管理 | 启动可初始化和本地重建 | Alembic 迁移 |
| 文件存储 | `backend/data` | S3-compatible OSS |
| 访问方式 | ContentStore | ContentStore |

## 5. Key 规则

Subject 级资产必须落在用户和 subject 作用域下：

```text
users/<user_id>/subjects/<subject>/
  raw_files/
  raw_markdowns/
  assets/
  knowledge_markdowns/
```

禁止业务代码手拼绝对路径、公开 URL 或绕过 ContentStore。

## 6. 派生数据原则

- 向量索引、构建中间态和临时文件是可重建资产，不作为 `.atmx` 强一致内容。
- 发布后的知识文档、封面和结构化 DB 行是用户可见资产。
- 完整环境迁移走数据库备份 + 对象存储备份；课程级迁移走 `.atmx`。

## 7. 相关文档

- `13_database_schema_inventory.md`
- `14_cloud_deployment_architecture.md`
- `15_export_import.md`
- `16_cloud_db_migrations.md`
