# Infra 分层说明

最后更新：2026-04-14

`app.shared.infra` 是后端的共享基础设施层。
它回答的是：

- 配置怎么读取
- 数据库和存储怎么接
- LLM / Search / Tool / Memory 这些底层能力怎么统一暴露
- Tracing 和执行契约怎么统一接入

它**不**回答：

- 某条业务流程怎么编排
- 某个教学动作怎么表达
- 某个 workflow 节点应该先跑还是后跑

对新同学来说，先记住这句区分：

> `infra` 负责把能力接稳，`teaching` 负责把教学语义讲清，`workflows` 负责把流程跑起来。

## 1. 先看它在系统里的位置

当前更准确的依赖关系应该理解成一个小型 DAG，而不是单条线：

```text
api -> services
services -> workflows
services -> teaching
workflows -> teaching
services/workflows/teaching -> shared.infra -> shared.kernel
```

这里的含义是：

- `infra` 在业务层之下，给上层提供共用能力。
- `infra` 可以被 `services`、`workflows`、`teaching` 复用。
- `workflows` 可以依赖 `teaching` 提供的教学语义与文档脚手架。
- `teaching` 不应该反向依赖 `workflows`。
- `infra` 不应该反向依赖某个具体业务流程。

另外注意一个很容易混的点：

- `backend/app/shared/infra/` 是**应用内共享基础设施层**。
- 仓库根目录的 `infra/` 是**部署、统计、脚本等仓库运维目录**。

这两个目录名字一样，但不是一回事。

## 2. 新成员先用这张“找东西地图”

| 我想找什么 | 应该先看哪里 |
| --- | --- |
| 读取项目配置 | `config/settings.py`、`config/support.py` |
| 读取 `.env`、解析环境变量 | `env_support.py` |
| 区分本地 / 云端模式 | `runtime/mode.py` |
| 本地运行时路径、SQLite 路径 | `runtime/paths.py` |
| 数据库引擎、Session、向量表 | `database.py` |
| 本地存储 / S3 存储 | `storage/` |
| 业务侧统一文件读写 | `storage/content_store.py` |
| 调 LLM | `llm_support/` |
| LLM 调用与路由入口 | `llm_support/`、`llm_support/routing.py` |
| Prompt 变量填充 | `prompt_loader.py` |
| Embedding 与 token 预算 | `embedding.py`、`token_budget.py` |
| Guardrail / 通用推理策略 | `guardrails/`、`reasoning.py`、`strategies.py` |
| 搜索、检索、网页读取 | `search/` |
| 工具注册与执行 | `tools/` |
| Toolpack 扩展加载 | `tools/tool_loader.py` |
| Skillpack 渲染与推荐 tag | `skills/` |
| 共享记忆与学习档案 | `memory/` |
| 统一 LangSmith / LLM tracing | `observability/` |
| 长执行单元的通用执行契约 | `execution/` |
| 进程内后台任务注册 | `runtime/tasks.py` |
| 学科级 embedding 绑定 | `subject_settings.py` |

## 3. `infra` 现在实际有哪些层

下面不是“理想分层”，而是按当前代码真实目录整理出来的阅读顺序。

### 3.1 配置与运行环境层

这一层负责让应用知道“自己运行在哪里、配置从哪里来、日志怎么打”。

主要文件：

- `__init__.py`
  导入时调用 `load_local_dotenv()`，保证本地开发时自动读取仓库根 `.env` 或 `backend/.env`。
- `env_support.py`
  负责读取环境变量、解析布尔/整数/浮点值、定位项目根目录和 `config.yaml` 路径。
- `config/settings.py`
  项目级运行配置对象，当前主要从 `config.yaml` 加载。
- `config/support.py`
  配置解析辅助，例如 embedding 维度映射、retriever profile、配置字段映射。
- `runtime/mode.py`
  负责本地 / 云端模式判断，以及版本、Cookie 策略等运行模式相关逻辑。
- `runtime/paths.py`
  统一本地运行时数据目录和 SQLite 路径。
- `logger.py`
  日志初始化入口。

这一层不关心业务，只关心“环境如何被解析出来”。

### 3.2 数据与资源接入层

这一层负责把数据库、存储、缓存、事件等资源接进来。

主要文件：

- `database.py`
  数据库引擎、Session、SQLite / PostgreSQL 初始化、向量列和 subject 向量表管理。
- `storage/`
  存储抽象层。
  - `base.py`：底层存储接口
  - `local_store.py`：本地文件存储
  - `s3_store.py`：S3 存储
  - `content_store.py`：业务代码推荐直接使用的统一文件接口
  - `config.py`：存储后端选择与 S3 配置
  - `sync_bridge.py`：同步桥接辅助
- `cache.py`
  当前是 LLM 语义缓存的共享实现。
- `events.py`
  教学事件日志的共享实现，供长期学习闭环回流使用。
- `subject_settings.py`
  负责把 `Subject.settings_json` 里的 embedding 绑定结构化。
- `runtime/tasks.py`
  FastAPI 进程内后台任务注册表，API 触发的后台任务都挂在这里。

判断标准：

- 这层可以决定“资源怎么接、怎么持久化、怎么复用”。
- 这层不应该决定“某个 workflow 什么时候使用这些资源”。

### 3.3 AI 能力与通用辅助层

这一层负责 AI 基础能力本身，不负责业务流程顺序。

主要文件和目录：

- `llm_support/`
  当前 LLM 的主入口。
  - `text.py`：普通文本调用
  - `stream.py`：流式调用
  - `structured_calls.py`：结构化输出
  - `tool_calls.py`：带工具调用
  - `fallback.py`：模型 fallback 策略
  - `routing.py`：任务类型到模型 profile 的路由
  - `observability.py`：LLM 观测辅助
- `llm_support/`
  LLM 的唯一主入口，内部区分 text / stream / structured / tool calls。
- `llm_support/routing.py`
  模型任务到 profile 的路由入口。
- `prompt_loader.py`
  Prompt 模板变量填充辅助。
- `embedding.py`
  Embedding 生成相关共享能力。
- `token_budget.py`
  token 预算辅助。
- `guardrails/`
  通用 guardrail pipeline。
- `reasoning.py`
  通用推理模式封装。
- `strategies.py`
  把 reasoning、tool、guardrail 组合成通用策略原语。
- `agent_loop.py`
  共享 agent/tool loop 辅助。
- `checker.py`
  通用评分 / rubric helper，不等于当前 Examine 主链的完整评分系统。

要特别注意：

- 这里可以提供“怎么调用模型”的共享方法。
- 这里不决定“Digest 失败后要不要回退”“Interact 什么时候查知识库”这种业务语义。

### 3.4 检索与资料获取层

这一层统一处理“怎么找资料、怎么读资料、怎么压缩上下文”。

主目录：

- `search/`
  当前 canonical search 层。
  - `retrievers/`：找候选来源
  - `readers/`：把 URL / 文档读成正文
  - `knowledge.py`：本地知识库检索契约
  - `source_curation.py`：来源筛选
  - `context_compression.py`：上下文压缩
  - `factory.py`：按 profile 组装 retriever / reader
  - `cache.py`：search runtime cache
  - `api.py`：对外统一入口

推荐继续阅读：

- `search/README.md`

旧的根层检索入口例如 `retrievers.py`、`reranker.py` 已经删除。

如果你在旧文档或旧分支里看到这些名字，请把它们理解成历史入口；
当前实现统一从 `search/` 及其子目录进入。

### 3.5 工具、扩展与技能包层

这一层负责“系统能调用哪些工具”和“如何加载外部扩展”。

主要目录：

- `tools/`
  运行时可执行工具的主入口。
  - `definition.py`：工具定义
  - `decorator.py`：`@tool(...)`
  - `registry.py`：工具注册表
  - `api.py`：列举和执行工具的统一入口
  - `tool_loader.py`：外部 toolpack 加载
  - `builtin/`：内建工具
- `skills/`
  `SKILL.md` 风格 skillpack 的加载、解析、渲染与推荐 tag 处理。
- `mcp.py`
  当前轻量 MCP 接入口。

三个概念一定要区分：

- `tool`：真正可执行的动作。
- `toolpack`：一组外部工具扩展包。
- `skillpack`：给 prompt 注入策略和默认值，不执行代码。

### 3.6 共享记忆层

这一层负责跨模块共享的记忆与学习档案。

主目录：

- `memory/`
  - `api.py`：记忆读写统一入口
  - `store.py`：记忆存储
  - `profile.py`：用户画像
  - `learner_doc.py`：学习者档案文档
  - `types.py`：类型定义

`memory` 里的东西是共享基础能力，不是教学表达本身。

### 3.7 观测与执行契约层

这一层把上面的共享能力纳入统一的 tracing 与执行约束里。

主要文件：

- `observability/__init__.py`
  `infra` 层推荐直接从这里导入 tracing 能力；底层实现位于 `observability/tracing.py`。
- `observability/tracing.py`
  统一 LangSmith / LLM tracing、上下文透传、敏感字段裁剪、调用统计与摘要能力。
- `execution/__init__.py`
  `infra` 层推荐直接从这里导入共享执行契约；底层实现位于 `execution/traced.py`。
- `execution/traced.py`
  通用长执行单元契约，例如章节 research/writer 一类 runtime 单元会复用这个抽象。
- `exceptions.py`
  基础设施层异常定义。

这里最容易混淆的一点是：

- `execution/traced.py` 是**共享执行契约**。
- `workflows/digest/docgen/runtime/*.py` 是**业务 runtime 实现**。

两者不是同一个层次。

### 3.8 安全与运行限制层

主要文件：

- `execution/security.py`
  安全相关辅助。
- `execution/sandbox.py`
  运行限制、沙箱执行、安全边界控制。

它们属于基础设施层，因为多个 workflow 都可能共用。

## 4. 真实调用链怎么理解

新同学最容易迷路，不是因为目录多，而是不知道调用链从哪开始。下面是几条最常见的真实链路。

### 4.1 应用启动链

`app.main:create_app()` 会依次用到：

1. `logger.py` 初始化日志
2. `config/get_settings()` 读取项目配置
3. `database.py` 初始化数据库
4. `runtime/paths.py` 确定本地数据目录
5. `storage/` 决定走本地还是 S3
6. `runtime/tasks.py` 挂到 FastAPI app state 上

### 4.2 workflow 节点里的 LLM 调用链

一个 workflow 节点如果要调模型，通常会经过：

<<<<<<< HEAD
1. `workflows/common` 建立 workflow 上下文
2. `app.shared.infra.observability` 用 `llm_trace_scope(...)` 绑定 subject / workflow / lane / node
=======
1. `shared/infra/workflow` 建立 workflow 上下文
2. `observability/tracing.py` 用 `llm_trace_scope(...)` 绑定 subject / workflow / lane / node
>>>>>>> origin/main
3. `llm_support/*` 发起实际模型调用
4. `app.shared.infra.observability` 内部统计 token 和延迟

所以：

- tracing 和模型调用的共享逻辑属于 `infra`
- 节点顺序、阶段切换属于 `workflows`

### 4.3 teaching tool 的注册与执行链

教学工具虽然归 `teaching` 所有，但执行系统还是 `infra`：

1. `app.teaching.tools` 里用 `@teaching_function(...)` 定义工具
2. `app.teaching.teaching` 最终调用 `infra.tools.tool(...)` 注册
3. `infra.tools.registry.ToolRegistry` 维护全局注册表
4. `infra.tools.api.run_agent_tool(...)` 负责执行

所以团队不要再在 `teaching` 里发明第二套工具系统。

### 4.4 搜索链

DocGen / Planner / Interact 需要找资料时，通常是：

1. `search.factory` 选择 retriever 组合
2. `search.retrievers/*` 找候选结果
3. `search.readers/*` 读取正文
4. `source_curation.py` 过滤来源
5. `context_compression.py` 压缩成可喂给 LLM 的上下文

流程怎么决定由谁先跑，属于 `workflows`；检索能力本身属于 `infra`。

## 5. 当前已经收敛掉的旧入口

这一轮已经直接删除下面这些旧入口，不再保留兼容层：

- `llm.py`
- `model_router.py`
- `retrievers.py`
- `reranker.py`
- `execution.py`
- `call_tracking.py`

现在的新入口很简单：

| 能力 | 入口 |
| --- | --- |
| 运行环境 | `runtime/` |
| LLM 调用与路由 | `llm_support/`、`llm_support/routing.py` |
| 统一观测 | `observability/` |
| 共享执行契约与执行安全 | `execution/` |
| 检索 | `search/` |

判断规则也更直接：

- 目录就是 canonical 入口，不再额外保留旧别名。
- 新代码如果还想从根层平铺文件里找旧入口，说明目录分层还没读清楚。
- `infra` 现在优先通过包目录表达分组，而不是靠一堆平铺 shim 过渡。

## 6. 哪些东西不应该放进 `infra`

下面这些东西即使“看起来像基础能力”，也不应该往这里塞：

- workflow graph、state、node、router、subgraph
- workflow 专属 runtime
- 章节脚手架、教学块、教学上下文表达
- 某个业务场景专属 prompt 文本
- 失败后的业务兜底策略
- 第二套 tool registry、第二套 memory store、第二套 tracing 入口

判断方法很简单：

### 问题 1：离开具体业务，这段代码还成立吗？

- 如果成立，可能是 `infra`
- 如果不成立，通常不是 `infra`

### 问题 2：它是在描述“能力本身”，还是在描述“流程顺序”？

- 能力本身，可能放 `infra`
- 流程顺序，应该放 `workflows`

### 问题 3：它表达的是教学语义吗？

- 如果是，应该放 `teaching`

## 7. 新代码放置速查

| 需求 | 更合适的目录 |
| --- | --- |
| 新增一个统一存储 helper | `shared.infra.storage` |
| 新增一个 retriever | `shared.infra.search.retrievers` |
| 新增一个共享 tool | `shared.infra.tools` |
| 新增一个教学工具 | `teaching.tools` |
| 新增一个章节脚手架函数 | `teaching.documents` |
| 新增一个 Digest graph 节点 | `workflows.digest...` |
<<<<<<< HEAD
| 新增一个 workflow 节点 / 步骤的 trace 规则 | `workflows.common` |
| 新增一个共享 tracing primitive 或注解式 helper | `shared.infra.observability` |
=======
| 新增一个 workflow 运行步骤的 trace 规则 | `shared.infra.workflow` 或 `shared.infra.observability` |
>>>>>>> origin/main

## 8. 阅读建议

第一次读 `infra`，建议顺序如下：

1. `env_support.py`
2. `config/settings.py`
3. `runtime/mode.py` 和 `runtime/paths.py`
4. `database.py`
5. `storage/__init__.py` 与 `storage/content_store.py`
6. `llm_support/__init__.py`
7. `search/__init__.py`
8. `tools/__init__.py`
9. `memory/__init__.py`
10. `observability/__init__.py` 与 `execution/__init__.py`

## 9. 一句话总结

`infra` 是共享能力接入层。
它负责把数据库、存储、LLM、检索、工具、记忆、Tracing 这些能力接稳、接统一，但不替业务决定流程怎么跑。
