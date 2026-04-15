# Workflows 说明

最后更新：2026-04-16

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

`support/` 用来承接原本不属于五大 AI 引擎、但仍然属于后端业务层的模块，例如 `system` 与 `teaching_tools`

## 当前 canonical 链路

- `ingest/fast_parse`
- `ingest/deep_enhance`
- `digest/planner`
- `digest/docgen`
- `digest/knowledge_graph`
- `digest/unified`
- `interact/chat`
- `examine/question_build`
- `examine/exam_grade`
- `profile/pipeline`

## 当前已落地的单层化示例

- `digest/application/`
  Digest 模块根下的 API-facing use case 落点
- `digest/_shared/runtime_config.py`
  Digest 教学运行时配置 facade
- `digest/_shared/pedagogy/`
  Digest 教学语义 facade
- `support/teaching_tools/`
  教学工具实现的 canonical 位置
- `support/system/`
  系统初始化查询的 canonical 位置，承接原 `app.services.system_service`
- `support/files/`
  文件上传、列表、删除与解析触发的 canonical 位置，承接原 `app.services.file_service`
- `profile/application/`
  Profile 面向 API 的掌握度与复习任务用例落点
- `interact/application/`
  Interact 面向 API 的聊天会话、历史记录与 SSE streaming 外壳落点
- `support/auth/`
  访客身份、邮箱注册登录、token 与验证码的 canonical 位置
- `support/export_import/`
  学科级课程包导入导出的 canonical 位置

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
- 教学语义统一从 `digest/_shared`、`support/teaching_tools` 与 `shared.infra.tools` 进入

具体结构规则请统一看 [STRUCTURE.md](./STRUCTURE.md)。
