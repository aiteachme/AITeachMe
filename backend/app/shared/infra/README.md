# Infra 分层说明

`app.shared.infra` 只放基础设施、跨引擎基础能力、以及少量兼容 shim。

它不负责教学策略，也不负责某一轮 workflow 的业务编排。

## 当前结论

- `shared/infra` 不是业务 orchestration 层。
- `shared/infra/orchestrators/` 已删除，不再保留目录。
- `shared/infra/prompt_builders/` 已删除；所有业务 prompt 文本都归 `workflows/.../prompts`。
- `shared/infra/traced_execution.py` 是唯一 canonical traced execution helper。
- `shared/infra/execution.py` 只是旧导入兼容 shim。
- `shared/infra/llm_support/` 是当前 LLM 能力的 canonical 位置。
- `shared/infra/llm.py` 只是旧入口兼容 shim，项目内部不应继续依赖。
- `shared/infra/llm_support/routing.py` 是模型任务路由的 canonical 位置。
- `shared/infra/model_router.py` 只是旧入口兼容 shim。
- `shared/infra` 不再保留 `runtime.py`；`runtime` 作为业务运行单元只属于 `workflows/.../runtime`。
- `tools` 是唯一运行时可调用扩展点。
- `skillpack` 只做策略注入，不执行代码。
- 外部工具扩展正式采用 `toolpack`，不是 YAML-only 元数据。
- `prompt_loader.py` 只负责通用模板渲染，不拥有任何业务 prompt 文本。

## 这一层应该放什么

- 配置、数据库、存储、缓存、日志、追踪、LangSmith/LangGraph 接缝。
- LLM 调用、模型路由、fallback、structured output、tool calling。
- 检索与资料获取基础设施：retriever factory、reader、legacy scraper shim、knowledge retrieval、reranker、search helper。
- canonical tool registry、tool decorator、toolpack loader。
- skillpack loader 与渲染器。
- 通用 memory、search support、可跨引擎复用的 helper。
- 一个通用 traced execution helper。
- 极少数兼容 shim。

## 这一层不应该放什么

- 教学块、教学结构、章节脚手架、错因翻译、练习编排。
- 某个 workflow 专属的多步业务运行单元。
- graph/state/router/subgraph 业务编排。
- workflow-local prompt 文本。
- 任何第二套 tool registry 或第二套 teaching runtime。
- 任何把业务 prompt 内容重新搬回 `infra` 的做法。

## 长期目录语义

```text
shared/infra/
├── traced_execution.py   # 唯一 canonical traced execution helper
├── execution.py          # 兼容 shim
├── tools/                # canonical tool registry + toolpack loader
├── skills/               # SKILL.md prompt skillpack loader / renderer
├── search/               # retriever / readers / knowledge / curation / compression
├── llm_support/          # LLM 调用、fallback、structured output、routing
├── llm.py                # 兼容 shim
├── model_router.py       # 兼容 shim
├── runtime_paths.py      # 运行时文件路径 helper，不是 workflow runtime
├── storage/              # content store / local / s3
├── memory/               # canonical memory primitives + context helpers
├── tracing.py            # LangSmith / runtime tracing
└── mcp.py                # 当前仍是轻量原型；若继续扩张应升级为 mcp/ 包
```

## `tool / skillpack / toolpack`

- `tool`
  一个原子动作，稳定输入输出，可被 LLM/tool calling 真正调用。
- `skillpack`
  `SKILL.md` 风格策略包，只提供提示词、默认约束、推荐 tool tags，不执行代码。
- `toolpack`
  一个真实外部工具包，目录形态为 `manifest.yaml + handler.py`，负责向 canonical tool registry 注册可执行工具。

## 关键判断规则

- 脱离 Digest/Interact/Examine 仍然成立的东西，才进 `infra`。
- 如果模块在回答“如何接 provider / 如何统一 tracing / 如何让多处复用”，它应该在这里。
- 如果模块在回答“这轮课程先检索什么、后写什么、怎样做章节 fan-out”，它不该在这里。

## 额外边界说明

- `search/`
  这是统一的检索与资料获取层，不是纯 `rag/`。其中：
  `retrievers/` 负责发现候选来源，
  `readers/` 负责读取 URL 内容，
  `knowledge.py` 负责本地知识库检索契约与 rerank。
  `retrievers.py` 与 `reranker.py` 只保留兼容 shim，不再是新的 canonical 入口。
- `memory/`
  这里只放通用记忆原语、画像聚合、上下文拼装 helper，不放教学业务判断。
- `runtime_paths.py`
  这里只处理 backend 本地运行所需的固定路径；它不是 workflow 里的 `runtime` 业务单元。
- `mcp.py`
  目前仍是轻量原型文件；如果开始承载多 transport、server lifecycle、registry bridge，就应拆成 `shared/infra/mcp/` 包。
- LangSmith 兼容代码：
  provider/调用级追踪放 `shared/infra/tracing.py` 与 `shared/infra/llm_support/observability.py`；
  workflow 级观测结构放 `workflows/common/observability.py` 与各 workflow 自己的 observability 文件。


