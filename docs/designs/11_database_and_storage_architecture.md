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
- `subject_file`
- `retrieval_chunk`
- `knowledge_document`
- `knowledge_unit / knowledge_edge`
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

## 4. 存储抽象层

### 4.1 三层架构

```text
业务代码
    ↓ 调用
ContentStore           ← 高级业务接口（key 构建 + text/JSON + work_dir）
    ↓ 委托
ArtifactStore (ABC)    ← 存储抽象接口（read/write/delete bytes）
    ↓ 实现
LocalArtifactStore     ← 本地文件系统实现
S3ArtifactStore        ← S3 兼容对象存储实现
```

### 4.2 ContentStore（业务层入口）

位置：`app/shared/infra/storage/content_store.py`

ContentStore 封装了所有文件存储业务逻辑。业务代码**不应直接检查 `is_cloud_mode`**。

**Key 构建方法**：

| 方法 | 输出示例 |
| --- | --- |
| `raw_markdown_key(subject, file_id)` | `math/raw_markdowns/42.md` |
| `asset_key(subject, file_id, name)` | `math/assets/42/img.png` |
| `asset_prefix(subject, file_id)` | `math/assets/42/` |
| `chunk_manifest_key(subject)` | `math/knowledge_markdowns/chunk_manifest.json` |
| `embedding_cache_key(subject)` | `math/cache/node_embedding_cache.json` |
| `build_status_key(subject)` | `math/knowledge_markdowns/_build/status.json` |
| `build_manifest_key(subject)` | `math/knowledge_markdowns/_build/manifest.json` |
| `knowledge_doc_key(subject, filename)` | `math/knowledge_markdowns/chapter_01.md` |
| `knowledge_build_prefix(subject)` | `math/knowledge_markdowns/_build/` |
| `subject_prefix(subject)` | `math/` |

**便捷 I/O 方法**：

| 方法 | 说明 |
| --- | --- |
| `read_text(key)` / `write_text(key, text)` | UTF-8 文本读写，缺失返回 None |
| `read_json(key, Model)` / `write_json(key, obj)` | Pydantic 模型序列化/反序列化 |
| `read_json_raw(key)` / `write_json_raw(key, data)` | 原始 dict JSON 读写 |
| `read_bytes(key)` / `write_bytes(key, data)` | 原始字节读写 |
| `exists(key)` / `delete(key)` / `delete_prefix(prefix)` | 存在性检查和删除 |
| `list_prefix(prefix)` | 列出前缀下所有 key |
| `materialize(key, temp_dir)` | 物化到本地路径（local 零拷贝） |
| `upload_dir(local_dir, prefix)` | 上传整个目录 |
| `work_dir(prefix)` | 临时工作目录上下文管理器 |
| `public_url(key)` | CDN 公共 URL（无 CDN 返回 None） |

### 4.3 ArtifactStore（存储接口）

位置：`app/shared/infra/storage/base.py`

低级别存储接口，定义 `read_bytes`、`write_bytes`、`write_file`、`delete`、`exists`、`list_prefix`、`delete_prefix`、`materialize_to_temp`。

两个实现：

- `LocalArtifactStore`：基于 `backend/data/` 本地文件系统
- `S3ArtifactStore`：基于 S3 兼容对象存储（boto3）

### 4.4 同步桥接

位置：`app/shared/infra/storage/sync_bridge.py`

`run_store_sync(coro_fn, *args, default=...)` 为同步代码提供调用异步 ArtifactStore/ContentStore 方法的桥接。

### 4.5 工厂函数

位置：`app/shared/infra/storage/__init__.py`

- `get_content_store()` — 获取 ContentStore 单例（**推荐使用**）
- `get_artifact_store()` — 获取 ArtifactStore 单例（仅低级别基础设施代码使用）
- `run_store_sync()` — 同步桥接快捷导入

---

## 5. 中心化部署目标

中心化使用：

`PostgreSQL + pgvector + S3 兼容对象存储`

迁移时只替换底层实现，不改变业务主对象：

- 关系数据：SQLite -> PostgreSQL
- 向量：sqlite-vec -> pgvector
- 文件：LocalArtifactStore -> S3ArtifactStore

ContentStore 对业务代码完全透明——同一套代码在两种模式下运行。

---

## 6. 推荐存储抽象

| 抽象 | 负责什么 | 本地实现 | 中心化实现 |
| --- | --- | --- | --- |
| `ContentStore` | 文件生命周期管理 | LocalArtifactStore | S3ArtifactStore |
| `VectorIndex` | `retrieval_chunk` 向量读写 | sqlite-vec | pgvector |
| `BuildLock` | subject 级构建锁 | 锁文件 | DB 行锁（Subject 表） |
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

1. 当前 Digest 产物以 `knowledge_document + knowledge_unit + knowledge_edge` 为准，不恢复旧课程结构表。
2. 构建 runtime / staging / debug 产物不进入业务表，只通过 ContentStore 和运行态 envelope 管理。

也就是说，存储层迁移可以做，但不能把已移除的课程结构重新写成当前主表。

---

## 9. 一句话结论

业务代码统一通过 `ContentStore` 访问文件存储，不再直接判断 `is_cloud_mode`。
底层由 `ArtifactStore` 抽象切换 local/S3，实现真正的部署透明。

## 10. 知识运行时产物

- 知识文档的运行时存储现包含 `manifest.json`、`.build.lock` 和 `build_status.json`。
- `build_status.json` 记录当前或最近一次知识构建的生命周期，统一通过 ContentStore 读写。
- 构建锁（Build Lock）使用双策略：本地模式用文件锁，云端模式用 Subject 表行锁。
  这是唯一保留 `is_cloud_mode` 判断的业务逻辑，因为两种锁机制本质不同。
- 该设计不引入新的全局 `app/common` 层；共享 workflow 编排继续收口到 `shared/infra/workflow`，路径与存储辅助能力继续留在 `utils/`。
