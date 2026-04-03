# 10. 仓库结构与运行时文件

## 1. 文档定位

本文档只回答两件事：

- 现在应该按什么顺序读仓库
- 运行时文件到底怎么落盘

数据库表职责请看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。

---

## 2. 推荐阅读顺序

后端主顺序：

`api → services → workflows → infra → core`（辅助层：`utils` / `repositories` / `models` / `schemas`）

原因：

- `api` 告诉你对外资源长什么样
- `services` 告诉你请求怎么被转成用例
- `workflows` 告诉你复杂流程真实怎么跑
- `infra` 告诉你 AI 引擎（LLM / 搜索 / 记忆 / 工具）怎么封装
- `core` 告诉你应用基础设施怎么启动
- `repositories/models` 告诉你数据最终怎么落
- `utils` 是各层共用的纯工具函数，可被任何层引用

---

## 3. 顶层目录

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 页面、组件、前端 API |
| `backend/` | FastAPI、workflow、repository、model |
| `docs/` | 设计文档 |
| `backend/scripts/` | 工具脚本与辅助脚本 |
| `backend/skills/` | 教学技能定义 |
| `backend/tools/` | 工具配置 YAML |

---

## 4. 后端核心目录

`backend/app/` 当前核心目录为：

| 目录 | 作用 |
| --- | --- |
| `api/` | HTTP 资源入口 |
| `services/` | 用例入口与结果封装 |
| `workflows/` | 五大引擎编排中心 |
| `repositories/` | 查询与持久化帮助 |
| `models/` | 业务表模型 |
| `schemas/` | API 请求 / 响应模型 |
| `core/` | 应用基础设施（config, database, exceptions, logger, runtime_paths） |
| `infra/` | AI 平台引擎（LLM, embedding, agent, tools, search, memory, guardrails 等） |
| `utils/` | 纯工具函数（path_helpers, presenters, time, subject, job_helpers, kg_helpers） |

### 4.1 分层依赖规则

```text
┌────────────────────────────────────────────────┐
│  api/          ← HTTP 入口                     │
│    ↓                                           │
│  services/     ← 业务编排                      │
│    ↓                                           │
│  workflows/    ← 引擎编排                      │
│    ↓                                           │
│  infra/        ← AI 引擎                       │
│    ↓                                           │
│  core/         ← 应用基础设施                   │
│                                                │
│  utils/        ← 纯工具（可被任何层引用）        │
│  models/       ← 数据模型（可被 repos 以上引用） │
│  schemas/      ← API 模型（仅 api/services 引用）│
│  repositories/ ← 持久化（仅 services 以上引用）  │
└────────────────────────────────────────────────┘
```

**核心规则**：
- 上层可以 import 下层，反之 **不可**
- `utils/` 是横切层，只依赖 `core/`，不依赖任何业务层
- `infra/` 可以 import `core/`，**不可** import `services/` 或 `workflows/`
- `models/` 只依赖 `core/` 和 `utils/`，**不可** import `services/` 或更上层

其中最需要优先读的是 `workflows/`，因为复杂主链路已经正式迁到这里。

---

## 5. 当前数据根目录

默认数据根目录来自 `get_settings().data_dir`。

在当前仓库的常见落点是：

`backend/data/`

其中：

- `backend/data/aiteachme.db` 是主 SQLite 数据库
- 每个 `subject` 都有自己的运行时目录

---

## 6. Subject 目录真实布局

当前真实目录由 `backend/app/utils/path_helpers.py` 定义：

```text
backend/data/<subject>/
├─ raw_files/
├─ raw_markdowns/
├─ assets/
│  └─ <file_id>/
├─ knowledge_markdowns/
│  └─ _build/
├─ temp/
└─ debug/
```

目录职责：

| 目录 | 作用 |
| --- | --- |
| `raw_files/` | 原始上传文件 |
| `raw_markdowns/` | ingest 产出的材料层 Markdown |
| `assets/<file_id>/` | 单文件图片与附件资产 |
| `knowledge_markdowns/` | 已发布知识文档 |
| `knowledge_markdowns/_build/` | 知识文档 staging 与中间产物 |
| `temp/` | 临时文件 |
| `debug/` | workflow 调试快照 |

---

## 7. 主要路径 helper

当前最重要的 helper 位于 `backend/app/utils/path_helpers.py`：

- `build_raw_dir()`
- `build_raw_file_path()`
- `build_raw_markdown_dir()`
- `build_raw_markdown_path()`
- `build_asset_dir()`
- `build_knowledge_markdown_dir()`
- `build_knowledge_doc_path()`
- `build_knowledge_manifest_path()`
- `to_storage_key()`
- `resolve_storage_key_path()`

这些 helper 才是运行时路径真相，文档和代码都应以它们为准。

> **注意**：旧的 `services/upload_support.py` 已删除。
> 新代码 **必须** 从 `app.utils.path_helpers` 导入。

---

## 8. 当前正式产物

### 8.1 Ingest 之后

- `raw_files/<raw_file_id>.<ext>`
- `raw_markdowns/<raw_file_id>.md`
- `assets/<raw_file_id>/*`

### 8.2 Digest Docs 发布之后

- `knowledge_markdowns/chapter_XX_*.md`
- `knowledge_markdowns/merged_knowledge_base.md`
- `knowledge_markdowns/manifest.json`
- `knowledge_markdowns/.build.lock`

### 8.3 中间与调试产物

- `knowledge_markdowns/_build/*`
- `temp/*`
- `debug/*`

---

## 9. 目录名与表名不是一回事

当前必须明确区分两套概念：

- 数据库表名：按业务模型命名
- 文件系统目录名：按运行时产物命名

例如：

- 表里是 `raw_file`
- 目录里是 `raw_files/`

例如：

- 表里是 `knowledge_document`
- 目录里是 `knowledge_markdowns/`

不要把目录名误写成数据库表名，也不要反过来。

---

## 10. 删除与重建边界

可以安全重建：

- `temp/`
- `debug/`
- `knowledge_markdowns/_build/`

需要谨慎处理：

- `raw_files/`
- `raw_markdowns/`
- `assets/<file_id>/`
- `knowledge_markdowns/*.md`
- `knowledge_markdowns/manifest.json`

---

## 11. 一句话结论

当前仓库的关键事实是：

- 复杂流程真相在 `workflows/`
- AI 引擎封装在 `infra/`
- 应用基础设施在 `core/`（仅 5 个模块）
- 数据真相在数据库
- 文件真相在 `raw_files / raw_markdowns / assets / knowledge_markdowns`
- 真实路径命名必须服从 `utils/path_helpers.py`
- 依赖方向：`api → services → workflows → infra → core`，`utils/` 可被任意层引用
## 12. 规范运行时辅助模块

- `app.utils.path_helpers` 是运行时路径构造的规范来源。
- `app.utils.docgen_store` 是知识文档构建锁、manifest 与运行时构建状态辅助逻辑的规范来源。
- `services/` 下旧的 helper 入口已经删除；调用方应直接依赖 `app.utils.path_helpers`、`app.utils.presenters`、`app.utils.docgen_store`。
- `knowledge_markdowns/build_status.json` 现在是与 `manifest.json`、`.build.lock` 并列的正式运行时产物。
- 不新增顶层 `app/common` 包；workflow 共享编排能力继续放在 `workflows/common`。
