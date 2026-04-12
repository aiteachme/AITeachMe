# Digest Refactor 总览

本目录是 Digest refactor 的权威设计入口。

## 目标

这轮重构只主动改两件事：

1. 把 `tool / skillpack / workflow runtime` 的边界固定下来。
2. 把 Digest DocGen 流程改成可扩展、可观测、可迁移的高质量知识文档流水线。

## 已确认的问题

- `shared/infra/orchestrators` 和 workflow node 职责重叠。
- `shared/infra/prompt_builders` 和 workflow prompts 职责重叠。
- `PedagogyWriter` 同时沾 `infra` 和 `teaching`。
- 旧工具扩展只有 YAML 元数据，没有真实 handler 绑定。
- `skills` 以前只发现和渲染，没有真正进入主运行链。

## 本轮权威结论

- `tools` 是唯一运行时可调用扩展点。
- `skillpack` 是 `SKILL.md` 风格 prompt strategy package。
- `toolpack` 是真实外部工具扩展模型。
- `workflows/.../runtime` 承载 workflow 专属多步逻辑。
- `shared/infra/orchestrators` 与 `shared/infra/prompt_builders` 目录都不再保留。
- `shared/infra/traced_execution.py` 是唯一通用 traced execution helper。
- `shared/infra/llm_support/routing.py` 是 canonical 模型路由位置。

## 阅读顺序

1. `03_tools_refactor.md`
2. `04_docgen_pipeline.md`
3. `05_document_modes.md`
4. `06_retrieval_strategy.md`
5. `07_teaching_tools.md`
6. `08_migration_plan.md`
7. `09_execution_plan.md`
8. `10_langsmith_observability.md`
9. `implementation_handoff.md`

LangSmith 代码级实现文档：`backend/app/workflows/LANGSMITH.md`

## 权威性说明

- 本 README、`08_migration_plan.md`、`09_execution_plan.md` 是当前重构口径的权威来源。
- 其他文档里如果还保留历史措辞，例如把 business runtime 写成 infra orchestrator，应按这里的口径理解。
