# AITeachMe 云端部署实施计划：PostgreSQL + DogeCloud OSS

## Context

AITeachMe 当前仅支持本地部署（SQLite + 本地文件系统）。需要在保持本地模式完全不变的前提下，增加云端部署支持：
- 前端：Cloudflare Pages
- 后端：Render Web Service + PostgreSQL
- 对象存储：DogeCloud OSS（S3兼容）

通过环境变量 `APP_MODE=local|cloud` 切换模式。

## 部署方案评估

**Cloudflare Pages + Render + DogeCloud 这个组合是合适的：**
- Cloudflare Pages 免费额度大，全球CDN，适合静态前端
- Render 支持 PostgreSQL + pgvector，免费tier可用于内测
- DogeCloud 提供 S3 兼容接口，国内访问快
- 作为开源项目，用户只需在各平台填环境变量即可部署，门槛低

**复杂度判断：中等偏大，但可控。** 核心改动集中在后端基础设施层，前端几乎不需要改。

---

## 阶段 1：配置层 + 抽象层

### Step 1.1 — 扩展 config.py 配置字段

**文件**: `backend/app/shared/infra/config.py`

在 `Settings` 类中新增：

```python
# ── 云端数据库 ──
database_url: str | None = None  # PostgreSQL 连接串

# ── 对象存储 (S3兼容) ──
storage_backend: str = "local"   # "local" | "s3"
s3_bucket: str | None = None
s3_endpoint: str | None = None
s3_access_key: str | None = None
s3_secret_key: str | None = None
s3_region: str | None = None
s3_public_base_url: str | None = None  # CDN域名，用于生成公开访问URL
```

新增属性：
```python
@property
def storage_is_s3(self) -> bool:
    return self.storage_backend.lower() == "s3"
```

### Step 1.2 — 新建 ArtifactStore 存储抽象

**新建目录**: `backend/app/shared/infra/storage/`

#### `backend/app/shared/infra/storage/base.py`
```python
class ArtifactStore(ABC):
    @abstractmethod
    async def read_bytes(self, storage_key: str) -> bytes: ...
    @abstractmethod
    async def write_bytes(self, storage_key: str, data: bytes) -> None: ...
    @abstractmethod
    async def write_file(self, storage_key: str, local_path: Path) -> None: ...
    @abstractmethod
    async def delete(self, storage_key: str) -> None: ...
    @abstractmethod
    async def exists(self, storage_key: str) -> bool: ...
    @abstractmethod
    async def list_prefix(self, prefix: str) -> list[str]: ...
    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int: ...
    @abstractmethod
    async def materialize_to_temp(self, storage_key: str, temp_dir: Path) -> Path: ...
    @abstractmethod
    def public_url(self, storage_key: str) -> str | None: ...
```

#### `backend/app/shared/infra/storage/local_store.py`
- 实现 `LocalArtifactStore(ArtifactStore)`
- 内部使用 `get_runtime_data_dir()` 作为根目录
- `read_bytes` → `Path.read_bytes()`
- `write_bytes` → `Path.write_bytes()`
- `write_file` → `shutil.copy2()`
- `delete` → `Path.unlink(missing_ok=True)`
- `list_prefix` → `Path.rglob("*")`
- `delete_prefix` → `shutil.rmtree()`
- `materialize_to_temp` → 直接返回本地路径（无需复制）
- `public_url` → 返回 `None`（本地通过 `/_assets` 静态挂载访问）

#### `backend/app/shared/infra/storage/s3_store.py`
- 实现 `S3ArtifactStore(ArtifactStore)`
- 使用 `boto3` S3 client（同步，用 `asyncio.to_thread` 包装）
- 初始化时从 config 读取 `s3_bucket`, `s3_endpoint`, `s3_access_key`, `s3_secret_key`, `s3_region`
- `read_bytes` → `s3.get_object()`
- `write_bytes` → `s3.put_object()`
- `write_file` → `s3.upload_file()`
- `delete` → `s3.delete_object()`
- `list_prefix` → `s3.list_objects_v2(Prefix=...)`
- `delete_prefix` → 批量 `s3.delete_objects()`
- `materialize_to_temp` → 下载到临时目录并返回 Path
- `public_url` → 拼接 `s3_public_base_url + "/" + storage_key`

#### `backend/app/shared/infra/storage/__init__.py`
```python
_store: ArtifactStore | None = None

def get_artifact_store() -> ArtifactStore:
    global _store
    if _store is None:
        settings = get_settings()
        if settings.storage_is_s3:
            _store = S3ArtifactStore(settings)
        else:
            _store = LocalArtifactStore()
    return _store
```

### Step 1.3 — 新增依赖

**文件**: `backend/pyproject.toml`

新增：
```
"psycopg[binary]>=3.1.0",
"pgvector>=0.3.0",
"boto3>=1.34.0",
```

### Step 1.4 — 验收标准

- [ ] `APP_MODE=local` 启动行为完全不变
- [ ] 新配置字段有默认值，不影响现有 `.env`
- [ ] `get_artifact_store()` 在 local 模式返回 `LocalArtifactStore`
- [ ] `LocalArtifactStore` 的行为与当前直接 Path 操作等价

---

## 阶段 2：数据库层 — PostgreSQL + pgvector

### Step 2.1 — 重构 `database/core.py` 支持双数据库

**文件**: `backend/app/shared/infra/database/core.py`

核心改动：`get_engine()` 根据 `APP_MODE` 创建不同引擎。

```python
def get_engine() -> sa.Engine:
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()

    if settings.is_cloud_mode:
        _engine = _build_postgres_engine(settings)
    else:
        _engine = _build_sqlite_engine()

    return _engine


def _build_sqlite_engine() -> sa.Engine:
    """当前 get_engine() 的逻辑原样搬入，包括 sqlite-vec 加载。"""
    db_path = _get_db_path()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    @sa.event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_conn, connection_record):
        del connection_record
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()
        _load_vec_extension(dbapi_conn)
    return engine


def _build_postgres_engine(settings) -> sa.Engine:
    """PostgreSQL 引擎，使用 psycopg 驱动。"""
    engine = create_engine(
        settings.database_url,  # postgresql+psycopg://...
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    return engine
```

### Step 2.2 — 重构 init_db() 支持双模式初始化

**文件**: `backend/app/shared/infra/database/core.py`

```python
def init_db() -> None:
    settings = get_settings()

    if settings.is_cloud_mode:
        _init_postgres_db(settings)
    else:
        _init_local_sqlite_db(settings)


def _init_local_sqlite_db(settings) -> None:
    """当前 init_db() 逻辑原样搬入。"""
    log_legacy_runtime_path_warnings()
    engine = _ensure_local_sqlite_schema(get_engine())
    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)
    _ensure_default_local_user(engine)
    logger.info("database_initialized", mode="local", ...)


def _init_postgres_db(settings) -> None:
    """PostgreSQL 初始化：建表 + 确保 pgvector 扩展。"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)
    logger.info("database_initialized", mode="cloud", ...)
```

### Step 2.3 — 新增辅助函数判断数据库方言

**文件**: `backend/app/shared/infra/database/core.py`

```python
def is_sqlite() -> bool:
    return get_engine().dialect.name == "sqlite"

def is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"
```

### Step 2.4 — 向量表：pgvector 方案

**关键区别**：
- SQLite: 每个 subject 一个 `vec0` 虚拟表 `chunk_embeddings_{slug}`
- PostgreSQL: 在 `retrieval_chunk` 表上直接加 `embedding` 列（`vector(dim)` 类型）

**文件**: `backend/app/models/knowledge.py`

在 `RetrievalChunk` 模型中新增条件列：

```python
from pgvector.sqlalchemy import Vector

class RetrievalChunk(SQLModel, table=True):
    # ... 现有字段 ...
    # 新增：仅 PostgreSQL 使用的向量列
    # 通过 SQLAlchemy Column 定义，SQLite 模式下此列不会被创建
    embedding_vector: Any = Field(
        default=None,
        sa_column=Column(Vector(1024), nullable=True)
    )
```

**但这里有兼容性问题**：SQLite 不认识 `Vector` 类型。

**更好的方案**：不在模型上加列，而是在 PostgreSQL 初始化时用 raw SQL 添加：

```python
def _init_postgres_db(settings) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)

    # 为 retrieval_chunk 添加 embedding 向量列（如果不存在）
    dim = settings.embedding_dim
    with engine.begin() as conn:
        conn.execute(sa.text(f"""
            ALTER TABLE retrieval_chunk
            ADD COLUMN IF NOT EXISTS embedding vector({dim})
        """))
        # 创建 HNSW 索引加速检索
        conn.execute(sa.text(f"""
            CREATE INDEX IF NOT EXISTS idx_retrieval_chunk_embedding
            ON retrieval_chunk
            USING hnsw (embedding vector_cosine_ops)
        """))
```

### Step 2.5 — 向量写入适配

**文件**: `backend/app/repositories/knowledge/knowledge_repo.py`

当前 `bulk_insert_embeddings()` 使用 sqlite-vec 语法。需要按方言分支：

```python
def bulk_insert_embeddings(session, chunk_ids, embeddings, subject, ...):
    if is_sqlite():
        _sqlite_insert_embeddings(session, chunk_ids, embeddings, subject, ...)
    else:
        _postgres_insert_embeddings(session, chunk_ids, embeddings)


def _sqlite_insert_embeddings(session, chunk_ids, embeddings, subject, ...):
    """当前逻辑原样保留：写入 vec0 虚拟表。"""
    # ... 现有代码 ...


def _postgres_insert_embeddings(session, chunk_ids, embeddings):
    """pgvector：直接更新 retrieval_chunk.embedding 列。"""
    for chunk_id, emb in zip(chunk_ids, embeddings):
        session.execute(
            sa.text(
                "UPDATE retrieval_chunk SET embedding = :emb WHERE id = :cid"
            ),
            {"cid": chunk_id, "emb": str(emb)},
        )
```

### Step 2.6 — 向量检索适配

**文件**: `backend/app/repositories/knowledge/knowledge_repo.py`

当前 `search_similar_chunks()` 使用 `MATCH` 语法。需要按方言分支：

```python
def search_similar_chunks(session, query_embedding, subject, top_k, ...):
    if is_sqlite():
        return _sqlite_search(session, query_embedding, subject, top_k, ...)
    else:
        return _postgres_search(session, query_embedding, subject, top_k, ...)


def _postgres_search(session, query_embedding, subject, top_k, ...):
    """pgvector 余弦相似度检索。"""
    results = session.execute(
        sa.text("""
            SELECT id, 1 - (embedding <=> :query_emb::vector) AS score
            FROM retrieval_chunk
            WHERE subject = :subject
              AND is_active = true
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_emb::vector
            LIMIT :top_k
        """),
        {
            "query_emb": str(query_embedding),
            "subject": subject,
            "top_k": top_k,
        },
    ).fetchall()
    return results
```

### Step 2.7 — 处理 SQLite 特有的 schema drift 逻辑

**文件**: `backend/app/shared/infra/database/core.py`

`_ensure_local_sqlite_schema()` 和 `_inspect_sqlite_schema_drift()` 仅在 local 模式调用，cloud 模式跳过。已在 Step 2.2 中通过 `_init_local_sqlite_db` 隔离。

### Step 2.8 — 处理 SQLite 特有的 vec 状态函数

当前 `is_vec_ready()`, `require_vec_ready()` 等函数在 cloud 模式下语义变化：
- cloud 模式下 pgvector 始终可用（初始化时已确认）
- 修改 `is_vec_ready()`:

```python
def is_vec_ready() -> bool:
    if is_postgres():
        return True  # pgvector 在 init_db 时已确认
    return bool(_vec_ready)
```

### Step 2.9 — 检查并适配 SQLite 特有 SQL

需要排查的文件：
- `backend/app/repositories/knowledge/knowledge_repo.py` — upsert 语法
- `backend/app/repositories/profile_repo.py` — 可能有 SQLite upsert
- `backend/app/shared/infra/subject_embeddings.py` — vec 表管理

**SQLite vs PostgreSQL 常见差异**：
| 操作 | SQLite | PostgreSQL |
|------|--------|------------|
| Upsert | `INSERT OR REPLACE` | `INSERT ... ON CONFLICT ... DO UPDATE` |
| Bool | `= 1` / `= 0` | `= true` / `= false` |
| 自增主键 | `INTEGER PRIMARY KEY` | `SERIAL` / `GENERATED` |
| JSON | `json_extract()` | `->` / `->>` 操作符 |

**SQLModel 的 ORM 层会自动处理大部分差异**，只有 raw SQL 需要手动适配。

### Step 2.10 — 阶段 2 验收标准

- [ ] `APP_MODE=cloud` + `DATABASE_URL=postgresql+psycopg://...` 可正常建表
- [ ] pgvector 扩展可用，向量列已创建
- [ ] 向量写入和检索在 PostgreSQL 下正常工作
- [ ] `APP_MODE=local` 行为完全不变
- [ ] 所有 raw SQL 已按方言分支处理

---

## 阶段 3：对象存储接入 — DogeCloud OSS (S3兼容)

### Step 3.1 — 改造文件上传用例

**文件**: `backend/app/workflows/support/files/commands.py`

当前流程：`temp写入 → shutil.move → 更新DB路径`

改造后流程（cloud模式）：
```
temp写入 → store.write_file(storage_key, temp_path) → 更新DB → 清理temp
```

关键改动：
```python
from app.shared.infra.storage import get_artifact_store

async def save_uploaded_file(subject, filename, content, ...):
    store = get_artifact_store()
    settings = get_settings()

    # 1. 写入临时文件（两种模式都需要，因为要计算hash等）
    temp_dir = build_temp_dir(subject)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{extension}"
    temp_path.write_bytes(content)

    # 2. 创建DB记录，获取 raw_file_id
    raw_file = _create_raw_file_record(session, subject, filename, ...)

    # 3. 构建 storage_key 并持久化
    storage_key = f"{subject}/raw_files/{raw_file.id}{extension}"

    if settings.is_cloud_mode:
        await store.write_file(storage_key, temp_path)
        raw_file.file_path = storage_key  # cloud模式下存storage_key
        temp_path.unlink(missing_ok=True)
    else:
        # local模式：原有逻辑，move到最终路径
        final_path = build_raw_file_path(subject, raw_file.id, extension)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(final_path))
        raw_file.file_path = str(final_path)

    session.commit()
```

### Step 3.2 — 改造文件读取/下载

**文件**: `backend/app/workflows/support/files/queries.py` / `commands.py`

需要新增一个统一的文件读取方法：

```python
async def read_file_bytes(raw_file: RawFile) -> bytes:
    store = get_artifact_store()
    settings = get_settings()

    if settings.is_cloud_mode:
        return await store.read_bytes(raw_file.storage_key)
    else:
        return Path(raw_file.file_path).read_bytes()
```

### Step 3.3 — 改造 Ingest 工作流文件读取

**关键文件**:
- `backend/app/workflows/ingest/fast_parse/lib/file.py` — 加载原始文件
- `backend/app/workflows/ingest/deep_enhance/lib/enhance.py` — OCR增强

Ingest 需要本地 Path 来调用解析器（markitdown, pymupdf4llm）。

**策略**：cloud模式下用 `materialize_to_temp()` 获取临时本地副本：

```python
async def load_raw_file(state, ...):
    store = get_artifact_store()
    settings = get_settings()

    if settings.is_cloud_mode:
        # 从OSS下载到临时目录
        temp_dir = build_temp_dir(state.subject)
        local_path = await store.materialize_to_temp(
            raw_file.storage_key, temp_dir
        )
    else:
        local_path = Path(raw_file.file_path)

    # 后续解析逻辑使用 local_path，不变
    ...
```

### Step 3.4 — 改造 Ingest 产物写回

Ingest 产出：`raw_markdowns/{id}.md` 和 `assets/{id}/*`

**文件**: `backend/app/workflows/ingest/fast_parse/lib/finalize.py`

```python
async def finalize_success(state, ...):
    store = get_artifact_store()
    settings = get_settings()

    # 写入 markdown
    md_storage_key = f"{state.subject}/raw_markdowns/{state.file_id}.md"
    if settings.is_cloud_mode:
        await store.write_bytes(md_storage_key, markdown_content.encode())
    else:
        md_path = build_raw_markdown_path(state.subject, state.file_id)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown_content, encoding="utf-8")

    # 写入 assets（如果有）
    if asset_files:
        for asset_path in asset_files:
            asset_key = f"{state.subject}/assets/{state.file_id}/{asset_path.name}"
            if settings.is_cloud_mode:
                await store.write_file(asset_key, asset_path)
            else:
                # local模式：assets已在解析时写入本地，无需额外操作
                pass
```

### Step 3.5 — 改造 Digest 文档发布

**关键文件**:
- `backend/app/workflows/digest/docs/publish.py` — 发布知识文档
- `backend/app/utils/docgen_store.py` — 文档构建存储工具

Digest 产出：`knowledge_markdowns/chapter_*.md`, `manifest.json`, `merged_knowledge_base.md`

**改造 docgen_store.py**：

```python
# 所有写入操作增加 store 分支
async def write_chapter(subject, chapter_index, title, content):
    store = get_artifact_store()
    settings = get_settings()
    storage_key = _chapter_storage_key(subject, chapter_index, title)

    if settings.is_cloud_mode:
        await store.write_bytes(storage_key, content.encode("utf-8"))
    else:
        path = build_knowledge_doc_path(subject, chapter_index, title)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

# 所有读取操作增加 store 分支
async def read_chapter(subject, chapter_index, title) -> str:
    store = get_artifact_store()
    settings = get_settings()

    if settings.is_cloud_mode:
        storage_key = _chapter_storage_key(subject, chapter_index, title)
        data = await store.read_bytes(storage_key)
        return data.decode("utf-8")
    else:
        path = build_knowledge_doc_path(subject, chapter_index, title)
        return path.read_text(encoding="utf-8")
```

### Step 3.6 — 改造 Subject 删除清理

**文件**: `backend/app/workflows/support/subjects/lib/deletion.py`

当前：`shutil.rmtree(subject_dir)`

改造后：
```python
async def delete_subject_artifacts(subject: str):
    store = get_artifact_store()
    settings = get_settings()

    if settings.is_cloud_mode:
        # 删除 OSS 上该 subject 的所有文件
        await store.delete_prefix(f"{subject}/")
    else:
        # 原有逻辑：删除本地目录
        subject_dir = build_subject_dir(subject)
        if subject_dir.exists():
            shutil.rmtree(subject_dir, ignore_errors=True)
```

### Step 3.7 — 改造静态文件服务

**文件**: `backend/app/main.py`

当前 `/_assets` 挂载指向本地 `data/` 目录，用于前端访问资产文件。

Cloud 模式下资产在 OSS，不需要本地静态挂载。需要新增一个代理端点或直接用 CDN URL。

**方案A（推荐）**：cloud模式下新增 API 端点代理 OSS 文件：

```python
# backend/app/api/files.py 新增
@router.get("/api/v1/assets/{storage_key:path}")
async def serve_asset(storage_key: str):
    settings = get_settings()
    if settings.is_cloud_mode:
        store = get_artifact_store()
        if store.public_url(storage_key):
            # 有CDN域名，302重定向
            return RedirectResponse(store.public_url(storage_key))
        else:
            # 无CDN，直接代理
            data = await store.read_bytes(storage_key)
            return Response(content=data, media_type=_guess_media_type(storage_key))
    else:
        # local模式：从本地读取
        path = resolve_storage_key_path(storage_key)
        return FileResponse(path)
```

**方案B**：前端直接拼接 `S3_PUBLIC_BASE_URL + storage_key` 访问 CDN。需要前端知道 CDN 域名。

**建议先用方案A**，简单可靠，后续优化再切CDN直连。

同时修改 `_register_static_mounts()`：
```python
def _register_static_mounts(app: FastAPI) -> None:
    settings = get_settings()
    if settings.is_local_mode:
        # 仅 local 模式挂载静态文件
        data_dir = get_runtime_data_dir()
        app.mount("/_assets", StaticFiles(directory=data_dir), name="runtime-assets")
```

### Step 3.8 — 改造 Export/Import

**文件**: `backend/app/workflows/support/export_import/commands.py`

Export 时读取文件：
```python
# 原来：zf.write(file_path, arcname)
# 改为：
if settings.is_cloud_mode:
    data = await store.read_bytes(storage_key)
    zf.writestr(arcname, data)
else:
    zf.write(str(local_path), arcname)
```

Import 时写入文件：
```python
# 原来：shutil.copy2(extracted_path, target_path)
# 改为：
if settings.is_cloud_mode:
    await store.write_file(storage_key, extracted_path)
else:
    shutil.copy2(str(extracted_path), str(target_path))
```

### Step 3.9 — 改造 Interact 引擎的知识文档读取

**文件**: `backend/app/workflows/interact/chat/nodes/` 相关文件

Interact 引擎在构建 prompt 时可能读取知识文档内容。需要确保读取走 store 抽象。

### Step 3.10 — 改造 build_status.json 和 .build.lock

**文件**: `backend/app/utils/path_helpers.py` 中的 `build_knowledge_build_status_path()` 和 `build_knowledge_build_lock_path()`

Cloud 模式下：
- `build_status.json` → 存入 OSS（需要持久化）
- `.build.lock` → 改用数据库行锁或简单的 DB 标记（OSS 不支持原子锁）

**建议**：在 `subject` 表中新增 `build_lock_holder` 和 `build_lock_at` 字段，cloud 模式下用 DB 行锁替代文件锁。

### Step 3.11 — 阶段 3 验收标准

- [ ] 上传文件后，文件真实进入 DogeCloud OSS
- [ ] Ingest 能从 OSS 读取原始文件并解析
- [ ] Digest 能把知识文档写入 OSS
- [ ] Subject 删除能清理对应 OSS prefix
- [ ] Export 能从 OSS 读取文件打包
- [ ] Import 能将文件写入 OSS
- [ ] Local 模式仍完全正常

---

## 阶段 4：前端 + 部署配置

### Step 4.1 — 前端改动（极少）

前端几乎不需要改动。唯一需要确认的是：

**文件**: `frontend/src/api/client.ts`

确保 `VITE_API_URL` 指向 Render 后端域名：
```
VITE_API_URL=https://aiteachme-backend.onrender.com
```

**Cloudflare Pages 环境变量**：
- `VITE_API_URL` = Render 后端 URL

**资产访问路径**：
- 当前前端通过 `/_assets/{storage_key}` 访问资产
- 如果 Step 3.7 的方案A已实现（API代理），前端无需改动
- 如果后续切CDN直连，需要前端增加一个 `VITE_ASSET_BASE_URL` 环境变量

### Step 4.2 — Render 部署配置

**Render Web Service 设置**：

Build Command:
```bash
cd backend && pip install -e .
```

Start Command:
```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Render 环境变量**（在 Dashboard 中配置）：
```bash
# 核心模式
APP_MODE=cloud

# 数据库（Render PostgreSQL 自动提供 DATABASE_URL）
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db>

# 对象存储
STORAGE_BACKEND=s3
S3_BUCKET=aiteachme-prod
S3_ENDPOINT=https://<dogecloud-s3-endpoint>
S3_ACCESS_KEY=<ak>
S3_SECRET_KEY=<sk>
S3_REGION=ap-guangzhou
S3_PUBLIC_BASE_URL=https://<cdn-domain>

# LLM
LLM_API_KEY=<key>
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus-latest
EMBEDDING_MODEL=text-embedding-v4

# 认证
AUTH_ENABLED=true
AUTH_TOKEN_SECRET=<strong-random-secret>

# SMTP（可选）
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USERNAME=<email>
SMTP_PASSWORD=<password>
SMTP_FROM_EMAIL=<email>
SMTP_USE_SSL=true

# CORS
CORS_ALLOWED_ORIGINS=https://aiteachme.cn,https://aiteachme.pages.dev
```

### Step 4.3 — Cloudflare Pages 部署配置

Build Command:
```bash
cd frontend && npm install && npm run build
```

Output Directory: `frontend/dist`

环境变量：
```bash
VITE_API_URL=https://aiteachme-backend.onrender.com
```

### Step 4.4 — DogeCloud OSS 配置

1. 创建存储桶 `aiteachme-prod`
2. 开启 S3 兼容接口
3. 获取 AccessKey / SecretKey
4. 获取 S3 Endpoint（如 `https://cos.ap-guangzhou.myqcloud.com`）
5. 可选：绑定 CDN 域名作为 `S3_PUBLIC_BASE_URL`
6. 设置 CORS 策略允许前端域名

### Step 4.5 — Render PostgreSQL 初始化

Render 创建 PostgreSQL 后：
1. 连接数据库
2. 手动执行 `CREATE EXTENSION IF NOT EXISTS vector;`
3. 验证：`SELECT extname FROM pg_extension WHERE extname = 'vector';`

> 注意：Render 免费 PostgreSQL 可能不支持 pgvector。如果不支持，需要升级到付费 plan 或使用 Supabase/Neon 等支持 pgvector 的托管服务。

### Step 4.6 — 阶段 4 验收标准

- [ ] Render 后端可正常启动
- [ ] PostgreSQL 连接正常，表已创建
- [ ] pgvector 扩展可用
- [ ] DogeCloud OSS 可读写
- [ ] Cloudflare Pages 前端可访问
- [ ] 前端能正常调用后端 API

---

## 阶段 5：端到端联调 + 生产切换

### Step 5.1 — 空环境全链路验证

从空环境开始，按顺序验证：

1. **注册/登录** — 用户创建成功，token 正常
2. **创建学科** — subject 写入 PostgreSQL
3. **上传文件** — 文件进入 DogeCloud OSS，DB 记录正确
4. **Ingest** — 从 OSS 读取文件，解析成功，markdown 写回 OSS
5. **Digest** — 知识文档生成，写入 OSS，知识图谱写入 PostgreSQL
6. **向量检索** — pgvector 检索返回合理结果
7. **Interact** — 聊天正常，能检索到知识上下文
8. **Examine** — 生成考卷，批改正常
9. **Profile** — 掌握度更新正常
10. **删除学科** — PostgreSQL 记录清除，OSS prefix 清除
11. **Export/Import** — 导出包正常，导入到新学科正常

### Step 5.2 — 常见问题排查顺序

如果联调出问题，按此顺序排查：

1. 环境变量是否完整（特别是 `DATABASE_URL` 格式）
2. PostgreSQL `vector` 扩展是否可用
3. DogeCloud S3 endpoint / credentials 是否正确
4. CORS 配置是否包含前端域名
5. `storage_key` 是否在所有链路中一致
6. workflow 中是否仍残留本地路径硬依赖

### Step 5.3 — 回滚策略

如果 cloud 模式失败：
1. Render env 中将 `APP_MODE` 改回 `local`（或直接回滚到旧版本代码）
2. 重新部署
3. 保留 PostgreSQL 和 OSS 环境用于排查

---

## 需要改动的文件清单汇总

### 必改核心文件（~15个）

| 文件 | 改动内容 |
|------|----------|
| `backend/app/shared/infra/config.py` | 新增云端配置字段 |
| `backend/app/shared/infra/database/core.py` | 双数据库引擎 + pgvector 初始化 |
| `backend/app/shared/infra/runtime/paths.py` | cloud 模式下 data_dir 处理 |
| `backend/app/utils/path_helpers.py` | 确保 storage_key 在 cloud 模式下正确 |
| `backend/app/utils/docgen_store.py` | 文档读写走 store 抽象 |
| `backend/app/models/raw_file.py` | storage_key 在 cloud 模式下的语义 |
| `backend/app/repositories/knowledge/knowledge_repo.py` | 向量写入/检索按方言分支 |
| `backend/app/workflows/support/files/commands.py` | 文件上传走 store |
| `backend/app/workflows/support/subjects/lib/deletion.py` | 删除走 store |
| `backend/app/workflows/support/export_import/commands.py` | 导出导入走 store |
| `backend/app/main.py` | 静态挂载条件化 + init_db 适配 |
| `backend/app/workflows/ingest/fast_parse/lib/file.py` | 文件加载走 store |
| `backend/app/workflows/ingest/fast_parse/lib/finalize.py` | 产物写回走 store |
| `backend/app/workflows/digest/docs/publish.py` | 文档发布走 store |
| `backend/pyproject.toml` | 新增 psycopg, pgvector, boto3 |

### 新增文件（~5个）

| 文件 | 内容 |
|------|------|
| `backend/app/shared/infra/storage/__init__.py` | get_artifact_store() 工厂 |
| `backend/app/shared/infra/storage/base.py` | ArtifactStore 抽象基类 |
| `backend/app/shared/infra/storage/local_store.py` | 本地文件系统实现 |
| `backend/app/shared/infra/storage/s3_store.py` | S3 兼容实现 |

### 可能需要适配的文件（视排查结果）

- `backend/app/shared/infra/subject_embeddings.py` — vec 表管理逻辑
- `backend/app/repositories/profile_repo.py` — 可能有 SQLite 特有 SQL
- `backend/app/workflows/digest/shared/prepare.py` — 文件读取
- `backend/app/workflows/digest/kg/support.py` — 可能读取本地文件
- `backend/app/workflows/interact/chat/nodes/` — 知识文档读取

---

## 实施顺序建议

严格按阶段顺序执行，每阶段验收通过后再进入下一阶段：

```
阶段1（配置+抽象）→ 阶段2（PostgreSQL）→ 阶段3（OSS）→ 阶段4（部署配置）→ 阶段5（联调）
```

**不要并行多个阶段。** 先让 PostgreSQL 单独可用，再接 OSS，避免两个问题叠加。

---

## .env.sample 更新

最终 `.env.sample` 应包含所有配置项的说明：

```bash
# ── 运行模式 ──
# APP_MODE=local          # local（默认）| cloud
# DATABASE_URL=           # cloud模式必填，PostgreSQL连接串
# STORAGE_BACKEND=local   # local（默认）| s3

# ── S3兼容对象存储（STORAGE_BACKEND=s3 时必填）──
# S3_BUCKET=
# S3_ENDPOINT=
# S3_ACCESS_KEY=
# S3_SECRET_KEY=
# S3_REGION=
# S3_PUBLIC_BASE_URL=     # 可选，CDN域名

# ── LLM ──
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus-latest
EMBEDDING_MODEL=text-embedding-v4

# ── 前端 ──
VITE_API_URL=http://localhost:8000
```
