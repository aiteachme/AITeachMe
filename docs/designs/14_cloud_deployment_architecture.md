# 14. Render 上中心化 PostgreSQL + DogeCloud OSS 实施方案

**状态**: 阶段 1 + 阶段 3 已完成（ContentStore 统一抽象 + OSS 接入）  
**最后更新**: 2026-04-04  
**负责人**: 系统架构

---

## 1. 文档目标

本文档用于指导后续把 AITeachMe 的云端部署补齐为：

- Render Web Service
- PostgreSQL 15+ + pgvector
- DogeCloud OSS

这份文档只解决“中心化方案如何实现”，不再把历史本地数据迁移作为首版目标。

### 1.1 重要前提

本方案固定采用以下前提：

- **本地服务** 与 **中心化服务** 是两套独立运行环境
- 本地的 `aiteachme.db`、`backend/data/` **不要求强制迁移到云端**
- 本地模式继续服务开发与调试
- 云端模式作为独立生产部署目标

因此，这次要做的不是“把旧本地库搬上云”，而是：

> 把代码改造成既能跑本地，也能跑中心化部署；  
> 并保证两套模式在数据模型、表结构语义、文件 key 语义上保持兼容互通。

### 1.2 为什么文档里同时出现 DogeCloud 和 S3

这里做一个固定区分：

- **供应商选择**: DogeCloud OSS
- **代码抽象协议**: S3-compatible storage

也就是说：

- 部署层面，当前就按 DogeCloud 来落
- 代码层面，不把业务逻辑写死为 DogeCloud SDK 语义，而是通过 S3 兼容抽象来实现

这样做的好处是：

- 当前能直接接 DogeCloud
- 后续如需换成 R2 / 阿里云 OSS / MinIO，不需要重写业务层

---

## 2. 固定决策

以下决策在本文档内视为固定：

| 主题 | 固定决策 | 说明 |
| --- | --- | --- |
| 云平台 | Render | 后端继续在 Render |
| 中心化数据库 | PostgreSQL 15+ | 优先 Render PostgreSQL |
| 向量引擎 | pgvector | 替代 sqlite-vec |
| 对象存储 | DogeCloud OSS | 代码按 S3 抽象实现 |
| 生产配置 | Render Dashboard env | 当前不强制 `render.yaml` |
| 本地开发 | 继续保留 SQLite + 本地文件系统 | 不影响现有开发 |
| 文件定位真相 | `storage_key` | 本地路径字段仅保留兼容含义 |
| 删除策略 | 首版不引入全局 `is_deleted` | 内测阶段继续硬删除 |
| 首版驱动 | `psycopg` | 不做 async ORM 重构 |
| 切换方式 | 分阶段推进 | 不一次性爆改 |
| 历史数据 | 不纳入首版强制迁移 | 如未来需要，再单独做导入工具 |

---

## 3. 本地与云端的兼容要求

虽然本地和云端是独立环境，但两边必须满足“结构兼容、语义兼容”。

### 3.1 数据库兼容

必须保证：

- 使用同一套 SQLModel 模型
- 表名一致
- 字段语义一致
- 业务主键和唯一约束语义一致
- 本地 SQLite 与云端 PostgreSQL 在业务层行为一致

不要求：

- 本地 SQLite 物理文件与 PostgreSQL 直接互转
- 首版就提供自动导库工具

### 3.2 文件与工件兼容

必须保证：

- `storage_key` 规则一致
- subject 下目录语义一致
- 文档工件命名一致
- 业务层以 `storage_key` 为核心寻址语义

不要求：

- 本地路径字段在云端继续充当真实路径
- 本地 `backend/data/` 目录直接复制到云端成为生产真相

### 3.3 API 与行为兼容

必须保证：

- 相同 API 在 local/cloud 下语义一致
- 上传、ingest、digest、interact、exams、profile 的业务结果一致
- cloud 只是底层基础设施不同，不改变上层业务契约

### 3.4 删除策略兼容

首版中心化方案不要求引入全局软删除字段，例如：

- `is_deleted`
- `deleted_at`

原因很明确：

- 当前代码库整体按硬删除设计，删除逻辑已经大量使用 `session.delete(...)` 与批量 `DELETE`
- 如果现在全局引入软删除，几乎所有查询都要补过滤条件
- 唯一约束、索引、列表页、统计口径、subject 级联删除、OSS 清理语义都会一起变复杂
- 当前中心化数据库先用于内测，这个复杂度不值得现在就背

因此本方案的固定建议是：

- 首版继续沿用硬删除
- 不在所有业务表上普遍增加 `is_deleted`
- 如后续确实需要“误删恢复”或“归档回看”，优先只在聚合根层做

聚合根优先顺序建议为：

1. `subject`
2. `raw_file`

而以下派生或级联表，首版不建议做软删除：

- `retrieval_chunk`
- `knowledge_document`
- `knowledge_node`
- `knowledge_edge`
- `curriculum`
- `theme_tree_node`
- `unit_dependency`
- `exam_paper_item`
- `chat_message`

---

## 4. 当前代码现状（2026-04-04 更新）

> **阶段 1（配置与抽象层）和阶段 3（对象存储接入）已完成。**
> 业务代码已全面切换到 ContentStore 统一抽象，不再直接判断 `is_cloud_mode`。

### 4.1 数据库现状

数据库实现位于 `app/shared/infra/database/core.py`（稳定导入面仍是 `app.shared.infra.database`）：

- `get_engine()` 已按 `APP_MODE` 自动选择 SQLite 或 PostgreSQL
- `init_db()` 已按方言初始化（SQLite + sqlite-vec / PostgreSQL + pgvector）
- 双模式启动正常

### 4.2 文件存储现状（已完成 ContentStore 重构）

存储抽象已落地，三层架构：业务代码 -> ContentStore -> ArtifactStore(ABC) -> Local/S3。

代码位置：`app/shared/infra/storage/`（含 content_store.py, base.py, local_store.py, s3_store.py, sync_bridge.py）

已完成 14 个业务文件重构，消灭 24+ 个 if/else 分支。详见 [11_database_and_storage_architecture.md](./11_database_and_storage_architecture.md)。

### 4.3 模型现状


aw_file.py 中的路径字段统一存储 storage_key 格式（如 math/raw_markdowns/42.md）。
ContentStore 提供所有 key 构建方法，业务代码不再手动拼路径。

### 4.4 已完成事项

1. ~~PostgreSQL 初始化与运行逻辑~~ - 已完成
2. ~~pgvector 写入与检索分支~~ - 已完成
3. ~~正式的 ArtifactStore~~ - 已完成
4. ~~DogeCloud 的 S3 兼容存储实现~~ - 已完成
5. ~~统一的 storage_key 驱动读写~~ - 已完成（ContentStore）
6. ~~Cloud 模式下的工件管理~~ - 已完成
7. 清晰的切换与回滚方案 - 见阶段 5

### 4.5 实际改造规模

- 修改业务文件：**14 个**
- 新增抽象文件：**6 个**（storage 目录）
- 消灭 if/else 分支：**24+**
- 总触达文件：约 **20 个**

---

## 5. 目标架构

目标架构保持简单：

```text
前端（已部署）
    ↓ HTTPS
后端（Render Web Service）
    ├── PostgreSQL 15+（Render PostgreSQL）
    │   └── pgvector
    └── DogeCloud OSS（S3 兼容）
        ├── raw_files
        ├── raw_markdowns
        ├── assets
        ├── knowledge_markdowns
        └── build artifacts
```

职责划分固定如下：

- PostgreSQL：结构化数据、外键、查询、向量索引
- DogeCloud OSS：正式文件与正式工件
- Render 本地临时磁盘：`temp/`、`debug/`、临时处理副本

### 5.1 哪些内容必须进 OSS

必须进入 OSS：

- `raw_files/`
- `raw_markdowns/`
- `assets/<file_id>/`
- `knowledge_markdowns/`
- `knowledge_markdowns/_build/`
- `manifest.json`
- `build_status.json`

不进入 OSS：

- `temp/`
- `debug/`
- 运行时临时副本

---

## 6. 分阶段实施

整个方案按 5 个阶段推进。  
规则只有一条：

> 上一阶段验收通过，才进入下一阶段。

### 6.1 分阶段实施原则

本方案之所以必须分阶段，不是为了“文档看起来更规范”，而是为了控制真实工程风险。

固定原则如下：

- 先抽象，再替换底层；不要在路径直读写仍然散落全项目时，直接接入 OSS
- 先保证 local 不坏，再新增 cloud；不要一边改基础设施，一边破坏本地开发
- 先让 PostgreSQL 单独可用，再接 OSS；不要把数据库问题和对象存储问题混成一个故障面
- 先打通空环境，再考虑未来是否需要导入历史数据；不要把“首次上线可用”和“历史数据搬迁”绑死
- 每一阶段都必须有可观测的验收结果，而不是只看代码是否“理论上能跑”

如果不按这个顺序做，最容易出现的问题是：

- PostgreSQL 问题和 OSS 问题叠在一起，定位困难
- ingest/digest 在半抽象、半本地状态下出现隐性路径 bug
- 删除逻辑在数据库删掉后，OSS 工件漏删，或者反过来先删文件后删库失败
- 本地模式被云端改造误伤，导致团队日常开发也被拖慢

---

## 7. 阶段 1：配置与抽象层落地 ✅ 已完成

### 7.1 目标

先让系统具备双模式基础：

- `local` 模式继续跑 SQLite + 本地文件系统
- `cloud` 模式具备接 PostgreSQL + DogeCloud OSS 的入口

这一阶段不切生产，也不做历史数据导入。

### 7.2 主要改动

#### 配置层

主要文件：

- [`settings.py`](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/settings/settings.py)

需要补齐的配置契约：

| 变量名 | 说明 |
| --- | --- |
| `APP_MODE` | `local` / `cloud` |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `STORAGE_BACKEND` | `local` / `s3` |
| `S3_BUCKET` | DogeCloud bucket |
| `S3_ENDPOINT` | DogeCloud S3 endpoint |
| `S3_ACCESS_KEY` | AK |
| `S3_SECRET_KEY` | SK |
| `S3_REGION` | 可选 |
| `S3_PUBLIC_BASE_URL` | 可选 CDN 域名 |

过渡策略：

- 短期可兼容 `DOGECLOUD_*`
- 规范命名统一为 `S3_*`

#### 数据库抽象

主要文件：

- [`database/core.py`](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/database/core.py)

应拆出：

- `get_db_dialect()`
- `is_sqlite()`
- `is_postgres()`
- `build_sqlite_engine()`
- `build_postgres_engine()`
- `init_local_db()`
- `init_postgres_db()`
- `ensure_sqlite_vec()`
- `ensure_pgvector()`

要求：

- `init_db()` 不能再默认等价于初始化本地 SQLite
- `cloud` 模式必须检查 PostgreSQL 与 `vector` 扩展

#### 存储抽象

新增目录：

```text
app/shared/infra/storage/
├── __init__.py
├── base.py
├── local.py
├── s3.py
└── factory.py
```

`ArtifactStore` 最低接口固定为：

```python
read_bytes(storage_key) -> bytes
write_bytes(storage_key, data) -> None
delete(storage_key) -> None
exists(storage_key) -> bool
list_prefix(prefix) -> list[str]
materialize_to_temp(storage_key) -> Path
```

### 7.3 路径与模型语义

主要涉及：

- [`path_helpers.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/utils/path_helpers.py)
- [`raw_file.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/models/raw_file.py)
- [`docgen_store.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/utils/docgen_store.py)

阶段 1 固定语义：

- `storage_key` 成为统一文件定位真相
- `file_path` / `markdown_path` / `asset_dir` 仅保留兼容语义
- `docgen_store` 升级为“基于 store 的工件 helper”

### 7.4 Render env 形态

生产 env 直接录在 Render Dashboard：

```bash
APP_MODE=cloud
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db>
STORAGE_BACKEND=s3

S3_BUCKET=aiteachme-prod
S3_ENDPOINT=https://<dogecloud-s3-endpoint>
S3_ACCESS_KEY=<access-key>
S3_SECRET_KEY=<secret-key>
S3_REGION=<optional-region>
S3_PUBLIC_BASE_URL=https://<optional-cdn-domain>

LLM_API_KEY=<key>
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus-latest
EMBEDDING_MODEL=text-embedding-v3
```

### 7.5 阶段 1 验收 ✅

- 本地模式不受影响
- 新配置项已落地
- `ArtifactStore` 抽象已存在
- PostgreSQL 分支已具备初始化入口
- 新代码不再扩散硬编码本地路径

### 7.6 阶段 1 预计触达文件

这一阶段是“立规矩”的阶段，改动不会最多，但会决定后面四个阶段是否顺畅。

必改核心文件通常包括：

- [`settings.py`](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/settings/settings.py)
- [`database/core.py`](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/database/core.py)
- [`path_helpers.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/utils/path_helpers.py)
- [`docgen_store.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/utils/docgen_store.py)
- [`raw_file.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/models/raw_file.py)

新增文件通常包括：

- `app/shared/infra/storage/__init__.py`
- `app/shared/infra/storage/base.py`
- `app/shared/infra/storage/local.py`
- `app/shared/infra/storage/s3.py`
- `app/shared/infra/storage/factory.py`

这一阶段结束后，代码应达到一个很关键的状态：

- 虽然 cloud 还没有完全打通
- 但系统已经具备“以统一抽象承接后续改造”的能力
- 后面 PostgreSQL 与 OSS 的接入不会继续把本地路径假设扩散到更多文件

---

## 8. 阶段 2：数据库接入 PostgreSQL

### 8.1 目标

让 cloud 模式正式使用 PostgreSQL + pgvector。

### 8.2 Render 侧准备

在 Render 创建 PostgreSQL，并执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

### 8.3 主要改动

主要涉及：

- [`database/core.py`](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/database/core.py)
- [`knowledge_repo.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/repositories/knowledge/knowledge_repo.py)
- [`profile.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/models/profile.py)

固定要求：

- 使用同步 `psycopg`
- 检索逻辑按 dialect 分支
- 不引入 async ORM 重构

### 8.4 向量策略

固定策略：

- PostgreSQL 使用 `pgvector`
- 首版只需要支持“云端数据写入后可正常建向量并查询”
- 不要求兼容搬运 `sqlite-vec` 物理表

### 8.5 阶段 2 验收

- PostgreSQL 可建表
- `vector` 扩展可用
- 检索链路可在 PostgreSQL 下运行
- local/cloud 两种模式都能正常启动

### 8.6 阶段 2 预计触达文件

这一阶段的重点不是普通 CRUD，而是把“SQLite 专属假设”收敛掉。

高优先级文件通常包括：

- [`database/core.py`](/c:/Project/Project0GIT/aiteachme/AiTeachMe-main/backend/app/shared/infra/database/core.py)
- [`knowledge_repo.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/repositories/knowledge/knowledge_repo.py)
- [`profile_repo.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/repositories/profile_repo.py)
- [`profile.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/models/profile.py)
- [`main.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/main.py)

需要重点复核的内容包括：

- SQLite 专属 upsert 写法是否需要 PostgreSQL 分支
- `sqlite_where` 这类方言相关索引定义是否需要补 PostgreSQL 等价语义
- 向量表、向量列、向量查询语法是否已完全切到 `pgvector`
- 启动初始化过程是否已从“默认本地 SQLite”变成“按当前方言初始化”

这一阶段的工程特点是：

- 文件数不会像阶段 3 那么多
- 但数据库语义出错的代价更大
- 因此必须配套最小化验证，而不是只看服务能否启动

---

## 9. 阶段 3：对象存储接入 DogeCloud OSS ✅ 已完成

### 9.1 目标

让 cloud 模式下的正式文件与正式工件进入 DogeCloud OSS。

### 9.2 供应商与抽象关系

这一阶段固定采用：

- 供应商：DogeCloud OSS
- 代码实现：`S3ArtifactStore`
- 环境变量命名：`S3_*`

禁止把 DogeCloud 细节写死进业务层；  
只允许出现在：

- env 值
- endpoint 配置
- 部署文档

### 9.3 主要改动

主要涉及：

- [`workflows/support/files/uploads.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/support/files/uploads.py)
- [`workflows/support/subjects/lib/deletion.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/support/subjects/lib/deletion.py)
- ingest workflow 相关文件
- digest docs publish 相关文件
- [`docgen_store.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/utils/docgen_store.py)

固定策略：

- 正式文件写 OSS
- 临时文件仍落本地临时目录
- 需要 `Path` 的地方通过 `materialize_to_temp()`
- 删除 subject 时同时清 PostgreSQL 数据与 OSS prefix

### 9.4 阶段 3 验收 ✅

- ✅ ContentStore 12 项功能测试通过
- ✅ 全部 14 个业务模块 import 验证通过
- ✅ local 模式不受影响
- ⬜ cloud 模式端到端冒烟测试（待阶段 4 联调时执行）

### 9.5 阶段 3 预计触达文件

这一阶段通常是**改动面最大**的一阶段，因为它会真正碰到 ingest、digest、文件服务、删除清理等多条链路。

高优先级文件通常包括：

- [`workflows/support/files/uploads.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/support/files/uploads.py)
- [`workflows/support/subjects/lib/deletion.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/support/subjects/lib/deletion.py)
- [`docgen_store.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/utils/docgen_store.py)
- [`graph.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/ingest/fast_parse/graph.py)
- [`file.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/ingest/fast_parse/lib/file.py)
- [`enhance.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/ingest/fast_parse/lib/enhance.py)
- [`finalize.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/ingest/fast_parse/lib/finalize.py)
- [`publish.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/digest/docs/publish.py)
- [`prepare.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/digest/common/prepare.py)
- [`support.py`](/c:/Project/Project1GIT/AITeachMe1/backend/app/workflows/digest/kg/support.py)

这一步需要特别注意两类代码：

- 直接 `Path(...).read_text()` / `read_bytes()` / `write_text()` 的位置
- 默认认为 `raw_file.file_path`、`markdown_path`、`asset_dir` 一定指向本地可访问路径的代码

合理的落地方式不是强行把所有解析器改成“原生支持 OSS 流”，而是：

- 正式文件长期存 OSS
- 运行时需要本地路径的解析器，通过 `materialize_to_temp()` 获取临时副本
- 解析结束后再把正式产物通过 store 层回写

这样做虽然不是理论上最极致的“全流式对象存储”，但对当前项目最稳，也最容易落地。

---

## 10. 阶段 4：云端初始化与联调

### 10.1 目标

这一阶段不做“历史数据迁移”，只做：

- 新云环境初始化
- 新云环境端到端联调
- 验证 local/cloud 结构兼容

### 10.2 验证方式

在 cloud 模式下，从空环境开始验证以下能力：

1. 创建学科
2. 上传新文件
3. 完成 ingest
4. 完成 digest
5. 完成 interact
6. 完成 exams / profile 基本链路
7. 删除学科并清理 OSS 工件

### 10.3 需要确认的兼容点

必须确认：

- 表结构语义与本地模式一致
- 唯一约束与索引语义一致
- `storage_key` 规则一致
- 工件命名一致
- 上层 API 行为一致

### 10.4 如未来要做数据导入

如后续真要把本地 `aiteachme.db` 或 `backend/data/` 导入云端，应作为**独立专题**处理，而不是本方案的首版阻塞项。  
也就是说：

- 可以未来再写导入工具
- 但当前不把它作为必须交付物

### 10.5 阶段 4 验收

- 云端空环境可独立完成全链路
- 本地与云端结构语义兼容
- 不依赖历史本地数据也能正常运行

### 10.6 联调检查清单

阶段 4 的目标不是“看服务活着”，而是确认中心化模式真的可用。

联调时至少要覆盖：

- 学科创建是否成功写入 PostgreSQL
- 上传文件后，DB 记录与 OSS 对象是否都存在
- ingest 是否能正确读取原始文件、生成 markdown、登记资产
- digest 是否能写出知识文档与运行时工件
- interact 是否能在 PostgreSQL 检索链路下拿到合理上下文
- exams / profile 是否没有被数据库方言切换误伤
- 删除学科后，数据库记录与 OSS prefix 是否同步清理

如果这一阶段出现问题，优先排查顺序建议为：

1. env 配置是否完整
2. PostgreSQL `vector` 扩展是否可用
3. `storage_key` 是否稳定
4. store 层读写是否正确
5. workflow 中是否仍残留本地路径硬依赖

---

## 11. 阶段 5：生产切换与回滚

### 11.1 切换前条件

必须全部满足：

- PostgreSQL 已验证
- DogeCloud OSS 已验证
- Cloud 模式代码已稳定
- 空环境联调已通过
- 冒烟测试清单已通过

### 11.2 切换步骤

固定顺序：

1. 在 Render Dashboard 配好 cloud 模式 env
2. Manual Deploy 新后端
3. 运行冒烟验证
4. 确认前端访问正常
5. 正式切生产流量

由于本地与云端独立，不需要做“最后一次本地数据增量迁移”。

### 11.3 前端是否需要改动

只有后端域名变化时才需要改：

```bash
VITE_API_URL=https://<backend-domain>
```

### 11.4 回滚策略

如果 cloud 模式失败：

1. Render env 切回旧模式
2. 重新部署旧版本
3. 保留 PostgreSQL 与 OSS 环境用于排查

回滚目标是恢复服务，不是销毁新环境。

---

## 12. Agent 实施顺序

为保证 agent 可稳定执行，顺序固定为：

1. 阶段 1：配置与抽象层
2. 阶段 2：PostgreSQL
3. 阶段 3：DogeCloud OSS
4. 阶段 4：云端空环境联调
5. 阶段 5：生产切换

### 12.1 禁止事项

首版禁止做以下事情：

- 不要同时引入 async ORM 重构
- 不要把 DogeCloud 细节写死进业务层
- 不要把 `temp/`、`debug/` 强行中心化
- 不要把“历史数据迁移”塞进首版阻塞项
- 不要在阶段 1 未完成前直接切 Render 生产 env

### 12.2 改动规模与工期预估

按当前代码现状，这次改造的工程量可以保守估计为“单人连续开发下的 `2-3` 周级别任务”。

更细一点的拆分如下：

| 阶段 | 主要内容 | 粗略工期 |
| --- | --- | --- |
| 阶段 1 | 配置、数据库抽象、存储抽象、`storage_key` 语义收敛 | `3-4` 个工作日 |
| 阶段 2 | PostgreSQL + `pgvector` 接入、数据库方言适配 | `3-5` 个工作日 |
| 阶段 3 | DogeCloud OSS 接入、ingest/digest/store 适配 | `4-6` 个工作日 |
| 阶段 4 | Render 云端空环境联调、冒烟、问题修补 | `2-3` 个工作日 |
| 阶段 5 | 正式切换、回滚预案确认、发布窗口执行 | `1` 个工作日 |

综合来看：

- 理想顺利情况下：约 `10-12` 个工作日
- 稳妥估计情况下：约 `13-19` 个工作日

其中最容易额外吃时间的地方通常是：

- PostgreSQL 与 SQLite 在索引、upsert、约束语义上的差异
- ingest 链路里仍残留的本地路径假设
- DogeCloud S3 兼容细节与 SDK 参数校准
- Render 云端联调时暴露出的环境变量或权限问题

如果由 agent 按文档分阶段执行，这个工期可以明显更可控；  
但前提是每一阶段都先完成验收，而不是把 1-5 阶段并行乱改。

### 12.3 文件改动规模预估

按当前代码触点判断，比较合理的文件规模预估是：

- 必改核心文件：约 `10-15` 个
- 新增抽象与适配文件：约 `4-6` 个
- 连同联动适配、测试、联调辅助后：总触达约 `20-30` 个文件

需要明确的是：

- 这里的“大部分改动”发生在 backend
- frontend 不会成为这次中心化改造的主战场
- 真正最重的链路是 ingest / digest / subject 删除，不是普通接口层

---

## 13. 总体验收

最终认为“中心化方案落地”，必须满足：

- 本地模式仍正常
- 云端模式可独立运行
- PostgreSQL 成为云端正式数据库
- DogeCloud OSS 成为云端正式文件真相
- `storage_key` 成为统一文件定位语义
- 上传、ingest、digest、interact、exams、profile、subject 删除全链路通过
- Render 上 env 已稳定托管

---

## 14. 一句话结论

后续实现时，应把 DogeCloud 视为**当前选定的 OSS 供应商**，把 S3 视为**代码层存储抽象协议**；  
同时明确：**本地与云端是独立环境，不做强制历史迁移，只要求结构与语义兼容。**

---

**文档结束**
