# Infra 分层说明

最后更新：2026-04-15

`app.shared.infra` 是后端共享基础设施层。它负责把数据库、存储、检索、工具、技能、执行契约、Tracing 这些通用能力接稳，但不负责教学语义，也不负责某条业务流程的编排顺序。

一句话理解：
> `infra` 负责“能力怎么接”，`teaching` 负责“怎么教”，`workflows` 负责“流程怎么跑”。

## 1. 当前边界

推荐把依赖方向理解成下面这张图：

```text
api -> services
services -> workflows
services -> teaching
workflows -> teaching
services/workflows/teaching -> shared.infra -> shared.kernel
```

当前这轮需要特别记住两条硬边界：

- `app.shared.infra` 不直接 import `app.teaching`
- `app.shared.infra` 不直接 import `app.services`

如果需要同步上层注册信息，应该通过通用 hook、回调或显式参数注入，而不是在 infra 里写死业务模块名。

## 2. 与 Planner / DocGen 的关系

当前知识文档主线是：

```text
api/knowledge_docs.py
-> services/knowledge_docs/build_planner_service.py
-> app.workflows.digest.planner
-> confirmed_plan
-> services/knowledge_docs/digest_service.py
-> app.workflows.digest.run_docgen_workflow
```

`infra` 在这条主线里提供的是下面这些底座：

| 能力 | 当前稳定入口 | 对 planner / docgen 的作用 |
| --- | --- | --- |
| 搜索 | `app.shared.infra.search` | 本地 RAG、外部 retriever、reader、source curation |
| 向量状态 | `app.shared.infra.subject` | 判断学科向量是否可检索，给搜索层提供只读 gating |
| 工具 | `app.shared.infra.tools` | 统一工具注册表、执行入口、registry sync hook |
| 技能 | `app.shared.infra.skills` | skillpack 渲染、默认值、推荐 tag |
| workflow 支撑 | `app.shared.infra.workflow` | `tracked_step`、`run_state_graph`、workflow context |
| 执行契约 | `app.shared.infra.execution` | 长执行单元的共享边界与观测 |
| 存储 | `app.shared.infra.storage` | 统一文件读写和后端存储接入 |
| 观测 | `app.shared.infra.observability` | LangSmith / trace / track 的唯一底层实现 |

重点是：

- planner / docgen 可以依赖 `infra`
- `infra` 不反向感知 planner / docgen 的业务语义

## 3. 当前最重要的目录

| 目录或文件 | 作用 |
| --- | --- |
| `config/`、`env_support.py`、`runtime/` | 读取环境、运行模式、项目配置、运行时路径 |
| `database.py` | 数据库引擎、Session、向量表能力 |
| `storage/` | 本地存储 / S3 / 统一内容存储接口 |
| `llm_support/` | 文本、结构化、流式、tool call、上下文窗口预算等 LLM 主入口 |
| `search/` | 本地知识检索、retriever、reader、source curation |
| `subject/` | 学科向量配置与只读向量能力的稳定入口 |
| `tools/` | 工具注册、执行、toolpack 加载 |
| `skills/` | `SKILL.md` 风格技能包渲染与推荐 |
| `memory/` | 共享记忆与学习档案 |
| `workflow/` | workflow authoring/runtime 公共支撑 |
| `execution/` | 共享执行契约与执行安全边界 |
| `observability/` | trace / track 的底层唯一实现 |

## 4. Search / Tools / Skills / Execution / Workflow / Storage 怎么看

### 4.1 `search/`

`search/` 是 planner / docgen 最直接会碰到的 infra 子系统。

当前推荐入口：

- `app.shared.infra.search.search_knowledge(...)`
- `app.shared.infra.search.web_search(...)`
- `app.shared.infra.search.get_knowledge_search_notice(...)`

这层现在已经收口为：

- `search/api.py` 只依赖 `infra` 自己的只读向量能力
- 向量 gating 通过 `subject/` 提供，不再反向依赖 `services`

### 4.2 `tools/`

`tools/` 是系统的 canonical tool registry。

当前推荐入口：

- `tool(...)`
- `list_agent_tools()`
- `run_agent_tool(...)`
- `register_tool_registry_sync_hook(...)`

本轮之后的边界约定是：

- `infra.tools` 只负责“注册表”和“同步 hook 机制”
- `teaching` 自己注册 teaching tool 的 sync hook
- `infra` 不再直接 import `app.teaching.teaching`

### 4.3 `skills/`

`skills/` 负责 skillpack 的解析、渲染和推荐 tag，不执行代码。

planner / docgen 常见使用方式是：

- 根据 selected skillpacks 渲染 prompt 片段
- 读取 prompt scope 默认值
- 收集推荐的 tool tags

skillpack 不是 tool，也不是 workflow。

### 4.4 `execution/`

`execution/` 表达的是共享执行边界，不是某条具体 digest runtime。

要区分：

- `app.shared.infra.execution`：共享执行契约
- `app.workflows.digest.docgen.runtime/*`：docgen 自己的业务 runtime

### 4.5 `workflow/`

`workflow/` 是 workflow authoring / runtime 的公共层，不是业务 workflow 本身。

业务代码默认从这里导入：

```python
from app.shared.infra.workflow import (
    WorkflowContext,
    WorkflowGraphExport,
    invoke_state_graph,
    run_state_graph,
    tracked_step,
    traceable_run,
    workflow_tracer,
)
```

不要再把 `workflows/common` 当成新的公共基座。

### 4.6 `storage/`

`storage/` 负责把本地文件、S3 和业务统一内容接口接起来。

对上层更重要的结论是：

- planner / docgen 要文件内容时，优先走统一内容存储接口
- 不要在 workflow 里重新发明一套存储后端判断逻辑

### 4.7 `llm_support/`

`llm_support/` 除了 completion / structured / tool calls 之外，也承载和上下文窗口直接相关的 LLM 辅助工具。

当前上下文预算与消息截断统一放在：

- `app.shared.infra.llm_support.context_window`

这类能力更接近 “LLM 输入怎么组织”，不再平铺在 `shared/infra` 根目录。

## 5. `subject/` 的定位

`subject/` 是这轮整理后的 subject 级 infra 子包，目的是把“学科设置怎么存”和“向量当前能不能用”收口到同一处，但仍然保持 settings / vectors 两层职责分离。

其中：

- `settings.py` 负责 `Subject.settings_json` 的结构化读写、binding 模型、vector table 命名
- `vectors.py` 负责 runtime embedding snapshot、vector capability、status / notice / queryable 判定

稳定导入面统一通过：

- `app.shared.infra.subject`

它适合承载：

- `RuntimeEmbeddingConfig`
- `SubjectVectorCapability`
- `get_runtime_embedding_config()`
- `get_subject_vector_capability()`
- `get_subject_vector_status[_by_slug]()`
- `get_subject_vector_search_notice()`
- `should_generate_subject_embeddings()`

它不负责：

- precheck 决策写入
- disable / rebuild 的状态修改
- 重建向量表

这些仍然属于 `app.services.subject_embedding_service`。

## 6. 什么不该放进 Infra

下面这些内容不要继续回流到 `infra`：

- workflow graph、state、node、router、subgraph
- workflow 专属 runtime
- teaching documents、教学块、教学上下文表达
- 某个业务场景专属 prompt
- 某条业务链自己的失败兜底策略
- 第二套 tool registry / memory store / tracing 入口

判断方法很简单：

- 离开具体业务还能成立，才可能是 `infra`
- 如果在描述“流程顺序”，那应该去 `workflows`
- 如果在描述“教学表达”，那应该去 `teaching`

## 7. 阅读顺序

第一次读 `infra`，建议按下面顺序：

1. `env_support.py`
2. `config/settings.py`
3. `runtime/mode.py` 与 `runtime/paths.py`
4. `database.py`
5. `storage/content_store.py`
6. `subject/`
7. `search/__init__.py`
8. `tools/__init__.py`
9. `workflow/__init__.py`
10. `observability/__init__.py` 与 `execution/__init__.py`

## 8. 一句话总结

`infra` 是共享能力接入层。
它要尽量稳定、可复用、无业务反向依赖，为 planner / docgen 等上层链路提供可靠底座，但不替它们决定教学策略或流程顺序。
