# 10. 仓库结构与运行时文件布局

## 1. 文档目标

本文档说明两件事：

- 仓库里的源码真相源在哪里
- `backend/data/` 里的运行时文件现在到底怎么落盘

后续如果代码、数据库和本地目录发生冲突，以 `backend/app/*` 与 `backend/app/services/upload_support.py` 为准。

---

## 2. 仓库顶层结构

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 页面、组件、前端 API、MSW mock |
| `backend/` | FastAPI、service、workflow、repository、model |
| `docs/` | 设计文档与协作说明 |
| `backend/scripts/` | OpenAPI 导出、调试脚本、工程脚本 |

真相源与生成物要分开看：

- 真相源：`backend/app/*`、`frontend/src/*`、`docs/designs/*`
- 生成物：`frontend/openapi.json`、`frontend/src/api/generated/*`
- 运行时数据：`backend/data/*`

---

## 3. 后端源码主阅读顺序

当前后端最稳的阅读顺序仍然是：

`api -> services -> workflows -> repositories -> models`

| 目录 | 作用 |
| --- | --- |
| `api/` | HTTP 资源边界 |
| `services/` | 用例入口、聚合查询、后台任务触发 |
| `workflows/` | LangGraph 工作流编排 |
| `repositories/` | SQLModel / sqlite-vec 数据访问 |
| `models/` | 数据表定义 |
| `schemas/` | API schema |
| `core/` | 配置、数据库、日志、LLM、异常 |

---

## 4. 当前运行时数据根目录

默认数据根目录：

`backend/data/`

其中：

- `backend/data/aiteachme.db` 是主 SQLite 数据库
- `chunk_embeddings` 是 SQLite 里的 `sqlite-vec` 虚拟表
- 每个学科一个独立目录：`backend/data/<subject>/`

---

## 5. 每个 Subject 的目录布局

当前标准布局如下：

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

各目录职责：

| 目录 | 作用 | 类型 |
| --- | --- | --- |
| `raw/` | 用户上传的原始文件 | 正式业务产物 |
| `raw_markdown/` | ingest 解析后的原始 Markdown | 正式业务产物 |
| `assets/` | 当前 subject 下所有图片/附件的共享扁平目录 | 正式业务产物 |
| `knowledge_markdown/` | 已发布知识文档 | 正式业务产物 |
| `knowledge_markdown/_build/` | 知识文档构建中的 staging 与中间产物 | staging / 调试产物 |
| `temp/` | 上传落地前的临时文件 | 临时目录 |
| `debug/` | 其他 workflow 的调试快照 | 调试产物 |

---

## 6. Ingest 产物布局

单个原始文件的正式落盘现在是：

- `raw/<raw_file_id>.<ext>`
- `raw_markdown/<raw_file_id>.md`
- `assets/<asset_name_prefix>__*.png|jpg|...`

这里有两个关键约束：

1. `assets/` 不再是 `assets/<file_id>/` 多级目录，而是整个 subject 共享的一级目录
2. 每个文件提取出的图片用 `asset_name_prefix` 做确定性前缀，避免不同文件的图片重名

典型文件名示例：

`math_exam__file_abcd1234__p3_img1_f81a7f4d3c.png`

---

## 7. Markdown 与图片引用规则

当前约定：

- `raw_markdown/*.md` 全部放在一级目录
- `knowledge_markdown/*.md` 全部放在一级目录
- 图片统一通过相对路径引用：

`../assets/<flattened_asset_name>`

这样做的原因是：

- `raw_markdown/` 和 `knowledge_markdown/` 都是 `assets/` 的兄弟目录
- 所有 Markdown 都能复用同一套相对路径
- 后续如果数据库里直接保存 Markdown 正文，也可以把图片路径替换成绝对路径或对象存储 URI

---

## 8. Knowledge Docs 目录约定

Docs workflow 当前使用固定目录，不再使用 `job_id` 目录。

### 8.1 正式目录

`backend/data/<subject>/knowledge_markdown/`

其中包含：

- `chapter_XX_*.md`
- `merged_knowledge_base.md`
- `manifest.json`
- `.build.lock`

### 8.2 staging / 中间目录

`backend/data/<subject>/knowledge_markdown/_build/`

这里同时承担两类角色：

- 构建中的 staging 发布目录
- docs workflow 的中间调试目录

常见文件包括：

- `chapter_XX_*.md`
- `merged_knowledge_base.md`
- `clean_*.md`
- `outline_tree.json`
- `chapter_assignments.json`
- `draft_*.md`

---

## 9. 典型生成链路

### 9.1 上传并 ingest 解析后

通常会得到：

- `raw/<raw_file_id>.<ext>`
- `raw_markdown/<raw_file_id>.md`
- `assets/<asset_name_prefix>__*.png|jpg|...`

### 9.2 构建知识文档后

通常会得到：

- `knowledge_markdown/chapter_XX_*.md`
- `knowledge_markdown/merged_knowledge_base.md`
- `knowledge_markdown/manifest.json`
- `knowledge_markdown/_build/*`

### 9.3 Digest Graph / Curriculum 后

主要结果在数据库：

- `document`
- `document_chunk`
- `chunk_embeddings`
- `knowledge_*`
- `teaching_unit*`
- `theme_tree*`
- `prereq_dag*`
- `curriculum_snapshot`

这些流程默认不再把“正式结果”写成新的本地 JSON 目录协议；本地 `debug/` 仅用于调试快照。

---

## 10. 删除与重建约定

### 10.1 可以安全重建

- `temp/`
- `debug/`
- `knowledge_markdown/_build/`

### 10.2 谨慎删除

- `raw/`
- `raw_markdown/`
- `assets/`
- `knowledge_markdown/chapter_XX_*.md`
- `knowledge_markdown/merged_knowledge_base.md`
- `knowledge_markdown/manifest.json`

这些文件代表当前正式业务产物。

### 10.3 重要实现细节

因为 `assets/` 是共享目录：

- 删除单个 `RawFile` 时只能按 `asset_name_prefix` 删除匹配图片
- 绝不能再直接删除整个 `assets/` 目录

---

## 11. 当前结论

运行时文件布局已经明确分成三层：

- 数据库中的结构化真相
- `raw/raw_markdown/assets/knowledge_markdown` 中的正式文件产物
- `_build/debug/temp` 中的 staging 与调试文件

后续无论本地部署还是中心化部署，这三层边界都应继续保持稳定。
