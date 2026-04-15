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
| `database/` | 数据库引擎、Session、向量表能力 |
| `storage/` | 本地存储 / S3 / 统一内容存储接口 |
| `llm_support/` | 文本、结构化、流式、tool call、上下文窗口预算等 LLM 主入口 |
| `embedding/` | canonical embedding 调用入口与框架适配 |
| `search/` | 本地知识检索、retriever、reader、source curation |
| `subject/` | 学科向量配置与只读向量能力的稳定入口 |
| `mcp/` | MCP 协议接入与外部工具服务器管理 |
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

当前实现已经从“每段硬上限裁切”改成了“总输入预算内的软分配”：

- 各段仍有默认 target cap
- 如果 history / retrieval / system 某一段没用满，剩余额度会回流给其他段
- 超长的最后一条消息至少保留一个截断版本，而不是直接整条丢掉
- `interact` 入口不再先按 `chat_history` 做一次预裁切，而是把完整历史交给 `ContextWindowManager` 统一分配

因此它现在更适合作为共享 LLM 输入组织工具，但是否长期保留在公共层，仍要看后续复用度。

### 4.8 `embedding/`

`embedding/` 现在表达的是 embedding 相关的 canonical 入口，而不是搜索子系统的私有细节。

当前分工：

- `embedding/api.py`
  对外 provider-facing 的 embedding 调用封装
- `embedding/llamaindex.py`
  把 canonical embedding 能力桥接成 LlamaIndex `BaseEmbedding`

这样做的目的是把：

- 底层向量生成能力
- 框架级 embedding 适配

都收在同一个 embedding 语义层里，而不是让 search 子系统看起来像“拥有第二套 embedding 入口”。

当前这轮先不继续拆 `embedding/adapters/`：

- 现在只有一个稳定的框架适配对象 `ATMEmbedding`
- 先把“provider 能力”和“框架适配”分开已经足够解决职责重叠
- 真正出现第二种框架适配时，再把 `llamaindex.py` 下沉到 `adapters/` 会更合适
- `ATMEmbedding` 也不再由 `app.shared.infra.search` 重导出，避免调用方重新依赖回 search 包

### 4.9 `database/`

`database/` 是数据库相关共享能力包，而不是继续用一个根目录单文件承载所有实现。

当前对外导入面保持不变：

- `from app.shared.infra.database import ...`

但内部结构已经为后续继续拆分预留了空间。当前可以把它理解成：

- 应用运行时数据库底座
- Session 管理
- SQLite / PostgreSQL 双模式初始化
- 向量表相关辅助

### 4.10 `mcp/`

`mcp/` 是 MCP 协议接入层。

当前它仍以单个 manager 实现为主，但放进目录后，后续更容易继续拆成：

- transport
- client/session
- tool registration bridge

这比长期把 MCP 逻辑平铺在 `infra` 根目录更稳。

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

## 6. 当前仍建议继续收口的模块

这轮虽然已经把 `subject/` 和 `llm_support/context_window.py` 做了初步归位，但 `infra` 里仍有几组模块值得继续观察。

### 6.1 `llm_support/context_window.py`

当前事实：

- 这个文件现在主要只被 `app.workflows.interact.prompts.messages` 直接使用
- 它做的是消息截断、上下文预算和最终 message 组装，职责更接近 LLM 输入组织层，而不是通用杂项 helper

当前判断：

- 放在 `llm_support/` 方向上是合理的
- 但它目前“共享度”还不高，更像一个已经放到公共层的局部能力

建议口径：

- 如果后面 `chat / planner / docgen` 都开始复用上下文预算逻辑，就继续留在 `llm_support/`
- 如果长期只有 `interact` 使用，可以继续下沉到 `workflows/interact/prompts/` 附近，避免公共层里堆积单场景模块
- 预算策略默认应保持“软上限”，不要重新回到每段死卡上限的激进裁剪

### 6.2 `embedding/` 与 `search/llamaindex_adapter/`

这两层容易看起来像重复，但当前职责其实不同：

- `app.shared.infra.embedding`
  统一 Embedding 调用封装，是底层 provider-facing 能力
- `app.shared.infra.search.llamaindex_adapter`
  负责 vector store / retriever / rerank 等 search 集成能力

当前判断：

- 它们不是严格的功能重复
- 但 LlamaIndex 的 embedding 适配更自然地属于 `embedding/` 而不是 `search/` 自己

建议口径：

- `embedding/` 继续作为 canonical embedding 入口
- `search/llamaindex_adapter/` 保留为 search 集成层
- 如果后面还会接更多 embedding 框架，优先考虑先在 `embedding/` 下新增 `adapters/`
- 如果后面 search 侧还会接更多检索框架，再考虑把 `llamaindex_adapter/` 逐步重命名成更明显的 integration / adapter 语义目录

### 6.3 `reasoning.py`、`strategies.py`、`agent_loop.py`

这三者不是一回事，但当前确实混在了 `infra` 根目录：

- `reasoning.py`
  表达的是“怎么推理”，偏 LLM reasoning style
- `strategies.py`
  表达的是“怎么教 / 怎么互动”，现在的 `EXPLAIN / SOCRATIC / QUIZ / REVIEW` 明显更贴近 `interact` 或 `teaching`
- `agent_loop.py`
  表达的是“带工具的 LLM 循环执行”，更像 agent runtime

当前判断：

- `strategies.py` 的业务语义最重，最不像 infra 根目录模块
- `reasoning.py` 当前几乎没被上层真正消费，像一个待落地的抽象
- `agent_loop.py` 是有价值的底层能力，但更适合落到 `llm_support/agents` 或类似的 runtime 子层，而不是长期平铺在根目录

建议口径：

- 优先考虑先处理 `strategies.py` 的归位
- `reasoning.py` 先判断要不要真正进入主链；如果不用，宁可收缩，不要继续挂在公共层
- `agent_loop.py` 后续可以单独整理成 agent runtime 子目录

### 6.4 `mcp/`、`database/`、`events.py`

这几类能力都在 infra，但不建议把它们简单归到同一个文件夹：

- `database/`
  是应用运行时持久化底座
- `mcp/`
  是外部工具协议接入，更接近 integrations / tools
- `events.py`
  现在更像一个带 SQLite 存储的事件日志子系统，而不只是“事件类型定义”

当前判断：

- `database/` 不应该和 `mcp/` 绑成一个目录
- `mcp/` 更适合未来往 `tools/` 或独立 integrations 子层收
- `events.py` 如果继续长大，应该考虑往 `memory/` 或单独 event log 子层收，而不是继续保持单文件直连数据库

## 7. 什么不该放进 Infra

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

## 8. 阅读顺序

第一次读 `infra`，建议按下面顺序：

1. `env_support.py`
2. `config/settings.py`
3. `runtime/mode.py` 与 `runtime/paths.py`
4. `database/__init__.py`
5. `llm_support/__init__.py` 与 `llm_support/context_window.py`
6. `embedding/__init__.py`
7. `storage/content_store.py`
8. `subject/`
9. `search/__init__.py`
10. `tools/__init__.py`
11. `workflow/__init__.py`
12. `observability/__init__.py` 与 `execution/__init__.py`

## 9. 一句话总结

`infra` 是共享能力接入层。
它要尽量稳定、可复用、无业务反向依赖，为 planner / docgen 等上层链路提供可靠底座，但不替它们决定教学策略或流程顺序。
