# Infra 分层说明

最后更新：2026-04-15

`app.shared.infra` 是后端共享基础设施层，负责提供可复用的底层能力，以及跨 workflow 共享的作者侧支撑，但不承载具体业务引擎实现。

一句话理解：
> `infra` 负责“通用能力怎么接”，`workflows` 负责“具体业务流程怎么跑”。

## 重点入口

- 配置与环境：`config/`、`env_support.py`、`runtime/`
- 数据与存储：`database.py`、`storage/`
- LLM 能力：`llm_support/`
- 搜索与读取：`search/`
- 工具与技能：`tools/`、`skills/`
- 记忆：`memory/`
- 观测：`observability/`
- 执行契约：`execution/`
- workflow 作者侧公共支撑：`workflow/`

## observability 的新约定

`shared/infra/observability` 现在只保留两类主模块：

- `trace.py`
  - LangSmith tracing
  - ambient trace context
  - `@traceable` wrapper
  - metadata / tags 构建
  - 输入输出脱敏
- `track.py`
  - 内存态 LLM call tracking
  - 轻量 span 记录

也就是说，底层 trace / track 只有这一套真实实现，不再在别的包里重复实现第二套。

## workflow 包的定位

`shared/infra/workflow/` 是共享的 workflow authoring / runtime 支撑层，不是业务 workflow 本身。

业务代码默认应从 `app.shared.infra.workflow` 导入公共接口；
`authoring.py`、`steps.py`、`runtime.py` 等文件属于实现分工，不应成为业务层首选导入路径。

它只放这些公共能力：

- `context.py`：`WorkflowContext`
- `events.py`：轻量事件总线
- `runtime.py`：`run_state_graph()` / `invoke_state_graph()`
- `steps.py`：`tracked_step()` 与 runtime steps
- `authoring.py`：`workflow_tracer`、`WorkflowGraphExport`、`traceable_run`
- `result.py`：`WorkflowResult`
- `types.py`：基础类型别名

## execution 的定位

`execution/units.py` 是共享执行契约层，用于长运行或可复用执行单元。
它属于 infra，因为这里表达的是“统一执行边界”，不是某条具体 workflow 的 runtime。

## 与 workflows 的边界

- `app.workflows` 只保留业务引擎：`ingest`、`digest`、`interact`、`examine`、`profile`
- `app.shared.infra.workflow` 提供 workflow 共用作者侧支撑
- `app.shared.infra.observability` 提供唯一的底层 trace / track 能力
- `app.shared.infra.execution` 提供共享执行单元契约

## 一句话总结

`infra` 负责共享能力和统一边界；`workflows` 只负责具体业务编排。
