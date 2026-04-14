# Workflows 分层说明

最后更新：2026-04-15

`backend/app/workflows/` 是业务编排层，负责把 `teaching` 的教学语义和 `shared.infra` 的基础能力组织成可运行的业务流程。

一句话理解：
> `workflows` 负责“这条业务流程怎么跑”。

## 目录职责

```text
workflows/
├── ingest/
├── digest/
├── interact/
├── examine/
├── profile/
├── LANGSMITH.md
└── TRACKED_STEP.md
```

- `ingest/`：资料导入与解析。
- `digest/`：知识编织与文档/图谱构建。
- `interact/`：伴读对话。
- `examine/`：出题、组卷、评分。
- `profile/`：学习画像与复习建议。

## 共享 workflow 支撑放哪里

`workflows/` 只保留业务引擎。

workflow 共用作者侧能力统一放在 `app.shared.infra.workflow`，当前公开入口为：

```python
from app.shared.infra.workflow import (
    WorkflowGraphExport,
    WorkflowContext,
    run_state_graph,
    invoke_state_graph,
    workflow_tracer,
    traceable_run,
    tracked_step,
)
```

其中：

- `runtime.py` 负责 LangGraph 执行入口
- `steps.py` 负责 runtime step / progress / substep tracing
- `authoring.py` 负责 graph authoring 辅助，例如 `workflow_tracer` 与 `WorkflowGraphExport`
- `context.py`、`events.py`、`result.py`、`types.py` 提供 workflow 共用契约

业务 workflow 代码默认直接从 `app.shared.infra.workflow` 导入；
只有维护 infra 实现时，才需要直接进入 `authoring.py`、`steps.py` 这些模块。

## 与 infra 的边界

- 底层 tracing / tracking 统一在 `app.shared.infra.observability`
  - `trace.py`：LangSmith、ambient context、`@traceable` wrapper、metadata / tags、脱敏
  - `track.py`：内存态统计与 span
- `app.shared.infra.workflow` 不再实现第二套 tracing 系统，只做 workflow authoring / runtime 适配
- `app.shared.infra.execution` 负责共享长运行执行单元契约

## 阅读顺序

建议按下面顺序看：

1. `backend/app/shared/infra/workflow/__init__.py`
2. `backend/app/shared/infra/workflow/context.py`
3. `backend/app/shared/infra/workflow/runtime.py`
4. `backend/app/shared/infra/workflow/authoring.py`
5. `backend/app/shared/infra/workflow/steps.py`
6. 对应具体引擎的 `runtime.py` / `graph.py`

## 一句话总结

`workflows` 只保留业务引擎编排；workflow 共用支撑统一收口到 `app.shared.infra.workflow`，底层 trace / track 统一收口到 `app.shared.infra.observability`。

