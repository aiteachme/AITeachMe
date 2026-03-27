# 10. 仓库结构与运行时文件

## 1. 文档定位

本文档只回答两件事：

- 现在应该按什么顺序读仓库
- 运行时文件到底怎么落盘

数据库表职责请看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。

---

## 2. 推荐阅读顺序

后端主顺序：

`api -> services -> workflows -> repositories -> models -> schemas -> core`

原因：

- `api` 告诉你对外资源长什么样
- `services` 告诉你请求怎么被转成用例
- `workflows` 告诉你复杂流程真实怎么跑
- `repositories/models` 告诉你数据最终怎么落

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
| `core/` | LLM、Search、Memory、Sandbox 等基础设施 |

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

当前真实目录由 `backend/app/services/upload_support.py` 定义：

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

当前最重要的 helper 位于 `backend/app/services/upload_support.py`：

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
- 数据真相在数据库
- 文件真相在 `raw_files / raw_markdowns / assets / knowledge_markdowns`
- 真实路径命名必须服从 `upload_support.py`
