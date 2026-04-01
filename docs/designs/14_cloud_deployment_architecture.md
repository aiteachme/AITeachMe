# 14. 云端部署架构设计

**状态**: 设计中  
**最后更新**: 2026-04-01  
**负责人**: 系统架构

---

## 1. 概述

本文档定义 AITeachMe 的生产环境部署架构，从本地 SQLite + 文件系统迁移到云原生基础设施：

- **后端**: Render（Web Service）
- **数据库**: PostgreSQL 15+ with pgvector 扩展
- **对象存储**: 多吉云 OSS（S3 兼容）
- **向量检索**: pgvector（替换 sqlite-vec）

### 1.1 设计目标

1. **环境兼容**: 单一代码库同时支持本地开发和云端生产
2. **零数据丢失**: 从 SQLite 到 PostgreSQL 的安全迁移路径
3. **可扩展性**: 支持多用户并发和大文件上传
4. **成本优化**: 适合初创/MVP 阶段的预算约束
5. **可观测性**: 结构化日志和错误追踪

---

## 2. 架构对比

### 2.1 当前架构（本地开发）

```
┌─────────────────────────────────────────────┐
│  前端 (Vite 开发服务器)                      │
│  http://localhost:5173                      │
└─────────────────┬───────────────────────────┘
                  │ HTTP/SSE
┌─────────────────▼───────────────────────────┐
│  后端 (FastAPI + Uvicorn)                   │
│  http://localhost:8000                      │
│  ┌─────────────────────────────────────┐    │
│  │ SQLite + sqlite-vec                 │    │
│  │ data/<subject>/aiteachme.db         │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ 本地文件系统                         │    │
│  │ data/<subject>/raw_files/           │    │
│  │ data/<subject>/raw_markdowns/       │    │
│  │ data/<subject>/assets/              │    │
│  │ data/<subject>/knowledge_markdowns/ │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 2.2 目标架构（云端生产）

```
┌─────────────────────────────────────────────┐
│  前端 (Cloudflare Pages)                    │
│  https://aiteachme.pages.dev                │
└─────────────────┬───────────────────────────┘
                  │ HTTPS/SSE
┌─────────────────▼───────────────────────────┐
│  后端 (Render Web Service)                  │
│  https://aiteachme.onrender.com             │
│  ┌─────────────────────────────────────┐    │
│  │ PostgreSQL 15 + pgvector            │    │
│  │ (Render 托管数据库)                  │    │
│  │ - 连接池 (asyncpg)                   │    │
│  │ - SSL 加密                           │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │ 多吉云 OSS (S3 兼容)                 │    │
│  │ - Bucket: aiteachme-prod            │    │
│  │ - CDN 加速                           │    │
│  │ - 预签名 URL 上传                    │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

---

## 3. 数据库迁移策略

### 3.1 核心变化

#### 3.1.1 向量存储

**当前 (sqlite-vec)**:
```sql
-- 虚拟表，使用 vec0 扩展
CREATE VIRTUAL TABLE chunk_embeddings USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[1024]
);

-- 距离函数
SELECT vec_distance_cosine(e.embedding, :query_vec) as distance
FROM chunk_embeddings e;
```

**目标 (pgvector)**:
```sql
-- 启用扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 普通表，使用 vector 列类型
CREATE TABLE chunk_embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES retrieval_chunk(id) ON DELETE CASCADE,
    embedding vector(1024),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 创建索引加速相似度搜索
CREATE INDEX ON chunk_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 距离查询（<=> 是余弦距离运算符）
SELECT 1 - (e.embedding <=> :query_vec::vector) as score
FROM chunk_embeddings e;
```

#### 3.1.2 JSON 字段优化

**当前**: JSON 存储为 TEXT
```python
class KnowledgeDocument(SQLModel, table=True):
    tags: str = Field(default="[]")  # JSON 字符串
    source_file_ids: str = Field(default="[]")
```

**目标**: 原生 JSONB（可选优化，非必须）
```python
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

class KnowledgeDocument(SQLModel, table=True):
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    source_file_ids: list[int] = Field(default_factory=list, sa_column=Column(JSONB))
```

**注意**: 为了简化迁移，可以先保持 JSON 字段为字符串，后续再优化。

#### 3.1.3 Upsert 语法

**当前 (SQLite)**:
```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

stmt = sqlite_insert(UserKnowledgeState).values(...)
stmt = stmt.on_conflict_do_update(
    index_elements=["user_id", "subject"],
    index_where=sa.text("knowledge_node_id IS NULL"),  # SQLite 特有
    set_={...}
)
```

**目标 (PostgreSQL)**:
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(UserKnowledgeState).values(...)
stmt = stmt.on_conflict_do_update(
    index_elements=["user_id", "subject"],
    where=sa.text("knowledge_node_id IS NULL"),  # 注意：where 不是 index_where
    set_={...}
)
```

### 3.2 简化的迁移方案

**核心思路**: 用配置开关控制数据库类型，最小化代码改动。

#### 步骤 1: 添加数据库方言检测

```python
# app/core/database.py

def get_db_dialect() -> str:
    """获取当前数据库方言: 'sqlite' 或 'postgresql'"""
    engine = get_engine()
    return engine.dialect.name

def is_postgres() -> bool:
    """是否使用 PostgreSQL"""
    return get_db_dialect() == "postgresql"

def is_sqlite() -> bool:
    """是否使用 SQLite"""
    return get_db_dialect() == "sqlite"
```

#### 步骤 2: 向量搜索适配

```python
# app/repositories/knowledge/knowledge_repo.py

def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    """向量检索（自动适配 SQLite 和 PostgreSQL）"""
    
    from app.core.database import is_postgres
    
    if is_postgres():
        # PostgreSQL + pgvector
        query = """
            SELECT ce.chunk_id, 1 - (ce.embedding <=> :query_vec::vector) as score
            FROM chunk_embeddings ce
            JOIN retrieval_chunk c ON ce.chunk_id = c.id
            WHERE c.subject = :subject AND c.is_active = true
            ORDER BY ce.embedding <=> :query_vec::vector
            LIMIT :top_k
        """
        rows = session.execute(
            sa.text(query),
            {
                "query_vec": str(query_embedding),  # pgvector 接受字符串格式
                "subject": subject,
                "top_k": top_k,
            }
        ).fetchall()
    else:
        # SQLite + sqlite-vec（当前实现）
        query = """
            SELECT ce.chunk_id, ce.distance
            FROM chunk_embeddings ce
            WHERE ce.chunk_id IN (
                SELECT c.id FROM retrieval_chunk c
                WHERE c.subject = :subject AND c.is_active = 1
            )
            AND ce.embedding MATCH :query_embedding
            AND k = :top_k
            ORDER BY ce.distance
        """
        rows = session.execute(
            sa.text(query),
            {
                "subject": subject,
                "query_embedding": str(query_embedding),
                "top_k": top_k,
            }
        ).fetchall()
    
    # 统一处理结果
    results = []
    for row in rows:
        chunk = session.get(RetrievalChunk, row[0])
        if chunk:
            score = row[1] if is_postgres() else (1.0 / (1.0 + row[1]))
            results.append(ChunkSearchResult(chunk=chunk, score=score))
    
    return results
```

#### 步骤 3: Upsert 适配

```python
# app/repositories/profile_repo.py

def upsert_user_knowledge_state(session: Session, data: dict) -> UserKnowledgeState:
    """插入或更新用户知识状态（自动适配数据库）"""
    
    from app.core.database import is_postgres
    
    if is_postgres():
        from sqlalchemy.dialects.postgresql import insert as db_insert
        where_clause = "where"
    else:
        from sqlalchemy.dialects.sqlite import insert as db_insert
        where_clause = "index_where"
    
    stmt = db_insert(UserKnowledgeState).values(**data)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "subject"],
        **{where_clause: sa.text("knowledge_node_id IS NULL")},
        set_={k: v for k, v in data.items() if k not in ["user_id", "subject"]}
    )
    
    session.execute(stmt)
    session.commit()
    
    # 返回更新后的记录
    return session.query(UserKnowledgeState).filter_by(
        user_id=data["user_id"],
        subject=data["subject"]
    ).first()
```

---

## 4. 存储抽象层设计

### 4.1 核心接口

```python
# app/infra/storage/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

class StorageBackend(ABC):
    """存储后端抽象接口"""
    
    @abstractmethod
    async def write_file(self, key: str, content: bytes | BinaryIO) -> str:
        """写入文件，返回存储键"""
        ...
    
    @abstractmethod
    async def read_file(self, key: str) -> bytes:
        """根据存储键读取文件"""
        ...
    
    @abstractmethod
    async def delete_file(self, key: str) -> None:
        """根据存储键删除文件"""
        ...
    
    @abstractmethod
    def get_public_url(self, key: str) -> str:
        """获取文件的公开访问 URL"""
        ...
```

### 4.2 本地文件系统实现

```python
# app/infra/storage/local.py
from pathlib import Path

class LocalStorageBackend(StorageBackend):
    """本地文件系统存储（开发环境）"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    async def write_file(self, key: str, content: bytes | BinaryIO) -> str:
        file_path = self.base_dir / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(content, bytes):
            file_path.write_bytes(content)
        else:
            with file_path.open("wb") as f:
                f.write(content.read())
        
        return key
    
    async def read_file(self, key: str) -> bytes:
        file_path = self.base_dir / key
        return file_path.read_bytes()
    
    async def delete_file(self, key: str) -> None:
        file_path = self.base_dir / key
        if file_path.exists():
            file_path.unlink()
    
    def get_public_url(self, key: str) -> str:
        # 返回本地开发服务器的相对 URL
        return f"/_assets/{key}"
```

### 4.3 多吉云 OSS 实现

```python
# app/infra/storage/dogecloud.py
import boto3
from botocore.config import Config

class DogeCloudStorageBackend(StorageBackend):
    """多吉云 OSS 存储（S3 兼容）"""
    
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket: str,
        endpoint: str,
        cdn_domain: str | None = None,
    ):
        self.bucket = bucket
        self.cdn_domain = cdn_domain
        
        # 创建 S3 客户端（多吉云兼容 S3 协议）
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint,
            config=Config(signature_version="s3v4"),
        )
    
    async def write_file(self, key: str, content: bytes | BinaryIO) -> str:
        if isinstance(content, bytes):
            self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=content)
        else:
            self.s3_client.upload_fileobj(content, self.bucket, key)
        return key
    
    async def read_file(self, key: str) -> bytes:
        response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()
    
    async def delete_file(self, key: str) -> None:
        self.s3_client.delete_object(Bucket=self.bucket, Key=key)
    
    def get_public_url(self, key: str) -> str:
        if self.cdn_domain:
            # 使用 CDN 域名（推荐）
            return f"https://{self.cdn_domain}/{key}"
        else:
            # 生成临时访问 URL
            return self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=3600,
            )
```

### 4.4 存储工厂

```python
# app/infra/storage/factory.py
from app.core.config import get_settings

_storage_backend = None

def get_storage_backend() -> StorageBackend:
    """获取存储后端（单例模式）"""
    global _storage_backend
    
    if _storage_backend is None:
        settings = get_settings()
        
        if settings.storage_backend == "local":
            from app.infra.storage.local import LocalStorageBackend
            _storage_backend = LocalStorageBackend(base_dir=settings.data_dir)
        
        elif settings.storage_backend == "dogecloud":
            from app.infra.storage.dogecloud import DogeCloudStorageBackend
            _storage_backend = DogeCloudStorageBackend(
                access_key=settings.dogecloud_access_key,
                secret_key=settings.dogecloud_secret_key,
                bucket=settings.dogecloud_bucket,
                endpoint=settings.dogecloud_endpoint,
                cdn_domain=settings.dogecloud_cdn_domain,
            )
        
        else:
            raise ValueError(f"未知的存储后端: {settings.storage_backend}")
    
    return _storage_backend
```

---

## 5. 配置管理

### 5.1 环境变量配置

```bash
# .env.local (本地开发)
STORAGE_BACKEND=local
DATABASE_URL=sqlite:///./data/aiteachme.db
DATA_DIR=./data

# .env.production (生产环境 - Render)
STORAGE_BACKEND=dogecloud
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
DOGECLOUD_ACCESS_KEY=xxx
DOGECLOUD_SECRET_KEY=xxx
DOGECLOUD_BUCKET=aiteachme-prod
DOGECLOUD_ENDPOINT=https://s3-cn-south-1.dogecloud.com
DOGECLOUD_CDN_DOMAIN=cdn.aiteachme.com
```

### 5.2 配置类更新

```python
# app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 数据库配置
    database_url: str = Field(default="sqlite:///./data/aiteachme.db")
    database_pool_size: int = Field(default=10)
    database_max_overflow: int = Field(default=20)
    database_pool_timeout: int = Field(default=30)
    database_ssl_required: bool = Field(default=False)
    
    # 存储配置
    storage_backend: str = Field(default="local")  # "local" | "dogecloud"
    data_dir: Path = Field(default=Path("./data"))
    
    # 多吉云 OSS 配置
    dogecloud_access_key: str = Field(default="")
    dogecloud_secret_key: str = Field(default="")
    dogecloud_bucket: str = Field(default="")
    dogecloud_endpoint: str = Field(default="")
    dogecloud_cdn_domain: str | None = Field(default=None)
    
    # 上传配置
    max_upload_size_mb: int = Field(default=100)
    upload_chunk_size_mb: int = Field(default=5)
    presigned_url_expires_in: int = Field(default=3600)
```

---

## 6. 简化的迁移执行计划

### 6.1 阶段 1: 添加数据库方言适配（第 1 周）

**目标**: 让代码能够自动识别并适配不同的数据库类型。

**步骤**:

1. 在 `app/core/database.py` 添加方言检测函数：
   ```python
   def get_db_dialect() -> str:
       """获取当前数据库方言"""
       engine = get_engine()
       return engine.dialect.name
   
   def is_postgres() -> bool:
       return get_db_dialect() == "postgresql"
   
   def is_sqlite() -> bool:
       return get_db_dialect() == "sqlite"
   ```

2. 修改 `app/repositories/knowledge/knowledge_repo.py` 的 `vector_search()` 函数：
   - 添加 `if is_postgres()` 分支使用 pgvector 语法
   - 保留 `else` 分支使用 sqlite-vec 语法

3. 修改 `app/repositories/profile_repo.py` 的 upsert 函数：
   - 根据数据库类型选择 `sqlite_insert` 或 `pg_insert`
   - 根据数据库类型使用 `index_where` 或 `where` 参数

4. **测试**: 确保本地 SQLite 环境仍然正常工作

### 6.2 阶段 2: 本地测试 PostgreSQL（第 2 周）

**目标**: 在本地环境验证 PostgreSQL 兼容性。

**步骤**:

1. 启动本地 PostgreSQL（使用 Docker）：
   ```bash
   docker run -d \
     --name aiteachme-postgres \
     -e POSTGRES_PASSWORD=postgres \
     -e POSTGRES_DB=aiteachme \
     -p 5432:5432 \
     pgvector/pgvector:pg15
   ```

2. 安装 PostgreSQL 依赖：
   ```bash
   pip install asyncpg psycopg2-binary
   ```

3. 创建 `.env.postgres` 测试配置：
   ```bash
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aiteachme
   STORAGE_BACKEND=local
   DATA_DIR=./data
   ```

4. 初始化 PostgreSQL 数据库：
   ```bash
   # 创建表结构
   python -m app.core.database init
   
   # 启用 pgvector 扩展
   psql -h localhost -U postgres -d aiteachme -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

5. 测试基本功能：
   - 上传文件
   - 生成知识文档
   - 向量检索
   - 聊天对话

6. **如果测试通过**: PostgreSQL 适配完成 ✅

### 6.3 阶段 3: 添加存储抽象层（第 3 周）

**目标**: 让文件存储可以切换到云端 OSS。

**步骤**:

1. 创建存储抽象层目录结构：
   ```bash
   mkdir -p backend/app/infra/storage
   touch backend/app/infra/storage/__init__.py
   touch backend/app/infra/storage/base.py
   touch backend/app/infra/storage/local.py
   touch backend/app/infra/storage/dogecloud.py
   touch backend/app/infra/storage/factory.py
   ```

2. 实现 `base.py`（StorageBackend 接口）

3. 实现 `local.py`（LocalStorageBackend）

4. 实现 `factory.py`（get_storage_backend 工厂函数）

5. 修改文件操作代码使用 StorageBackend：
   - `app/workflows/ingest/runtime.py` - 文件上传和解析
   - `app/utils/path_helpers.py` - 路径处理
   - `app/api/files.py` - 文件下载

6. **测试**: 确保本地文件系统模式仍然正常工作

### 6.4 阶段 4: 集成多吉云 OSS（第 4 周）

**目标**: 在本地环境测试多吉云 OSS 存储。

**步骤**:

1. 注册多吉云账号并创建 OSS bucket：
   - 访问 https://www.dogecloud.com/
   - 创建 bucket: `aiteachme-test`
   - 获取 AccessKey 和 SecretKey

2. 安装 boto3（S3 客户端）：
   ```bash
   pip install boto3
   ```

3. 实现 `dogecloud.py`（DogeCloudStorageBackend）

4. 创建 `.env.dogecloud` 测试配置：
   ```bash
   DATABASE_URL=sqlite:///./data/aiteachme.db
   STORAGE_BACKEND=dogecloud
   DOGECLOUD_ACCESS_KEY=你的AccessKey
   DOGECLOUD_SECRET_KEY=你的SecretKey
   DOGECLOUD_BUCKET=aiteachme-test
   DOGECLOUD_ENDPOINT=https://s3-cn-south-1.dogecloud.com
   ```

5. 测试文件上传到 OSS：
   ```bash
   # 使用 dogecloud 配置启动
   export $(cat .env.dogecloud | xargs)
   uvicorn app.main:app --reload
   ```

6. 验证功能：
   - 上传文件到 OSS
   - 从 OSS 读取文件
   - 生成公开访问 URL

7. **如果测试通过**: OSS 集成完成 ✅

### 6.5 阶段 5: 生产环境部署（第 5 周）

**目标**: 部署到 Render 云平台。

**步骤**:

1. **准备 Render 账号**：
   - 注册 https://render.com/
   - 绑定 GitHub 仓库

2. **创建 PostgreSQL 数据库**：
   - 在 Render Dashboard 创建 PostgreSQL 数据库
   - 选择 Starter 套餐（$7/月）
   - 区域选择 Singapore
   - 记录数据库连接字符串

3. **启用 pgvector 扩展**：
   ```sql
   -- 在 Render 的 PostgreSQL Shell 中执行
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

4. **创建多吉云生产 bucket**：
   - 创建 bucket: `aiteachme-prod`
   - 配置 CORS 允许前端域名
   - 启用 CDN 加速（可选）

5. **创建 Web Service**：
   - 在 Render Dashboard 创建 Web Service
   - 连接 GitHub 仓库
   - 选择 Starter 套餐（$7/月）
   - 设置构建命令: `pip install -e ./backend`
   - 设置启动命令: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

6. **配置环境变量**（在 Render Web Service 设置中）：
   ```
   DATABASE_URL=<从 PostgreSQL 数据库复制>
   STORAGE_BACKEND=dogecloud
   DOGECLOUD_ACCESS_KEY=<你的 AccessKey>
   DOGECLOUD_SECRET_KEY=<你的 SecretKey>
   DOGECLOUD_BUCKET=aiteachme-prod
   DOGECLOUD_ENDPOINT=https://s3-cn-south-1.dogecloud.com
   LLM_API_KEY=<你的 LLM API Key>
   LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   LLM_MODEL=qwen-plus-latest
   ```

7. **部署后端**：
   - 点击 "Manual Deploy" 触发首次部署
   - 等待构建完成（约 5-10 分钟）
   - 检查日志确认启动成功

8. **更新前端配置**：
   - 在 Cloudflare Pages 设置中更新环境变量：
     ```
     VITE_API_URL=https://aiteachme.onrender.com
     ```
   - 重新部署前端

9. **验证生产环境**：
   - 访问前端 URL
   - 测试文件上传
   - 测试知识文档生成
   - 测试聊天功能

10. **监控和优化**：
    - 查看 Render 日志
    - 监控数据库连接数
    - 监控 OSS 流量

---

## 7. Render 部署配置

### 7.1 render.yaml（推荐方式）

在项目根目录创建 `render.yaml`：

```yaml
services:
  - type: web
    name: aiteachme-backend
    env: python
    region: singapore
    plan: starter
    buildCommand: "cd backend && pip install -e ."
    startCommand: "cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT"
    envVars:
      - key: PYTHON_VERSION
        value: "3.11"
      - key: DATABASE_URL
        fromDatabase:
          name: aiteachme-db
          property: connectionString
      - key: STORAGE_BACKEND
        value: dogecloud
      - key: DOGECLOUD_ACCESS_KEY
        sync: false  # 需要在 Render Dashboard 手动设置
      - key: DOGECLOUD_SECRET_KEY
        sync: false
      - key: DOGECLOUD_BUCKET
        value: aiteachme-prod
      - key: DOGECLOUD_ENDPOINT
        value: https://s3-cn-south-1.dogecloud.com
      - key: LLM_API_KEY
        sync: false
      - key: LLM_BASE_URL
        value: https://dashscope.aliyuncs.com/compatible-mode/v1
      - key: LLM_MODEL
        value: qwen-plus-latest
    healthCheckPath: /api/health

databases:
  - name: aiteachme-db
    databaseName: aiteachme
    plan: starter
    region: singapore
    postgresMajorVersion: 15
```

### 7.2 健康检查端点

确保 `app/api/health.py` 已实现：

```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime

router = APIRouter()

@router.get("/health")
async def health_check():
    """健康检查端点（Render 用于监控服务状态）"""
    try:
        # 检查数据库连接
        from app.core.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "database": "connected",
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
```

---

## 8. 成本估算

### 8.1 Render 费用（月）

| 服务 | 套餐 | 费用 |
|------|------|------|
| Web Service | Starter (512MB RAM) | $7 |
| PostgreSQL | Starter (1GB 存储) | $7 |
| **合计** | | **$14/月** |

### 8.2 多吉云 OSS 费用（月）

| 资源 | 单价 | 预估用量 | 费用 |
|------|------|----------|------|
| 存储 | ¥0.12/GB/月 | 10GB | ¥1.2 |
| 流量 | ¥0.15/GB | 50GB | ¥7.5 |
| 请求 | ¥0.01/万次 | 10万次 | ¥0.1 |
| **合计** | | | **¥8.8/月 (~$1.2)** |

### 8.3 总月度成本

**约 $15/月**，可支撑 100-500 用户的 MVP 阶段。

---

## 9. 监控与可观测性

### 9.1 结构化日志

确保使用结构化日志（当前项目已配置 structlog）：

```python
# app/core/logger.py
import structlog

logger = structlog.get_logger()

# 使用示例
logger.info("file_uploaded", file_id=123, size_mb=5.2, subject="math")
logger.error("vector_search_failed", subject="physics", error=str(e))
```

### 9.2 关键指标监控

在 Render Dashboard 中监控：

- **CPU 使用率**: 应 < 80%
- **内存使用率**: 应 < 80%
- **响应时间**: P95 应 < 500ms
- **错误率**: 应 < 1%
- **数据库连接数**: 应 < 连接池大小的 80%

### 9.3 告警设置（可选）

可以集成 Sentry 进行错误追踪：

```python
# app/main.py
import sentry_sdk

settings = get_settings()
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment="production",
        traces_sample_rate=0.1,
    )
```

---

## 10. 安全考虑

### 10.1 数据库安全

- ✅ PostgreSQL 连接使用 SSL/TLS 加密
- ✅ 数据库密码通过环境变量管理，不提交到代码仓库
- ✅ 启用连接池防止连接耗尽
- ✅ 定期备份（Render 自动每日备份）

### 10.2 存储安全

- ✅ OSS bucket 设置 CORS 策略，只允许前端域名访问
- ✅ 使用 CDN 加速并隐藏真实 OSS 地址
- ✅ 文件上传大小限制（默认 100MB）
- ✅ 文件类型白名单验证

### 10.3 API 安全

- ✅ 上传接口限流（防止滥用）
- ✅ 文件大小验证
- ✅ Content-Type 验证
- ✅ JWT token 过期时间设置

---

## 11. 回滚计划

如果生产部署失败：

1. **立即回滚**: 在 Render Dashboard 点击 "Rollback to previous version"
2. **数据库恢复**: 从 Render 自动备份恢复 PostgreSQL
3. **存储回滚**: OSS 文件不可变，无需回滚
4. **前端回滚**: 在 Cloudflare Pages 回滚到上一个部署版本

---

## 12. 成功指标

### 12.1 性能指标

- API 响应时间 < 500ms (P95)
- 文件上传成功率 > 99%
- 向量检索延迟 < 200ms

### 12.2 可靠性指标

- 服务可用性 > 99.5%
- 零数据丢失事件
- 数据库连接池利用率 < 80%

### 12.3 成本指标

- 月度基础设施成本 < $20
- 每用户存储成本 < $0.10

---

## 13. 下一步行动

### 立即开始（本周）

1. ✅ 已修复 vector search 的 schema bug
2. ⏳ 在 `app/core/database.py` 添加数据库方言检测函数
3. ⏳ 修改 `vector_search()` 函数支持 PostgreSQL

### 短期目标（2-3 周）

4. ⏳ 本地测试 PostgreSQL + pgvector
5. ⏳ 实现存储抽象层
6. ⏳ 本地测试多吉云 OSS

### 中期目标（1-2 个月）

7. ⏳ 注册 Render 账号并创建服务
8. ⏳ 配置生产环境变量
9. ⏳ 部署到生产环境
10. ⏳ 监控和优化

---

## 附录 A: 多吉云 OSS 配置指南

### 步骤 1: 注册和创建 Bucket

1. 访问 https://www.dogecloud.com/ 注册账号
2. 进入控制台 → 对象存储 → 创建 Bucket
3. Bucket 名称: `aiteachme-prod`（或 `aiteachme-test` 用于测试）
4. 区域选择: 华南（深圳）或就近区域
5. 访问权限: 私有（推荐）

### 步骤 2: 获取访问凭证

1. 进入控制台 → 访问控制 → AccessKey 管理
2. 创建新的 AccessKey
3. 记录 `AccessKeyId` 和 `AccessKeySecret`（只显示一次，务必保存）

### 步骤 3: 配置 CORS（允许前端上传）

在 Bucket 设置中配置 CORS 规则：

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": [
        "https://aiteachme.pages.dev",
        "http://localhost:5173"
      ],
      "AllowedMethods": ["GET", "POST", "PUT", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3600
    }
  ]
}
```

### 步骤 4: 启用 CDN 加速（可选）

1. 在 Bucket 设置中启用 CDN
2. 绑定自定义域名（如 `cdn.aiteachme.com`）
3. 配置 HTTPS 证书（Let's Encrypt 免费证书）

### 步骤 5: 测试连接

使用 Python 测试连接：

```python
import boto3

s3 = boto3.client(
    "s3",
    aws_access_key_id="你的AccessKeyId",
    aws_secret_access_key="你的AccessKeySecret",
    endpoint_url="https://s3-cn-south-1.dogecloud.com",
)

# 测试上传
s3.put_object(
    Bucket="aiteachme-test",
    Key="test.txt",
    Body=b"Hello DogeCloud!",
)

# 测试下载
response = s3.get_object(Bucket="aiteachme-test", Key="test.txt")
print(response["Body"].read())  # 输出: b'Hello DogeCloud!'
```

---

## 附录 B: PostgreSQL 本地测试指南

### 使用 Docker 启动 PostgreSQL

```bash
# 启动 PostgreSQL + pgvector
docker run -d \
  --name aiteachme-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=aiteachme \
  -p 5432:5432 \
  pgvector/pgvector:pg15

# 查看日志
docker logs -f aiteachme-postgres

# 进入 PostgreSQL Shell
docker exec -it aiteachme-postgres psql -U postgres -d aiteachme
```

### 启用 pgvector 扩展

```sql
-- 在 psql 中执行
CREATE EXTENSION IF NOT EXISTS vector;

-- 验证扩展已安装
\dx

-- 测试向量操作
SELECT '[1,2,3]'::vector <=> '[4,5,6]'::vector AS cosine_distance;
```

### 创建测试表

```sql
-- 创建向量表
CREATE TABLE test_embeddings (
    id SERIAL PRIMARY KEY,
    content TEXT,
    embedding vector(1024)
);

-- 插入测试数据
INSERT INTO test_embeddings (content, embedding)
VALUES ('test', array_fill(0.1, ARRAY[1024])::vector);

-- 测试向量检索
SELECT id, content, embedding <=> array_fill(0.1, ARRAY[1024])::vector AS distance
FROM test_embeddings
ORDER BY distance
LIMIT 5;
```

### 配置本地环境

创建 `.env.postgres` 文件：

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aiteachme
STORAGE_BACKEND=local
DATA_DIR=./data
LLM_API_KEY=你的LLM_API_KEY
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus-latest
```

启动后端：

```bash
# 加载 PostgreSQL 配置
export $(cat .env.postgres | xargs)

# 初始化数据库表
python -c "from app.core.database import init_db; init_db()"

# 启动服务
cd backend
uvicorn app.main:app --reload --port 8000
```

---

## 附录 C: 常见问题排查

### 问题 1: pgvector 扩展未安装

**症状**: 执行 SQL 时报错 `type "vector" does not exist`

**解决**:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 问题 2: 数据库连接失败

**症状**: `could not connect to server: Connection refused`

**排查**:
1. 检查 PostgreSQL 是否启动: `docker ps`
2. 检查端口是否正确: `5432`
3. 检查 DATABASE_URL 格式: `postgresql://user:pass@host:port/dbname`

### 问题 3: OSS 上传失败

**症状**: `403 Forbidden` 或 `SignatureDoesNotMatch`

**排查**:
1. 检查 AccessKey 和 SecretKey 是否正确
2. 检查 Bucket 名称是否正确
3. 检查 Endpoint 是否正确（注意区域）
4. 检查 CORS 配置是否允许前端域名

### 问题 4: Render 部署失败

**症状**: 构建或启动失败

**排查**:
1. 查看 Render 构建日志
2. 检查 `buildCommand` 和 `startCommand` 是否正确
3. 检查环境变量是否都已设置
4. 检查 Python 版本是否匹配（3.11）

### 问题 5: 向量检索返回空结果

**症状**: `vector_search()` 返回空列表

**排查**:
1. 检查 `chunk_embeddings` 表是否有数据
2. 检查 `retrieval_chunk` 表的 `is_active` 字段
3. 检查 `subject` 参数是否正确
4. 检查向量维度是否匹配（1024）

---

**文档结束**

