# Infra 分层说明

最后更新：2026-04-16

`app.shared.infra` 是后端共享基础设施层。它负责把数据库、存储、检索、工具、LLM、workflow runtime、observability 这些通用能力接稳，但不负责教学语义，也不负责业务流程编排。

一句话理解：

> `infra` 负责“能力怎么接”，`workflows` 负责“业务怎么跑、怎么教”。

## 当前边界

推荐把依赖方向理解成：

```text
api -> workflows -> repositories / shared.infra / models / schemas
shared.infra -> shared.kernel
```

两条硬边界：

- `app.shared.infra` 不直接 import `app.teaching`
- `app.shared.infra` 不直接 import `app.services`

## 与 Planner / DocGen 的关系

当前知识文档主线是：

```text
api/knowledge_docs.py
-> workflows/digest/planner/sessions.py
-> app.workflows.digest.planner
-> confirmed_plan
-> workflows/digest/docgen/builds.py
-> app.workflows.digest.run_docgen_workflow
```

`infra` 给这条链路提供的是：

| 能力 | 当前稳定入口 | 对 planner / docgen 的作用 |
| --- | --- | --- |
| 搜索 | `app.shared.infra.search` | 本地 RAG、外部 retriever、reader、source curation |
| 向量状态 | `app.shared.infra.subject` | 判断学科向量是否可检索，并处理构建前向量配置确认 |
| 工具 | `app.shared.infra.tools` | 统一工具注册表、内置工具与 toolpack 执行入口 |
| 技能 | `app.shared.infra.skills` | skillpack 渲染、推荐 tags |
| workflow 支撑 | `app.shared.infra.workflow` | workflow root / node / progress |
| 执行契约 | `app.shared.infra.execution` | 长执行单元共享边界 |
| 存储 | `app.shared.infra.storage` | 统一文件读写与内容存储 |
| 观测 | `app.shared.infra.observability` | LangSmith tracing 与 LLM 统计底层实现 |

重点是：

- planner / docgen 可以依赖 `infra`
- `infra` 不反向感知 planner / docgen 的业务语义

## workflow / observability 公开接口

现在 workflow 相关公开接口已经极简收口。

## 推荐业务入口：`app.shared.infra.facade`

新增业务友好的门面层：

```python
from app.shared.infra.facade import (
    InfraRuntime,
    build_infra_context,
    build_research_context,
    call_llm_structured,
    call_llm_text,
    get_runtime_summary,
    list_tools,
    read_sources,
    run_rag_eval,
    run_tool,
    stream_llm_text,
)
```

使用约定：

- workflow / application 可以调用 facade；API 层不要直接调用。
- facade 只组合 LLM、检索、解析、工具、评测和观测能力，不承载业务状态机。
- `InfraContext` 只携带 `subject / user_id / workflow / lane / node / build_session_id / request_id / permissions / metadata`，不放 DB session、graph state 或教学策略。
- 复杂节点可实例化 `InfraRuntime`；简单调用优先用门面函数。

当前新增的底层能力包括：

- `facade/research.py`：统一组合 retriever、reader、source curation、context compression。
- `facade/tools.py`：统一工具列表和执行入口，支持 risk/scopes/approval 元数据。
- `facade/evals.py`：离线轻量评测入口，后续可接 Phoenix / Ragas / DeepEval。

这层是新增推荐入口，不要求一次性迁移旧代码；新代码优先从 facade 进入。

注意：文档解析不放在 infra facade 中。解析链路归 `app.workflows.ingest`，新增 Docling、MinerU、Marker 等 provider 时应接入 ingest 的 `parsing/providers.py`、`parsing/strategy.py` 与 `parsing/orchestrator.py`，由 ingest 继续负责状态推进、资产产物和 fallback。

### `app.shared.infra.workflow`

推荐导入面：

```python
from app.shared.infra.workflow import (
    WorkflowContext,
    emit_progress,
    invoke_state_graph,
    project_typed_dict_schema,
    run_state_graph,
    workflow_tracer,
)
```

分工：

- `run_state_graph(...)` / `invoke_state_graph(...)`
  workflow root 入口
- `workflow_tracer(...).node(handler, ...)`
  workflow node 接线
- `emit_progress(...)`
  前端阶段事件
- `project_typed_dict_schema(...)`
  从主 `State` 投影出精简的 LangGraph Studio schema

`WorkflowGraphExport` 不属于 workflow 主公开 API。
它只给离线图文导出脚本使用，应该从：

```python
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
```

单独导入。

### `app.shared.infra.observability`

这个包现在只保留极小的公共 trace 原语。

workflow 作者通常不需要从这里直接导入。

如果是 infra 或服务编排层，才会少量使用：

- `langsmith_trace`
- `langsmith_tracing_scope`
- `llm_trace_scope`

像下面这些能力虽然仍存在，但属于 infra-private：

- `traceable_with_context`
- LangSmith sanitizer helpers
- `build_langsmith_extra`
- `trace_substep`

应该直接从子模块导入，而不是继续把它们当成包级公开 API。

## 当前最重要的目录

| 目录或文件 | 作用 |
| --- | --- |
| `settings/`、`env_support.py`、`runtime/` | 运行模式、项目设置、环境变量、路径 |
| `database/` | 数据库引擎、Session、向量表能力 |
| `storage/` | 本地存储 / S3 / 内容存储接口 |
| `llm_support/` | 文本、结构化、流式、tool call 等 LLM 主入口 |
| `embedding/` | canonical embedding 调用入口与框架适配 |
| `search/` | 本地检索、retriever、reader、source curation |
| `subject/` | 学科向量配置、查询能力与构建前 precheck |
| `mcp/` | MCP 协议接入与外部工具服务管理 |
| `tools/` | 运行时工具注册、执行、内置工具、toolpack 加载 |
| `skills/` | `SKILL.md` 风格 prompt 策略包渲染与推荐 |
| `memory/` | 共享记忆与学习档案 |
| `workflow/` | workflow authoring/runtime/progress 公共支撑 |
| `execution/` | 共享执行契约与安全边界 |
| `observability/` | LangSmith tracing 与 LLM 统计底层实现 |

### LLM 模型选择

LLM 调用现在优先用 `model=` 指定模型选择：

```python
await acompletion_with_fallback(messages, model="reason")
await acompletion_with_fallback(messages, model="primary")
await acompletion_with_fallback(messages, model="light")
```

这些逻辑名直接对应 `settings_default.yaml` 的 `models.reason / primary / light / extract`。也可以传具体模型名。`task_type` 仍可用于默认温度、超时、重试和观测归类，但不应再作为业务代码选择模型的主要方式。

## 什么不该放进 Infra

下面这些内容不要继续回流到 `infra`：

- workflow graph、state、node、router、subgraph
- workflow 专属 runtime
- teaching documents、教学表达块、教学上下文拼装
- 业务场景专属 prompt
- 某条业务链自己的兜底策略
- 第二套 tool registry / tracing / progress 框架

判断方法很简单：

- 离开具体业务还能成立，才可能是 `infra`
- 如果在描述“流程顺序”，应该去 `workflows`
- 如果在描述“教学表达”，应该去对应 `workflows/<engine>/_shared` 或 `workflows/support`

## 阅读顺序

第一次读 `infra`，建议按下面顺序：

1. `env_support.py`
2. `settings/settings.py`
3. `runtime/mode.py` 与 `runtime/paths.py`
4. `database/__init__.py`
5. `llm_support/__init__.py`
6. `embedding/__init__.py`
7. `storage/content_store.py`
8. `subject/`
9. `search/__init__.py`
10. `tools/__init__.py`
11. `workflow/__init__.py`
12. `observability/__init__.py` 与 `execution/__init__.py`

## 一句话总结

`infra` 是共享能力接入层。它要尽量稳定、可复用、无业务反向依赖，为 planner / docgen 等上层链路提供可靠底座，但不替它们决定教学策略或流程顺序。

## 根目录能力包说明

- `backend/tools/` 已删除。旧 YAML-only 工具说明不会注册运行时工具，后续不要恢复这套机制。
- `backend/toolpacks/` 是开发者/管理员使用的可执行工具扩展点，必须提供 `manifest.yaml + handler.py`。
- `backend/skills/` 是内置 prompt 策略包目录，只通过 `selected_skillpacks` 和 `prompt_scope` 影响 prompt，不执行代码。
