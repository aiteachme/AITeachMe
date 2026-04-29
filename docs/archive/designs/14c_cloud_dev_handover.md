# 云端部署改造 — 开发交接文档

> 本文档供后续开发者（或 AI agent）接手继续改造使用。
> 最后更新：2026-04-04

---

## 一、改造目标

在保持本地模式（SQLite + 本地文件系统）完全不变的前提下，增加云端部署支持：
- 前端：Cloudflare Pages
- 后端：Render Web Service + PostgreSQL + pgvector
- 对象存储：DogeCloud OSS（通过 S3 兼容协议）
- 通过环境变量 `APP_MODE=local|cloud` 切换模式

完整的5阶段实施计划见：`docs/designs/16_cloud_implementation_plan.md`

---

## 二、当前进度

### ✅ 阶段1：配置层 + 存储抽象层（100% 完成）

| 文件 | 改动内容 |
|------|----------|
| `backend/app/shared/infra/settings/settings.py` | 新增 `database_url`, `storage_backend`, `s3_bucket`, `s3_endpoint`, `s3_access_key`, `s3_secret_key`, `s3_region`, `s3_public_base_url` 字段；新增 `storage_is_s3` 属性 |
| `backend/app/shared/infra/storage/__init__.py` | **新建** — `get_artifact_store()` 工厂，全局单例 |
| `backend/app/shared/infra/storage/base.py` | **新建** — `ArtifactStore` 抽象基类 |
| `backend/app/shared/infra/storage/local_store.py` | **新建** — `LocalArtifactStore` 本地实现 |
| `backend/app/shared/infra/storage/s3_store.py` | **新建** — `S3ArtifactStore` S3兼容实现（boto3 + asyncio.to_thread） |
| `backend/pyproject.toml` | 新增依赖：`psycopg[binary]>=3.1.0`, `pgvector>=0.3.0`, `boto3>=1.34.0` |

### ✅ 阶段2：数据库层 PostgreSQL + pgvector（100% 完成）

| 文件 | 改动内容 |
|------|----------|
| `backend/app/shared/infra/database/core.py` | `get_engine()` 按 `APP_MODE` 分支创建 SQLite/PostgreSQL 引擎（`_build_sqlite_engine` / `_build_postgres_engine`）；`init_db()` 拆分为 `_init_local_sqlite_db()` + `_init_postgres_db()`；新增 `is_sqlite()`, `is_postgres()` 辅助函数；`is_vec_ready()` 在 PostgreSQL 下始终返回 True；`_init_postgres_db()` 自动创建 pgvector 扩展、`retrieval_chunk.embedding` 向量列和 HNSW 索引 |
| `backend/app/repositories/knowledge/knowledge_repo.py` | `bulk_insert_embeddings()` 拆分为 `_pg_bulk_insert_embeddings()` + `_sqlite_bulk_insert_embeddings()`；`vector_search()` 拆分为 `_pg_vector_search()`（余弦相似度 `<=>` 操作符）+ `_sqlite_vector_search()`（`MATCH` 操作符）；`delete_embeddings_by_chunk_ids()` PostgreSQL 分支将 embedding 列置 NULL |
| `backend/app/repositories/profile_repo.py` | `upsert_knowledge_state()` 从硬编码 `sqlite_insert` 改为按 `is_postgres()` 分支使用 `pg_insert` / `sqlite_insert` |

### 🔧 阶段3：对象存储接入（约 30% 完成）

**已完成的文件：**

| 文件 | 改动内容 |
|------|----------|
| `backend/app/workflows/ingest/intake/uploads.py` | `save_uploaded_file()` 已添加 cloud 分支（上传到 OSS，file_path 存 storage_key）；`delete_files()` 已改为 async 并添加 cloud 分支（从 OSS 删除）；`_read_markdown()` cloud 模式返回空串；已导入 `get_artifact_store` |
| `backend/app/workflows/support/courses/lib/deletion.py` | `delete_course_with_all_content()` cloud 模式跳过本地目录删除；新增 `delete_course_artifacts_async()` 异步删除 OSS prefix |
| `backend/app/main.py` | `_register_static_mounts()` 仅在 local 模式挂载 `/_assets` 静态文件 |

**未完成的文件（阶段3剩余工作）：**

见下方第三节。

### ⬜ 阶段4：前端 + 部署配置（未开始）
### ⬜ 阶段5：端到端联调（未开始）

---

## 三、阶段3 剩余工作详解

这是改动面最大的阶段。核心思路：所有直接操作本地文件系统的代码，在 cloud 模式下改为通过 `ArtifactStore` 抽象。

### 3.1 需要注意的 async 问题

`delete_files()` 已改为 `async def`，但它的调用方（API 层）可能还是同步调用。需要检查 `backend/app/api/files.py` 中调用 `delete_files` 的地方，确保用 `await` 调用。

同样，`delete_course_artifacts_async()` 是新增的 async 函数，需要在 course 删除的 API 端点中调用。检查 `backend/app/api/courses.py`。

### 3.2 改造 Ingest 工作流（未开始）

**需要改的文件和改法：**

1. **`backend/app/workflows/ingest/fast_parse/lib/file.py`** — 加载原始文件
   - 找到读取 `raw_file.file_path` 的地方
   - cloud 模式下用 `store.materialize_to_temp(raw_file.file_path, temp_dir)` 获取本地副本
   - 解析器（markitdown, pymupdf4llm）需要本地 Path，所以必须先下载

2. **`backend/app/workflows/ingest/fast_parse/lib/finalize.py`** — 写回解析产物
   - 找到写入 markdown 和 assets 的地方
   - cloud 模式下用 `store.write_bytes()` 写 markdown，`store.write_file()` 写 assets

3. **`backend/app/workflows/ingest/fast_parse/lib/enhance.py`** — 后台 OCR 增强
   - 同样需要 `materialize_to_temp()` 获取本地副本

**改造模式统一为：**
```python
from app.shared.infra.settings import get_settings
from app.shared.infra.storage import get_artifact_store

settings = get_settings()
store = get_artifact_store()

if settings.is_cloud_mode:
    local_path = await store.materialize_to_temp(storage_key, temp_dir)
else:
    local_path = Path(raw_file.file_path)
```

### 3.3 改造 Digest 文档发布（未开始）

1. **`backend/app/utils/docgen_store.py`** — 文档构建存储工具
   - 所有 `Path.write_text()` / `Path.read_text()` 改为 store 抽象
   - 包括 chapter 写入、manifest.json 写入、merged_knowledge_base.md 写入

2. **`backend/app/workflows/digest/docs/publish.py`** — 发布知识文档
   - 发布产物写入走 store

3. **`backend/app/workflows/digest/common/prepare.py`** — 准备阶段
   - 读取 raw_markdowns 走 store

### 3.4 改造 Export/Import（未开始）

**`backend/app/workflows/support/export_import/exports.py`**

- Export 时读取文件：cloud 模式用 `store.read_bytes(storage_key)` + `zf.writestr(arcname, data)`
- Import 时写入文件：cloud 模式用 `store.write_file(storage_key, extracted_path)`

### 3.5 新增资产代理端点（未开始）

**`backend/app/api/files.py`** — 新增：

```python
from fastapi.responses import RedirectResponse, Response, FileResponse

@router.get("/api/v1/assets/{storage_key:path}")
async def serve_asset(storage_key: str):
    settings = get_settings()
    if settings.is_cloud_mode:
        store = get_artifact_store()
        url = store.public_url(storage_key)
        if url:
            return RedirectResponse(url)
        data = await store.read_bytes(storage_key)
        return Response(content=data)
    else:
        from app.utils.path_helpers import resolve_storage_key_path
        path = resolve_storage_key_path(storage_key)
        return FileResponse(path)
```

### 3.6 改造 build lock（未开始）

Cloud 模式下 `.build.lock` 文件锁不可用（OSS 不支持原子锁）。

建议在 `backend/app/models/course.py` 的 `Course` 模型中新增：
```python
build_lock_holder: str | None = None
build_lock_at: datetime | None = None
```

然后在 digest 构建流程中，cloud 模式用 DB 行锁替代文件锁。

---

## 四、如何找到所有需要改的文件

```bash
cd backend/app

# 找所有直接读写文件的地方
grep -rn "\.read_text\|\.read_bytes\|\.write_text\|\.write_bytes\|shutil\.\|Path(" \
  workflows/ utils/docgen_store.py --include="*.py" | grep -v "__pycache__"

# 找所有引用 file_path/markdown_path/asset_dir 的地方
grep -rn "file_path\|markdown_path\|asset_dir" \
  workflows/ repositories/ --include="*.py" | grep -v "__pycache__"
```

---

## 五、关键设计约束（必须遵循）

1. **local 模式必须完全不受影响** — 所有改动都通过 `settings.is_cloud_mode` 或 `is_postgres()` 分支
2. **storage_key 是统一文件定位语义** — 上传文件使用 `{file_uid}__{safe_stem}` 目录，不使用裸自增 id 命名
3. **不做 async ORM 重构** — PostgreSQL 用同步 psycopg
4. **DogeCloud 细节不写进业务层** — 只出现在 env 值和 `s3_store.py`
5. **temp/ 和 debug/ 不进 OSS** — 始终用本地临时目录
6. **解析器需要本地 Path** — cloud 模式通过 `materialize_to_temp()` 下载临时副本
7. **首版不引入全局软删除** — 继续硬删除
8. **不做历史数据迁移** — 云端从空环境开始

---

## 六、ArtifactStore 接口速查

```python
from app.shared.infra.storage import get_artifact_store

store = get_artifact_store()

await store.read_bytes("course/raw_files/1.pdf")       # 读取文件
await store.write_bytes("course/raw_markdowns/1.md", data)  # 写入文件
await store.write_file("course/raw_files/1.pdf", local_path)  # 上传本地文件
await store.delete("course/raw_files/1.pdf")            # 删除文件
await store.exists("course/raw_files/1.pdf")            # 检查存在
await store.list_prefix("course/")                      # 列出前缀下所有文件
await store.delete_prefix("course/")                    # 删除前缀下所有文件
await store.materialize_to_temp("course/raw_files/1.pdf", temp_dir)  # 下载到临时目录
store.public_url("course/raw_files/1.pdf")              # CDN URL（可能为 None）
```

---

## 七、数据库方言判断速查

```python
from app.shared.infra.database import is_sqlite, is_postgres

if is_postgres():
    # PostgreSQL 特有逻辑
else:
    # SQLite 特有逻辑
```

---

## 八、相关文档索引

| 文档 | 位置 | 内容 |
|------|------|------|
| 5阶段实施计划 | `docs/designs/16_cloud_implementation_plan.md` | 完整的分阶段实施方案，含代码示例和验收标准 |
| 原始架构设计 | `docs/designs/14_cloud_deployment_architecture.md` | 云端部署架构设计，含固定决策和兼容要求 |
| 数据库架构 | `docs/designs/11_database_and_storage_architecture.md` | 当前数据库和存储架构 |
| 数据库 Schema | `docs/designs/13_database_schema_inventory.md` | 完整的18张表 Schema |
| Export/Import | `docs/designs/15_export_import.md` | 导出导入功能设计 |
