# 10. 仓库结构与运行时文件

## 1. 文档定位

本文档只回答两件事：

- 源码主阅读顺序是什么
- 运行时数据根目录现在到底怎么落盘

数据库表设计看 [13_database_schema_inventory.md](./13_database_schema_inventory.md)。  
部署与存储抽象看 [11_database_and_storage_architecture.md](./11_database_and_storage_architecture.md)。

---

## 2. 源码主阅读顺序

后端主顺序：

`api -> services -> workflows -> repositories -> models -> schemas -> core`

顶层目录：

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 页面、组件、前端 API |
| `backend/` | FastAPI、workflow、repository、model |
| `docs/` | 设计文档 |
| `backend/scripts/` | 工程脚本 |

---

## 3. 运行时数据根目录

代码配置默认数据根目录是：

`./data/`

在当前仓库的常见启动方式下，实际通常会看到：

`backend/data/`

其中：

- 常见落点里的 `backend/data/aiteachme.db` 是主 SQLite 数据库
- 每个 `subject` 一个运行时目录
- `chunk_embeddings` 是本地 `sqlite-vec` 虚拟表，不是文件目录

---

## 4. 当前 Subject 目录布局

当前代码真实目录由 `backend/app/services/upload_support.py` 定义：

```text
backend/data/<subject>/
├─ raw/
├─ raw_markdown/
├─ assets/
├─ knowledge_markdown/
│  └─ _build/
├─ temp/
└─ debug/
```

目录职责：

| 目录 | 作用 |
| --- | --- |
| `raw/` | 原始上传文件 |
| `raw_markdown/` | ingest 解析后的 Markdown |
| `assets/` | 当前 subject 的共享资源目录 |
| `knowledge_markdown/` | 已发布知识文档 |
| `knowledge_markdown/_build/` | 知识文档 staging 和中间产物 |
| `temp/` | 临时文件 |
| `debug/` | 调试快照 |

---

## 5. 命名说明

这里是运行时目录名，不是数据库表名。

- 数据库表名按单数 `snake_case` 设计
- 运行时目录名以当前代码真实实现为准
- 当前不要在文档里提前改成不存在的复数目录名

也就是说，当前文档必须写：

- `raw/`
- `raw_markdown/`
- `assets/`
- `knowledge_markdown/`

而不是写成未来假想名字。

---

## 6. 当前正式产物

### 6.1 Ingest 后

- `raw/<raw_file_id>.<ext>`
- `raw_markdown/<raw_file_id>.md`
- `assets/<asset_name_prefix>__*.png|jpg|...`

### 6.2 Digest Docs 后

- `knowledge_markdown/chapter_XX_*.md`
- `knowledge_markdown/merged_knowledge_base.md`
- `knowledge_markdown/manifest.json`
- `knowledge_markdown/.build.lock`

### 6.3 中间产物

- `knowledge_markdown/_build/*`
- `temp/*`
- `debug/*`

### 6.4 版本记录怎么放

- 运行时目录默认只保留当前 live 的知识文档文件
- 最近一次 live 的文件级元数据写在 `knowledge_markdown/manifest.json`
- 历史版本真相放在数据库的 `knowledge_document.package_key / version_no / is_current`

也就是说，版本管理主要靠数据库，不靠在文件系统里无限堆目录层级。

---

## 7. 删除与重建边界

可以安全重建：

- `temp/`
- `debug/`
- `knowledge_markdown/_build/`

谨慎删除：

- `raw/`
- `raw_markdown/`
- `assets/`
- `knowledge_markdown/*.md`
- `knowledge_markdown/manifest.json`

---

## 8. 一句话结论

`backend/data/` 当前分三层，而且“目录名”和“数据库表名”是两套概念：

- 数据库：`aiteachme.db`
- 正式文件产物：`raw/ raw_markdown/ assets/ knowledge_markdown/`
- 中间与调试产物：`_build/ temp/ debug/`
