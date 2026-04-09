# Infra 层说明

`app.shared.infra` 是 AITeachMe 的基础设施层。

它不直接表达某一个业务流程，而是为 `workflows/`、`services/`、`teaching/` 提供统一的底层能力，包括：

- 模型调用与路由
- LangSmith 可观测性
- 搜索、抓取、工具、技能
- 存储、缓存、运行时路径
- 记忆、护栏、安全与沙箱

这层的目标不是“写业务”，而是把可复用、可观测、可替换的能力沉到底座里。

## 1. 定位

可以把 `shared/infra` 理解为“AI Runtime + Integration Layer”：

- `shared/kernel/` 放纯内核概念，尽量无外部依赖。
- `shared/infra/` 放会连接模型、数据库、存储、搜索、外部工具的基础设施。
- `teaching/` 放教学语义和教学领域复用逻辑。
- `workflows/` 放五大引擎的 LangGraph 编排与状态流转。

一句话边界：

- `infra` 解决“能力从哪里来、怎么接、怎么观测”。
- `teaching` 解决“教学语义怎么组织”。
- `workflows` 解决“这些能力按什么顺序运行”。

## 2. 依赖边界

推荐依赖方向如下：

```text
shared/kernel
    ↑
shared/infra
    ↑
teaching / repositories / services
    ↑
workflows / api
```

应遵循的规则：

- `infra` 可以依赖 `shared/kernel`，但不要反向依赖业务模块。
- `workflows` 应优先通过 `app.shared.infra.*` 调用底层能力，而不是散落地直接连第三方 SDK。
- 教学语义、章节脚手架、判卷策略，优先放在 `app.teaching`，不要塞回 `infra`。
- 面向 LangGraph 的状态对象、节点路由、事件编排，不要写进 `infra`。

## 3. 目录地图

### 3.1 运行时基础

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `config.py` | 全局运行配置入口 | 读取模型、存储、LangSmith、搜索、并发等配置 |
| `database.py` | DB Session/连接辅助 | 给 repository / service / workflow 统一使用 |
| `logger.py` | 结构化日志初始化 | 统一 `structlog` 风格 |
| `runtime_paths.py` | 运行时路径约定 | 管理数据目录、缓存目录、临时目录 |
| `task_registry.py` | 后台任务注册与状态管理 | 给后台构建、解析、异步任务使用 |
| `subject_settings.py` | 学科级运行配置 | 例如 embedding 或学科特定开关 |
| `storage/` | 内容存储抽象 | 支持本地和 S3，统一 raw markdown / assets / knowledge docs 的读写 |

这组模块主要解决“系统怎么跑起来”。

### 3.2 LLM 与调用封装

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `llm.py` | 对外统一 LLM 调用入口 | 文本、流式、工具调用都从这里进 |
| `embedding.py` | 向量化入口 | 为检索、图谱、chunk embedding 服务 |
| `model_router.py` | 模型选择策略 | 按任务类型映射 fast / smart / strategic |
| `prompt_loader.py` | Prompt 模板装载 | 统一模板读取与渲染 |
| `token_budget.py` | 上下文预算控制 | 避免 prompt 和检索片段失控 |
| `cache.py` | 缓存封装 | 降低重复调用成本 |
| `reasoning.py` | 推理策略辅助 | 放模型调用侧的策略工具，而不是业务编排 |
| `llm_support/` | `llm.py` 的内部实现细分 | 处理 text / stream / structured / tool-calls / fallback / observability |

`llm_support/` 是目前最关键的子目录之一：

- `text.py` / `stream.py`：处理普通文本与流式响应。
- `structured.py` / `structured_calls.py`：处理结构化输出。
- `tool_calls.py`：处理 tool-calling 模式。
- `fallback.py`：负责 tier 降级与统一兜底。
- `observability.py`：构造 LangSmith 兼容的输入输出与 metadata。

如果后续继续融合 `gpt-researcher` 的 provider/tier 思路，这一层是第一落点，不是直接改 workflow 节点。

### 3.3 可观测性与 LangSmith

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `tracing.py` | LangSmith tracing 基础设施 | 构造 trace scope、metadata、tags、嵌套 run |
| `llm_support/observability.py` | LLM 粒度 payload 清洗 | 控制输入输出截断、敏感字段、tool calls 展示 |

当前 LangSmith 相关配置主要在 `config.py`：

- `langsmith_tracing`
- `langsmith_project`
- `langsmith_capture_inputs`
- `langsmith_capture_outputs`
- `langsmith_max_text_chars`

后续所有新增 AI 能力都应优先遵循这条规则：

1. 先决定 trace 边界。
2. 再决定调用实现。
3. 不要等功能写完了再“补埋点”。

推荐的 trace 粒度：

- 单次 LLM 调用：由 `llm.py` / `llm_support/*` 自动记录。
- Skill/Tool/Retriever：在各自基类里记录。
- Workflow 节点：由 `workflows/common/observability.py` 或节点侧封装负责。

## 4. 搜索、抓取与检索

### 4.1 Search 子系统

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `search/api.py` | 对外搜索入口 | 给外层统一调用 |
| `search/factory.py` | 检索器装配 | 根据配置组合 retriever |
| `search/types.py` | 搜索结果类型 | 统一 Web / local result 结构 |
| `search/retrievers/` | 检索器实现 | `bing` / `bocha` / `duckduckgo` / `local_rag` |
| `search/scraper/` | 网页/PDF 抓取 | 把 URL 变成可消费文本 |
| `search/web.py` | Web 搜索辅助封装 | 给上层一个简化入口 |

### 4.2 检索相关辅助

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `retrievers.py` | 检索管线封装 | 聚合多种检索来源 |
| `reranker.py` | 重排逻辑 | 对候选片段二次排序 |

这部分是未来继续吸收 `gpt-researcher` 的主要接口层：

- 多 retriever 并行
- 抓取与净化
- Source curation
- 本地 RAG + Web research 混合策略

都应该先落到这里，再由 `skills/researcher.py` 或 workflow 节点编排。

## 5. Tools、Skills、Agent Loop

### 5.1 Tools

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `tools/definition.py` | Tool 定义模型 | 统一参数/描述结构 |
| `tools/decorator.py` | `@tool` 装饰器 | 声明原子工具 |
| `tools/registry.py` | Tool 注册表 | 统一管理工具 |
| `tools/tool_loader.py` | YAML Tool 装载 | 读取 `backend/tools/*.yaml` |
| `tools/builtin/` | 内置原子工具 | `web_search` / `search_kb` / `memory_ops` / markdown/latex/query 处理等 |

`tools/` 适合放“原子动作”：

- 输入输出清晰
- 可独立测试
- 不负责复杂多步编排

### 5.2 Skills

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `skills/base.py` | `BaseSkill`、`SkillContext`、`SkillResult`、注册机制 | 技能层基础抽象 |
| `skills/api.py` | `run_skill()` / `list_skills()` | 对外统一入口 |
| `skills/loader.py` | 加载项目内置与用户自定义 skill | 读取 `backend/skills/` 和用户目录 |
| `skills/researcher.py` | ResearchConductor | 检索、抓取、压缩的组合技能 |
| `skills/writer.py` | PedagogyWriter | 教学化写作 |
| `skills/source_curator.py` | 来源筛选/质量控制 | 研究资料质量管理 |
| `skills/context_manager.py` | 上下文压缩与净化 | 防止材料过长、重复 |
| `skills/mermaid_generator.py` | Mermaid 生成 | 用于文档富媒体 |
| `skills/image_generator.py` | 文生图规划/占位逻辑 | 当前更多是框架预留 |

`skills/` 适合放“重量级组合能力”：

- 内部会调用多个 tool / retriever / scraper
- 需要 trace metadata
- 需要被 workflow 节点直接复用

### 5.3 Agent Loop 与策略

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `agent_loop.py` | ReAct/工具循环 | 让模型按循环方式调用工具 |
| `strategies.py` | 更高层的策略调度辅助 | 用于控制不同推理/调用策略 |

当前 digest 主流程更多走 LangGraph 显式编排，但交互式、多工具的开放任务仍然可以复用这一层。

## 6. 记忆、护栏与外部工具

### 6.1 Memory

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `memory/api.py` | 对外记忆 API | remember / recall 等 |
| `memory/store.py` | 记忆存储实现 | 负责持久化 |
| `memory/profile.py` | 学习者画像结构 | 供 interact / profile 使用 |
| `memory/learner_doc.py` | Learner 文档管理 | 长期学习档案 |
| `memory/types.py` | 记忆类型定义 | tag、entry 等 |

### 6.2 Guardrails 与 Security

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `guardrails/` | 护栏管线 | 风险过滤、规则化检查 |
| `security.py` | 操作安全控制 | 面向危险工具或高风险动作 |
| `exceptions.py` | infra 领域异常 | 给上层统一抛出稳定错误 |

### 6.3 MCP / Sandbox / Events

| 文件/目录 | 作用 | 备注 |
| --- | --- | --- |
| `mcp.py` | MCP 集成入口 | 让模型接外部 tool server |
| `sandbox.py` | 沙箱抽象 | 预留代码/终端/训练环境能力 |
| `events.py` | 基础事件能力 | 统一事件记录接口 |

## 7. Storage 约定

`storage/` 不是简单的文件读写工具，而是整个内容资产层的统一抽象。

它主要承接这些对象：

- 上传原文件
- 解析后的 raw markdown
- 文档相关静态资源
- 发布后的 knowledge markdown
- 构建过程中的中间产物

当前结构：

- `base.py`：存储接口抽象
- `local_store.py`：本地文件系统实现
- `s3_store.py`：对象存储实现
- `content_store.py`：内容 key 约定
- `sync_bridge.py`：同步/异步桥接

这层对 ingest、digest、export/import 都很关键。后续若要上云或支持多环境，这里必须保持稳定。

## 8. 与 workflows 的关系

可以把 `workflows/` 理解为 orchestration layer，而 `infra/` 是 capability layer。

典型关系如下：

```text
workflows/ingest
  └─ 调用 storage / llm / events / runtime_paths

workflows/digest
  └─ 调用 llm / search / skills / tools / tracing / embedding / storage

workflows/interact
  └─ 调用 llm / agent_loop / tools / memory / search / tracing

workflows/examine
  └─ 调用 llm / memory / tracing / events / 题目上下文相关能力

workflows/profile
  └─ 调用 memory / events / tracing / 统计辅助
```

判断一个能力该放哪里，可以用这几个问题：

1. 它是否可以被多个 workflow 复用？
2. 它是否主要在解决“连接外部系统/模型/工具”的问题？
3. 它是否不依赖某个具体 workflow 的 state？

如果三者都成立，优先放 `infra`。

## 9. 哪些内容不应该放在 infra

这些内容不要继续塞进 `infra`：

- LangGraph 的 state schema
- workflow 节点的路由判断
- 教学章节结构设计、教学话术模板
- 学科领域专属规则
- API request/response schema
- repository/service 的业务组合逻辑

对应落点通常分别是：

- `workflows/`
- `teaching/`
- `schemas/`
- `services/`

## 10. 后续重构建议

结合当前 refactor 文档，`infra` 后续重点不是“大改目录”，而是继续做厚底座、薄流程：

### 10.1 工具体系

- 新增教育域原子工具时，优先放 `tools/builtin/`。
- 需要多步组合和上下文压缩的能力，优先放 `skills/`。
- `gpt-researcher` 的 action 思路继续映射到 `tools/`，而不是直接写死在 docgen 节点里。

### 10.2 LangSmith

- 每个新 Skill、Retriever、Scraper 默认要带 trace metadata。
- 新增 build lane 时，要能按 `subject`、`planner_session_id`、`confirmed_plan_id`、`chapter_index` 检索 trace。
- 输入输出采样和截断规则，应继续统一收敛在 `llm_support/observability.py`。

### 10.3 富媒体文档支持

- Mermaid、图片、交互 HTML 的生成能力，优先建设在 `skills/`。
- workflow 只负责决定“何时生成”，不负责关心“生成细节如何实现”。

## 11. 给开发者的落地建议

新增一个底层 AI 能力时，建议按这个顺序做：

1. 明确它是 Tool、Skill、Retriever、Scraper 还是纯 helper。
2. 明确它的 trace 入口和 metadata。
3. 明确它的输入输出类型和失败语义。
4. 先写最小可用实现，再接入 workflow。
5. 不要把临时业务判断偷偷塞进 `infra`。

---

如果你正在看 digest/docgen/graph 的重构，这个 README 可以当作“底座地图”：

- 要改工具调用，看 `tools/`、`skills/`、`search/`
- 要改模型调用，看 `llm.py`、`llm_support/`、`model_router.py`
- 要改可观测性，看 `tracing.py`、`llm_support/observability.py`
- 要改内容资产和落盘，看 `storage/`、`runtime_paths.py`
