# 14. 云端部署架构

最后更新：2026-04-27

本文是云端部署的当前事实页。完整历史实施方案已归档到 `docs/archive/designs/14_cloud_deployment_architecture_full.md`。

## 当前目标

AITeachMe 同时支持：

- 本地模式：SQLite + 本地 ContentStore。
- 云端模式：PostgreSQL + pgvector + S3-compatible OSS + 云端鉴权。

两套模式必须保持业务语义兼容：同一套 API、同一套业务表语义、同一套 storage key 语义。

## 模式边界

| 维度 | 本地模式 | 云端模式 |
| --- | --- | --- |
| `APP_MODE` | `local` | `cloud` |
| 数据库 | SQLite，可自动初始化和本地重建 | PostgreSQL，只能通过 Alembic 迁移 |
| 文件存储 | 本地 `backend/data` | S3-compatible OSS |
| 鉴权 | 可关闭或 guest | 云端启用账号鉴权 |
| 设置页 | 可写本地 `system_runtime_settings` | 普通用户只读 |
| 演示课程 | 不读取 OSS 目录 | 读取公开 demo course catalog |

## 代码入口

| 职责 | 文件 |
| --- | --- |
| 运行模式 | `backend/app/shared/infra/runtime/` |
| 数据库初始化 | `backend/app/shared/infra/database/core.py` |
| 迁移 | `backend/migrations/` + `backend/alembic.ini` |
| 存储抽象 | `backend/app/shared/infra/storage/` |
| 设置系统 | `backend/app/workflows/support/system/` |
| 鉴权 | `backend/app/workflows/support/auth/` |
| 演示课程 | `backend/app/workflows/support/export_import/courses.py` |

## 固定规则

- 云端启动不能自动 `create_all`、删表或删列。
- 云端 schema 变化必须走 Alembic。
- 业务代码统一通过 ContentStore 访问文件，不手拼本地路径或 S3 URL。
- 对象存储 key 必须以用户和 subject 作用域组织。
- 本地与云端不做强制历史数据迁移；跨环境课程迁移走 `.atmx`。
- 演示课程只在云端模式展示，本地只保留上传导入 `.atmx`。

## 相关文档

- `11_database_and_storage_architecture.md`：数据库和 ContentStore 分工。
- `16_cloud_db_migrations.md`：云端 PostgreSQL 迁移流程。
- `15_export_import.md`：`.atmx` 和演示课程分发。
- `17_settings_config_ownership.md`：local/cloud 设置页边界。
