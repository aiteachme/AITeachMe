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
-> app.workflows.digest.planner
-> confirmed_plan
-> workflows/digest/docgen/lib/build_lifecycle.py
-> app.workflows.digest.run_docgen_workflow
```

`infra` 给这条链路提供的是：

| 能力 | 当前稳定入口 | 对 planner / docgen 的作用 |
| --- | --- | --- |
| 搜索 | `app.shared.infra.search` | 本地 RAG、外部 retriever、reader、source curation |
| 向量状态 | `app.shared.infra.course` | 判断课程向量是否可检索，并处理构建前向量配置确认 |
| 工具 | `app.shared.infra.tools` | 统一工具注册表、内置工具与 toolpack 执行入口 |
| workflow 支撑 | `app.shared.infra.workflow` | workflow root / node / progress |
| 执行契约 | `app.shared.infra.execution` | 长执行单元共享边界 |
| 存储 | `app.shared.infra.storage` | 统一文件读写与内容存储 |
| 观测 | `app.shared.infra.observability` | LangSmith tracing 与 LLM 统计底层实现 |

重点是：

- planner / docgen 可以依赖 `infra`
- `infra` 不反向感知 planner / docgen 的业务语义

### Search 边界

`shared.infra.search` 只负责“发现来源、读取材料、压缩上下文”，不负责决定教学策略，也不负责生成最终答案。

稳定调用面：

```python
from app.shared.infra.search import web_search, search_knowledge
```

约定：

- workflow 默认调用 `web_search()` 或 `search_knowledge()`。
- 只有 search 层内部、调试工具或特殊 workflow 才直接调用 `dispatch_web_search()`。
- retriever 名是稳定配置名，统一用小写 snake_case。
- profile 名是内部检索 preset，不表达教学意图；对外应展示 `retrieval_policy`（本地优先、是否联网、来源优先级和选择原因），不要把 `docgen_*` 名称当业务语义。
- 不提供泛化抓站入口。新增外部网站必须是明确站点适配器，放入 `search/retrievers/sites/` 并说明使用边界。

### Provider-native tools 边界

`llm_support.native_tools` 只描述上游模型提供商内置工具的请求 hint，例如 OpenAI Responses `web_search` / `file_search`。它不注册项目函数工具，也不执行检索。

分工约定：

- 自管课程 RAG 仍走 `search_knowledge()`、KnowledgeUnit / KG / vector pipeline，并由 workflow 决定如何写入 prompt 和引用。
- 项目函数工具仍走 `app.agent_tools` / `shared.infra.tools`，例如 `search_kb`、`web_search`、`recall_info`。
- Provider-native tools 只通过 LLM helper 的 `provider_native_tools` kwarg 进入 Responses adapter；Chat Completions 和项目函数工具请求会丢弃该 hint，避免把 provider-specific 参数误传到普通网关。
- `file_search` 需要外部 provider vector store，不能默认替代本地课程索引；`auto` 只在课程工具链且本地 RAG 证据不足时补充，`force` 才表示显式强制发送。
- 全局 `settings.llm.native_*` 只提供默认能力开关；具体 workflow step 是否允许、继承或强制 provider-native tools，应由对应 `model_policy.py` 通过 `ProviderNativeToolPolicy` 声明。
- 文本/流式普通输出会由 adapter 统一决定 `responses` 或 `chat_completions`：`auto` 模式只对 `model_catalog.RESPONSES_API_MODELS` 中的文本模型优先使用 Responses，名单外默认走 Chat Completions；结构化输出和项目函数工具固定走 Chat Completions。
- `acompletion_stream()` 始终向上游请求真实流式输出。自定义 OpenAI-compatible Responses 网关不采用 LiteLLM 对未知模型名生成的伪流式；`RESPONSES_API_MODELS` 只决定接口形态，不再维护第二份流式模型名单。
- LangSmith LLM span 会记录 requested / initial / final API mode、route reason、原生 Responses 流式状态和 provider-native tool types，用于判断是否发生 Responses 到 Chat 的自动回退。

## workflow / observability 公开接口

现在 workflow 相关公开接口已经极简收口。

## 公开入口约定

`infra` 不再保留一个总的 `facade/` 目录。

之前的 `app.shared.infra.facade` 只是预留门面层，没有被 workflow/API 实际调用，反而让入口变得不清楚。现在按能力包直接导入稳定入口：

| 能力 | 推荐入口 |
| --- | --- |
| LLM | `app.shared.infra.llm_support` |
| 搜索 / 资料读取 | `app.shared.infra.search` |
| 工具 | `app.shared.infra.tools` |
| 技能 | `app.shared.infra.skills` |
| workflow runtime | `app.shared.infra.workflow` |
| 执行安全 / 沙箱 | `app.shared.infra.execution` |
| 观测 | `app.shared.infra.observability` |

使用约定：

- workflow / application 可以调用各能力包的稳定入口。
- API 层优先调用 workflows，不直接拼装 infra 能力。
- 文档解析不放在 infra 公共门面中。解析链路归 `app.workflows.ingest`，新增 Docling、MinerU、Marker 等 provider 时应接入 ingest 的 `parsing/provider_contracts.py`、`parsing/decision.py`、`parsing/strategy.py` 与 `parsing/orchestrator.py`，由 ingest 继续负责状态推进、资产产物和 fallback。

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
| `database/` | 数据库引擎、Session、向量索引能力 |
| `storage/` | 本地存储 / S3 / 内容存储接口 |
| `llm_support/` | 文本、结构化、流式、tool call 等 LLM 主入口 |
| `embedding/` | canonical embedding 调用入口与框架适配 |
| `search/` | 本地检索、retriever、reader、source curation |
| `course/` | 课程向量配置、查询能力与构建前 precheck |
| `mcp/` | MCP 协议接入与外部工具服务管理 |
| `tools/` | 运行时工具注册、执行、内置工具、toolpack 加载 |
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

这些逻辑名直接对应运行时 settings 的 `models.reason / primary / light`。也可以传具体模型名。`task_type` 仅作为底层兜底超时/重试画像和粗粒度观测分类保留，不应作为业务代码选择模型、采样参数或请求预算的主要方式。

前端的“自动 / 深度推理 / 均衡 / 快速”是一次请求的模型策略：`settings` 保留 workflow 原有分层，另外三种分别把本次 workflow 的 `reason / primary / light` 全部映射到设置中的同名槽位。映射同时覆盖备用网关模型和 reasoning effort，因此切换实际模型只需要修改设置页或 YAML，不需要改前端源码。

备用网关继续使用相同的逻辑槽位；`fallback_models.reason / primary / light` 可分别覆盖备用模型，字段为 `null` 时继承对应的 `models.*`。备用 provider 不再隐式替换为代码内置的 provider 默认模型。

三层文本模型的推理强度分别由 `llm.reasoning_efforts.reason / primary / light` 控制，`null` 表示使用模型默认值，`extract` 逻辑槽位继承 `light`。设置页根据 `llm_support.model_catalog` 中已知模型能力动态显示合法选项；未知兼容网关模型可通过 YAML 显式配置。备用网关沿用同一逻辑槽位的推理强度，并按其实际模型能力过滤已知的不兼容值。

### LLM 全局并发

所有文本、结构化、流式、tool call、文生图、embedding 和 rerank 调用都共享 `app.shared.infra.llm_support` 内的进程级 limiter。
运行时上限只由 `settings.llm.concurrency_limit` 控制，默认 `12`。workflow 内部可以继续设置本链路自己的 fan-out 上限，但实际发给上游的请求数仍会被全局 limiter 压住。

每次上游调用必须通过 `async with get_llm_concurrency_limiter().slot()` 获取独立 lease。lease 跟随调用生命周期而不是 `asyncio.Task` 记账，因此流在另一个 Task 中关闭时也能准确归还槽位；重试等待只临时释放并重新获取当前 lease。

### LLM 兜底 profile 与业务 model policy

底层 profile 和 workflow 自己的 `model_policy.py` 分工必须保持清楚：

- `TaskType` 是 infra 级轻量标签，只提供兜底 `timeout / max_retries` 以及粗粒度观测归类。默认值维护在 `app.shared.infra.llm_support.routing`。
- 这些兜底 `timeout / max_retries` 应偏宽松，优先避免长文档生成、结构化修复、网络抖动导致的非业务失败；线上仍可用 `LLM_TIMEOUT_<TASK>_S` 和 `LLM_MAX_RETRIES_<TASK>` 覆盖存量调用。
- `model=` 是模型槽位选择，业务 workflow 应显式传 `reason / primary / light`，不要指望 `task_type` 替你选模型。
- workflow 的 `model_policy.py` 负责“这个业务步骤用哪个模型槽位、调用类型、必要的 token 上限、temperature、timeout、max_retries、稳定 metadata”。请求预算和采样参数应跟业务步骤走，不跟 `task_type` 走。
- workflow 的 `model_policy.py` 也负责本步骤的 provider-native tool 策略；用 `ProviderNativeToolPolicy(off/settings/auto/force)` 控制是否继承全局设置或按链路覆盖。
- 如果发现非 workflow 临时调用需要采样参数，应在调用点显式传 `temperature`；不要把新的 temperature 默认塞回 task profile。
- 业务观测字段如 `planner_model_step / docgen_model_step` 应从 workflow 的 model policy 统一生成，再与运行时 metadata 合并，避免每个调用点手写一套。

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
8. `course/`
9. `search/__init__.py`
10. `tools/__init__.py`
11. `workflow/__init__.py`
12. `observability/__init__.py` 与 `execution/__init__.py`

## 一句话总结

`infra` 是共享能力接入层。它要尽量稳定、可复用、无业务反向依赖，为 planner / docgen 等上层链路提供可靠底座，但不替它们决定教学策略或流程顺序。

## 根目录能力包说明

- `backend/tools/` 已删除。旧 YAML-only 工具说明不会注册运行时工具，后续不要恢复这套机制。
- `backend/toolpacks/` 是开发者/管理员使用的可选可执行工具扩展点；只有提供 `manifest.yaml + handler.py` 的子目录才会注册运行时工具。
- 独立 prompt 扩展层已删除。后续教学策略由 Planner、DocGen 节点和 confirmed plan 显式决定。
