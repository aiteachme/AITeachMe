# Digest Refactor 总览

最后更新：2026-04-13

本目录是 Digest refactor 的权威设计入口，但它现在不再只是“未来计划”，而是要明确区分三类信息：

1. 已经在代码里落地的边界与约束
2. 已经部分实现、可以继续扩展的能力
3. 仍然只是预留位或下一批工作的方向

## 当前状态快照

### 已经落地

- `shared/infra / teaching / workflows` 三层边界已经固定。
- `tool / skillpack / toolpack` 三种扩展模型已经拆开。
- `workflows/digest/docgen/runtime` 已成为 DocGen 的 workflow-local runtime 落点。
- `selected_skillpacks` 已经打通到 planner -> confirmed plan -> docgen。
- workflow 级 LangSmith 已统一收口为：
  - `run_state_graph(...)`
  - `workflow_tracer(...).node(...)`
  - `@traceable_run(...)`
  - `tracked_step(...)`

### 已经部分落地

- 章节 research 已从单轮检索升级为轻量 micro-loop。
- retriever / reader / compression 已接入最小 runtime cache。
- asset sidecar 已支持 Mermaid / image / interactive HTML 的最小执行链。
- `systematic / sprint` 已进入 confirmed plan、chapter assignment、writer/runtime 与 practice layer。
- digest 侧 lane summary 已能聚合 `requested_profile / applied_profile / research_rounds / asset_summary / practice_count`。

### 仍未完成

- 学科化 retrieval 权重、来源分类调参与持久化缓存策略。
- richer asset sidecar，尤其是更强的 interactive 模板与 animation 真正执行链。
- Interact / Examine / Profile 与 Digest 在 skillpack、课程合同、知识上下文上的更深协同。
- 更强的教学块，例如错因卡、公式卡、变式题、迁移题。

## 本轮权威结论

- `tools` 是唯一运行时可调用扩展点。
- `skillpack` 是 `SKILL.md` 风格 prompt strategy package。
- `toolpack` 是真实外部工具扩展模型。
- `workflows/.../runtime` 承载 workflow 专属多步逻辑。
- `shared/infra/orchestrators` 与 `shared/infra/prompt_builders` 不再作为长期目录继续生长。
- `shared/infra/traced_execution.py` 是唯一通用 traced execution helper。
- workflow tracing 的主入口在 `workflows`，不在 `infra`。

## 阅读顺序

1. `01_architecture_alignment.md`
2. `03_tools_refactor.md`
3. `04_docgen_pipeline.md`
4. `05_document_modes.md`
5. `06_retrieval_strategy.md`
6. `10_langsmith_observability.md`
7. `08_migration_plan.md`
8. `09_execution_plan.md`
9. `11_open_questions.md`
10. `12_appendix.md`
11. `implementation_handoff.md`

代码侧实现文档：

- LangSmith 代码级规范：`backend/app/workflows/LANGSMITH.md`
- workflow step 规范：`backend/app/workflows/TRACKED_STEP.md`
- 当前 workflow authoring 入口：`backend/app/workflows/common/__init__.py`

## 权威性说明

- 本 README、`08_migration_plan.md`、`09_execution_plan.md`、`implementation_handoff.md` 是当前重构口径的管理性文档。
- `04_docgen_pipeline.md`、`05_document_modes.md`、`06_retrieval_strategy.md`、`10_langsmith_observability.md` 是专题设计文档。
- 如果设计文档与当前代码或代码旁文档冲突，优先以当前代码和 `backend/app/workflows/*.md` 的实现文档为准。
- 其他旧文档如果还残留 “infra orchestrator / prompt_builder / legacy tracing alias” 等历史措辞，应按这里的口径理解。
