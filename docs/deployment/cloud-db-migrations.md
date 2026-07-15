# 云端数据库迁移

这份文档描述 AITeachMe 在云端 Render 环境中的 PostgreSQL schema 管理方案，以及后续演进时的操作约束、验证步骤和排障办法。

当前结论很明确：

- 本地开发：SQLite，允许自动重建。
- 云端部署：PostgreSQL + pgvector，禁止应用启动时自动建表/删表/删列。
- 云端 schema 变更：统一走 Alembic migration。
- 云端运行时对象：由独立准备脚本负责，不塞回业务 migration。

## 1. 设计目标

这套方案想解决三个问题：

1. Render 新版本部署时，如果数据库没迁好，应该在切流前失败，而不是应用启动后再边跑边修。
2. Alembic autogenerate 只能当草稿，不能把 PostgreSQL 线上 DDL 交给自动生成结果直接决定。
3. 向量能力是“运行时配置驱动”的，不适合和业务表 schema 混在一个固定 migration 里。

因此当前策略是：

- 业务表：Alembic 管理。
- `retrieval_chunk.embedding vector(dim)` 与向量索引：`prepare_cloud_db.py` 管理。
- LlamaIndex `PGVectorStore` 自建表：由 LlamaIndex 初始化。
- 应用启动：只校验、不修复。

## 2. 当前文件与职责

### Alembic

- `backend/alembic.ini`
- `backend/migrations/env.py`
- `backend/migrations/versions/`

职责：

- 管理当前 SQLModel 业务表 schema。
- 记录可审计的 revision 历史。
- 提供离线 SQL 输出能力，给迁移安全检查使用。

### 云端启动保护

- `backend/app/shared/infra/database/core.py`

职责：

- local 模式继续执行 SQLite 初始化和 drift 重建。
- cloud 模式只校验：
  - Alembic revision 是否到 head
  - `vector` extension 是否存在
  - 核心业务表是否存在
  - `retrieval_chunk.embedding` 维度是否匹配当前运行时 embedding 配置

### Render pre-deploy 工具

- `backend/scripts/bootstrap_cloud_db.py`
- `backend/scripts/prepare_cloud_db.py`
- `backend/scripts/check_cloud_db.py`
- `backend/scripts/check_migration_sql.py`

职责：

- `bootstrap_cloud_db.py`：云端 pre-deploy 的单一入口，执行 Alembic upgrade、运行时对象准备和最终检查；遇到 legacy 脏库时要求显式 `--reset-db` 或 `ALLOW_CLOUD_DB_RESET=true`。
- `prepare_cloud_db.py`：创建/校验运行时对象。
- `check_cloud_db.py`：检查 DB 是否达到“可切流”状态。
- `check_migration_sql.py`：检查离线 migration SQL 中是否出现危险 DDL。

## 3. 本地与云端边界

### 本地 SQLite

本地仍然保留现在的开发便利逻辑：

- 自动创建 `data/aiteachme.db`
- 检测 schema drift
- 允许清理 legacy schema
- 必要时先把 `.db/-wal/-shm` 备份到 `data/backups/`，再删除 SQLite 文件并重建

这条路径只服务本地开发，不代表云端策略。

### 云端 PostgreSQL

云端禁止以下行为：

- 启动时 `create_all()`
- 启动时 `DROP TABLE`
- 启动时 `DROP COLUMN`
- 启动时“自动把 schema 修成当前代码样子”

原因很简单：线上 schema 不允许由应用实例在启动瞬间猜测和修正。

## 4. Render 配置

Render Native Python runtime 如果只跑纯 Python 依赖，可以配置：

```bash
# Pre-deploy command
cd backend && python scripts/bootstrap_cloud_db.py

# Start command
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Render Docker runtime 使用 `infra/deployment/docker/backend.Dockerfile` 或 `infra/deployment/docker/backend-office.Dockerfile` 时，镜像默认命令会在单副本场景下调用
`python scripts/start_cloud_app.py --host 0.0.0.0 --port ${PORT:-9020}`。多副本平台仍建议把迁移拆成独立 Job，只让 Web 容器启动 Uvicorn。

推荐环境变量：

```env
APP_MODE=cloud
DATABASE_URL=postgresql://...
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
DB_POOL_USE_LIFO=true
ALLOW_CLOUD_VECTOR_REBUILD=false
```

说明：

- `DATABASE_URL` 建议优先使用平台提供的 PgBouncer / pooled connection string；没有连接池服务时再使用 Render Postgres internal connection string。
- 应用侧连接池保持小而可控：总连接预算约等于实例数 * worker 数 * (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`)。
- 小规格数据库建议从 `DB_POOL_SIZE=3~5`、`DB_MAX_OVERFLOW=2~5` 开始，观察数据库连接数、请求延迟和排队情况后再调大。
- `ALLOW_CLOUD_VECTOR_REBUILD` 默认必须是 `false`。
- 只有在明确知道旧向量可以完全重建时，才临时改为 `true`。

GitHub Actions 的 `deploy.yml` 默认只在对应部署常量和 Secrets 齐全时执行真实部署；缺少 Cloudflare direct-upload 配置或 Sealos kubeconfig / registry 凭证时会自动跳过对应 job。后端镜像也可以通过 `build-backend-images.yml` 手动构建并推送到 GHCR。

### 4.1 Docker 部署

当前云端 ingest 已收敛到 `.pdf` / `.docx` / `.pptx` / Markdown / 文本上传：复杂 PDF/OCR 优先走 PaddleOCR 或 MinerU，本地兜底走 MarkItDown。仓库同时维护轻量后端镜像和 Office 后端镜像；Office 镜像预装 `soffice`/`libreoffice`，用于后续重新开放 `.doc`、`.ppt` 或本地 Office 转换链路。

当前仓库的后端镜像定义：

- `infra/deployment/docker/backend.Dockerfile`：轻量镜像，只安装 Python 运行依赖与后端应用本身。
- `infra/deployment/docker/backend-office.Dockerfile`：Office 镜像，额外安装 LibreOffice 与常用字体。

Render Dashboard 建议配置：

```text
Runtime / Language: Docker
Health Check Path: /api/health
```

Render Docker runtime 建议保持仓库根目录作为 Root Directory：

```text
Dockerfile Path: infra/deployment/docker/backend-office.Dockerfile
Docker Build Context Directory: .
```

Docker 模式下不需要再配置原来的 Start command，镜像默认命令已经复用：

```bash
python scripts/start_cloud_app.py --host 0.0.0.0 --port ${PORT:-9020}
```

如果 Render 已经把 Root Directory 设置为 `backend`，应改回仓库根目录；否则 Dockerfile 无法复用根目录 `.dockerignore`，也会重新出现多套部署入口问题。

如果使用 Office 镜像，部署后可在 Render Shell 或日志中确认：

```bash
which soffice
soffice --headless --version
```

注意：LibreOffice 镜像体积会明显增加。PPT/PDF 转换高峰期如果出现 OOM 或冷启动过慢，优先限制转换并发或升级实例规格，而不是在容器启动后临时安装系统包。

## 5. 业务表与运行时对象

### 5.1 业务表

由 Alembic 管理，来自当前 SQLModel metadata。

当前 head 业务 schema 覆盖：

- `user`
- `email_confirmation`
- `course`
- `raw_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_unit`
- `knowledge_edge`
- `question_template`
- `question_knowledge_unit_link`
- `exam_paper`
- `exam_paper_item`
- `exam_study_guide_cache`
- `user_knowledge_state`
- `chat_session`
- `chat_message`
- `system_runtime_settings`

用户级 settings 覆盖直接保存在 `user.runtime_settings_json`，系统 settings 快照直接保存在
`system_runtime_settings` 同一行的 `effective_settings_json / settings_hash / settings_source` 字段。
Planner 已确认构建方案保存在 `chat_session.meta_json.confirmed_plan`，不再单独建表。

### 5.2 运行时对象

以下对象不进业务 migration：

- `CREATE EXTENSION vector`
- `retrieval_chunk.embedding vector(dim)`
- `idx_retrieval_chunk_embedding`
- LlamaIndex `atm_llamaindex_rag` 相关表

原因：

- `embedding` 维度依赖当前运行时模型配置，不适合固化到一份长期不变的 migration。
- LlamaIndex 的内部表结构由第三方库拥有，业务 migration 不应接管。

## 6. 新增 migration 的标准流程

### Step 1：修改模型

先修改 SQLModel 模型。

如果新增唯一约束或索引，优先显式命名，避免不同环境命名漂移。

### Step 2：生成 Alembic 草稿

```bash
cd backend
alembic revision --autogenerate -m "简短说明"
```

注意：这是草稿，不是可直接提交的最终结果。

### Step 3：人工审查

必须重点检查：

- 是否误生成了 `server_default`
- 是否误把 JSON 改成 JSONB
- 是否把 LlamaIndex 表写进 migration
- 是否把 `retrieval_chunk.embedding` 写进 migration
- 是否出现破坏性 DDL
- 是否漏了命名约束/索引

### Step 4：跑离线 SQL 审查

```bash
cd backend
python scripts/check_migration_sql.py
```

该脚本目前会阻止以下语句直接进入升级 SQL：

- `DROP SCHEMA`
- `DROP TABLE`
- `TRUNCATE`
- `DROP COLUMN`
- `ALTER TYPE`

如果以后确实需要破坏性 DDL，应该先补备份方案、回滚方案，再显式扩展这层守卫。

数据回填 migration 也必须能在 Alembic `--sql` 离线模式下生成 SQL。不要在 migration 中依赖查询结果集迭代，例如 `.mappings()` / `.fetchall()` 后再逐行更新；这类逻辑应改成 SQL `UPDATE`、CTE 或窗口函数，必要时按 dialect 分支。

### Step 5：在临时 PostgreSQL 上验证

建议使用本地 `pgvector/pgvector` 容器或临时 Render 空库：

```bash
APP_MODE=cloud DATABASE_URL=<pg-url> python scripts/bootstrap_cloud_db.py
APP_MODE=cloud DATABASE_URL=<pg-url> python scripts/prepare_cloud_db.py
APP_MODE=cloud DATABASE_URL=<pg-url> python scripts/check_cloud_db.py
```

通常只需要跑 `bootstrap_cloud_db.py`；后两条可在排障时单独执行。至少跑两次，确认幂等性。

### Step 6：跑测试

```bash
python -m compileall app scripts
pytest
```

如果完整测试套件里存在与当前改动无关的历史失败，也至少要把迁移守卫相关测试跑过。

## 7. 向量维度变更

最需要谨慎的是 embedding 维度变化。

当前处理规则：

- 如果 `retrieval_chunk.embedding` 不存在：创建。
- 如果存在且维度相同：保持不动。
- 如果存在但维度不同：
  - 默认直接失败
  - 只有 `ALLOW_CLOUD_VECTOR_REBUILD=true` 才允许删除并重建该列与索引

这样做是为了避免一次普通部署误伤线上向量数据。

建议流程：

1. 先确认旧 embedding 可以全量重算。
2. 临时开启 `ALLOW_CLOUD_VECTOR_REBUILD=true`
3. 部署并观察 pre-deploy
4. 完成后恢复为 `false`

## 8. 启动失败时看什么

如果云端服务启动失败，优先看 Render deploy/pre-deploy 日志。

常见原因：

### 8.1 Alembic revision 不一致

表现：

- 启动时报 `alembic revision mismatch`

处理：

- 确认 pre-deploy 是否执行了 `alembic upgrade head`
- 确认 Render 实际使用的是新代码
- 确认没有多个 head 或迁移链断裂

### 8.2 vector extension 缺失

表现：

- 启动或检查脚本报 `missing PostgreSQL extension: vector`

处理：

- 确认当前 Render Postgres 支持 `pgvector`
- 确认 pre-deploy 里 `prepare_cloud_db.py` 运行成功

### 8.3 retrieval_chunk.embedding 维度不一致

表现：

- 报 `dimension mismatch`

处理：

- 如果不是预期中的模型升级，不要强行重建，先检查配置
- 如果是明确的 embedding 升级，走一次受控重建

### 8.4 LlamaIndex 表未初始化

表现：

- `check_cloud_db.py` 报 PGVectorStore 初始化失败

处理：

- 确认 `llama-index-vector-stores-postgres` 依赖存在
- 确认连接串驱动可用
- 确认数据库账户有建表/建索引权限

## 9. 当前实现的确认结果

本轮已经确认：

- Alembic head 可加载
- `alembic upgrade head --sql` 可生成离线 SQL
- SQL 安全检查通过
- 迁移守卫测试通过
- SQLite legacy 兼容测试通过
- `PGVectorStore.from_params(..., perform_setup=True)` 默认会尝试创建 schema、extension、tables、HNSW index，因此 `prepare_postgres_store()` 具备初始化其自管表的能力

本地没有完成的一项是“真 PostgreSQL 实例动态冒烟”。原因不是代码本身，而是当前机器上：

- Docker daemon 未启动
- 本地也没有 `psql`

所以这一步仍然建议在有 Docker 或直接有 Render 临时库的环境里补跑一次。

## 10. 后续改进建议

后续可以继续增强：

1. 增加 CI job，在临时 pgvector 容器上自动跑：
   - `alembic upgrade head`
   - `prepare_cloud_db.py`
   - `check_cloud_db.py`

2. 增加 migration diff 守卫：
   - 起一个临时 PG
   - 执行 head migration
   - 对当前 metadata 做 autogenerate compare
   - 要求 diff 为空

3. 给 `prepare_cloud_db.py` 增加只读 dry-run 模式，方便在生产变更前先看计划。

4. 如果未来 PG schema 复杂度继续提升，可以把“业务表迁移”和“向量运行时准备”拆成两份文档和两套 CI 校验。

## 11. 备份与回滚

当前首版按空库初始化设计。未来一旦有真实数据：

- 每次生产迁移前确认 Render PITR/逻辑备份可用，或手动执行 `pg_dump`
- 不要把“删库重来”当回滚策略
- 应优先：
  - 回滚 Render 服务版本
  - 或恢复到新 PostgreSQL 实例
  - 或从 PITR 恢复

应用启动只做校验，所以如果 schema 没迁好，Render 会让新部署失败，旧版本继续服务。这也是当前方案最重要的保护点之一。
