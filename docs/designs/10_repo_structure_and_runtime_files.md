# 10. 仓库结构与运行时文件布局

## 1. 文档目标

本文档说明：

- 仓库顶层目录各自承担什么职责。
- 哪些文件是源码真相源。
- 哪些文件是生成物。
- 运行时数据在本地如何落盘。

---

## 2. 仓库顶层结构

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端、页面、组件、前端 API、MSW mock |
| `backend/` | FastAPI 后端、service、workflow、repository、model |
| `docs/` | 设计文档与协作文档 |
| `backend/scripts/` | OpenAPI 导出、流程图生成等工程脚本 |

真相源与生成物必须分开理解：

- 真相源：`backend/app/*`、`frontend/src/*`、`docs/designs/*`
- 生成物：`frontend/openapi.json`、`frontend/src/api/generated/*`、`backend/scripts/.generated_workflow_diagrams/*`

---

## 3. 后端源码结构

`backend/app/` 当前仍按这条链路阅读最稳：

`api -> services -> workflows -> repositories -> models`

| 目录 | 作用 |
| --- | --- |
| `api/` | HTTP 路由与资源边界 |
| `services/` | 用例入口、聚合查询、后台任务触发 |
| `workflows/` | 复杂业务工作流编排 |
| `repositories/` | 数据访问与批量写入 |
| `models/` | SQLModel 数据模型 |
| `schemas/` | API schema |
| `core/` | 配置、数据库、LLM、日志、异常 |

---

## 4. 本地运行时数据布局

默认数据根目录：

`backend/data/`

每个学科一个子目录：

`backend/data/<subject>/`

常见子目录如下：

| 目录 | 作用 | 类型 |
| --- | --- | --- |
| `raw/` | 原始上传文件 | 正式业务产物 |
| `markdown/` | 解析后的 Markdown | 正式业务产物 |
| `assets/` | 文档图片和附件 | 正式业务产物 |
| `knowledge_docs/` | 已发布知识文档 | 正式业务产物 |
| `docgen_intermediate/` | 知识文档构建中间文件 | 调试友好产物 |
| `debug/` | 其他 workflow 调试快照 | 调试产物 |

---

## 5. Knowledge Docs 目录约定

Docs workflow 现在使用固定 staging 布局，不再按 `job_id` 落目录。

### 5.1 正式目录

`backend/data/<subject>/knowledge_docs/`

当前约定包含：

- `chapter_01_*.md`
- `chapter_02_*.md`
- `...`
- `merged_knowledge_base.md`
- `manifest.json`
- `.build.lock`

### 5.2 staging 目录

`backend/data/<subject>/knowledge_docs/_building/`

构建中的新版本先写到这里：

- `_building/chapter_XX_*.md`
- `_building/merged_knowledge_base.md`

发布成功后再整体覆盖正式目录。

### 5.3 中间目录

`backend/data/<subject>/docgen_intermediate/latest/`

它用于保存：

- 清洗后的文本
- 大纲
- 草稿
- review / metadata 辅助结果

它不是最终对外协议的一部分。

---

## 6. Docs 链路为什么不再使用 run_or_job_id 目录

Graph / Curriculum 仍可能使用：

`data/<subject>/debug/<workflow>/<run_or_job_id>/`

但 Docs 链路已经明确不再使用这种结构作为正式协议，原因是：

- Docs 对外不再暴露 job 概念
- 前端读取的是“已发布结果”而不是“某次任务状态”
- staging 发布只需要固定 `_building/`
- 最近一版发布信息只需要 `manifest.json`

---

## 7. 典型文件生成链路

### 7.1 Ingest 完成后

通常会得到：

- `raw/<file>`
- `markdown/<raw_file_id>.md`
- `assets/<raw_file_id>/...`

### 7.2 Digest Docs 完成后

通常会得到：

- `knowledge_docs/chapter_XX_*.md`
- `knowledge_docs/merged_knowledge_base.md`
- `knowledge_docs/manifest.json`
- `docgen_intermediate/latest/*`

### 7.3 Digest Graph / Curriculum 完成后

主要结果仍在数据库中，必要时会写到：

- `debug/digest.graph/<job_id>/`
- `debug/digest.curriculum/<job_id>/`

---

## 8. 删除与重建约定

### 8.1 可以安全重建

- `docgen_intermediate/latest/`
- `knowledge_docs/_building/`
- `debug/`

### 8.2 谨慎删除

- `knowledge_docs/chapter_XX_*.md`
- `knowledge_docs/merged_knowledge_base.md`
- `knowledge_docs/manifest.json`

这些文件代表当前已发布知识文档版本。

### 8.3 非常谨慎删除

- `backend/data/aiteachme.db`
- 整个 `backend/data/<subject>/`

这通常等价于清空本地工作空间。

---

## 9. 当前结论

运行时文件布局现在已经明确区分了 3 类东西：

- 正式产物
- staging 产物
- 调试产物

尤其是 Docs 链路：

- 正式文档在 `knowledge_docs/`
- 构建中版本在 `_building/`
- 最近一版元信息在 `manifest.json`
- 构建互斥通过 `.build.lock`
