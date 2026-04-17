# Workflows 说明

最后更新：2026-04-17

`backend/app/workflows/` 现在是 AITeachMe 后端的唯一业务层。这里不仅负责五大引擎的图编排，也负责承接面向 API 的业务用例和非引擎业务模块。

## 先看什么

- 总体结构规范：[STRUCTURE.md](./STRUCTURE.md)
- 调试方式：[DEBUGGING.md](./DEBUGGING.md)
- LangSmith 约定：[LANGSMITH.md](./LANGSMITH.md)
- 进度事件约定：[PROGRESS.md](./PROGRESS.md)

## 当前分区

### 五大引擎

- `ingest`
- `digest`
- `interact`
- `examine`
- `profile`

### 支撑业务

- `support`

`support/` 用来承接原本不属于五大 AI 引擎、但仍然属于后端业务层的模块，例如 `system`、`auth` 与 `subjects`

## 当前 canonical 链路

- `ingest/fast_parse`
- `digest/planner`
- `digest/docgen`
- `digest/knowledge_graph`
- `interact/chat`
- `examine/question_build`
- `examine/exam_grade`
- `profile/pipeline`

## 当前已落地的单层化示例

- `ingest/__init__.py`、`digest/__init__.py`
  引擎模块根只保留稳定导入面，不再承载业务实现
- `ingest/fast_parse/graph.py`
  Ingest 图定义与 workflow export 声明落点
- `ingest/fast_parse/lib/enhance.py`、`ingest/fast_parse/lib/recovery.py`
  Ingest 后台增强与增强恢复落点
- `digest/common/events.py`、`digest/common/exports.py`
  Digest 跨链路事件与 workflow export 落点
- `digest/knowledge_graph/overview.py`、`digest/knowledge_graph/study_plan.py`
  基于知识图谱的总览与学习计划用例
- `digest/docgen/__init__.py`、`digest/knowledge_graph/__init__.py`
  Digest workflow runner 的模块级入口
- `digest/planner/__init__.py`、`digest/planner/graph.py`
  Planner 的 API-facing 入口与 workflow runner 落点
- `digest/docgen/builds.py`
  DocGen 构建触发、状态装配与后台编排入口
- `digest/common/runtime_config.py`
  Digest 教学运行时配置 facade
- `digest/common/pedagogy/`
  Digest 教学语义 facade
- `support/system/init.py`、`support/system/settings.py`
  系统初始化与设置总览的 canonical 位置
- `support/files/catalog.py`、`support/files/uploads.py`、`support/files/parsing.py`、`support/files/deletion.py`
  文件模块按用例拆分后的 canonical 位置
- `profile/application/`
  Profile 面向 API 的掌握度与复习任务用例落点
- `interact/application/`
  Interact 面向 API 的聊天会话、历史记录与 SSE streaming 外壳落点
- `support/auth/identity.py`、`support/auth/sessions.py`、`support/auth/smtp.py`
  鉴权模块按身份、会话、邮件通道拆分后的 canonical 位置
- `support/export_import/exports.py`、`support/export_import/imports.py`、`support/export_import/courses.py`
  学科级课程包导入导出模块按用例拆分后的 canonical 位置

## 最重要的调用入口

当前上层依然主要依赖模块级稳定入口：

```python
from app.workflows.ingest import run_parse_file_workflow
from app.workflows.digest import run_docgen_workflow
from app.workflows.digest.planner import run_build_planner_workflow
from app.workflows.interact import stream_chat_workflow
```

如果要调图结构，再进入各链路目录看 `graph.py`

## 目录边界

新的推荐依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

这意味着：

- `app/services` 源层已移除，不再作为代码落点或兼容入口
- `app/teaching` 源层已移除
- `workflows` 内新业务代码禁止再直接 import `app.services.*` 与 `app.teaching.*`
- 教学语义统一从 `digest/common`、具体 workflow lane 与 `shared.infra.tools` 进入

具体结构规则请统一看 [STRUCTURE.md](./STRUCTURE.md)。
