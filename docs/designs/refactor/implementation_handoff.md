# Implementation Handoff

最后更新：2026-04-13

## 当前已经可以当作“固定事实”的内容

### 架构边界

- `shared/infra` = 基础设施与跨引擎基础能力
- `teaching` = 教学语义与 teaching-owned 原子工具
- `workflows` = graph + workflow-local runtime + workflow tracing 主入口

### 扩展模型

- `tool` 是唯一运行时可调用扩展点
- `skillpack` 是 `SKILL.md` prompt strategy package
- `toolpack` 是真实外部工具扩展

### DocGen

- concrete runtime 已稳定回到 `workflows/digest/docgen/runtime`
- `workflow_runtime.docgen.*` 已是当前 runtime trace namespace
- planner -> confirmed plan -> docgen 已支持 `selected_skillpacks`
- chapter research 已进入 micro-loop
- Mermaid / image / interactive HTML 已进入最小 asset sidecar 主线
- mode-aware practice layer 已进入 digest-local 执行链

### LangSmith

- workflow tracing 默认只保留四个入口：
  - `run_state_graph(...)`
  - `workflow_tracer(...).node(...)`
  - `@traceable_run(...)`
  - `tracked_step(...)`
- 新代码和新文档不再继续传播旧 tracing alias

## 目前还在推进中的内容

- 学科化 retrieval 调权与缓存
- richer asset sidecar，尤其是更强的 interactive/image 能力
- 更细颗粒度的 chapter execution contract 与质量门槛
- Digest 与 Interact / Examine / Profile 的更深合同打通
- 更丰富的教学块与练习块

## 后续开发时最容易踩错的点

1. 不要再把 workflow-local business runtime 写回 `shared/infra`。
2. 不要为了“更通用”重新引入 `orchestrators` 或 `prompt_builders` 口径。
3. 不要把 LangSmith 注解重新扩散到大量零散 infra helper。
4. 不要把“预留位”写成“已经落地能力”，尤其是 animation。
5. 不要绕开 confirmed plan / execution contract，直接把模式约束只塞进 prompt。

## 后续继续开发的优先顺序

### 第一优先级

- retrieval quality：profile、source class、cache、micro-loop stop 逻辑

### 第二优先级

- content quality：teaching blocks、repair、coverage/quality gate、mode-specific contract

### 第三优先级

- rich media：interactive/image 做深，animation 设定准入标准

### 第四优先级

- cross-engine convergence：Interact / Examine / Profile 共享 Digest 合同

## 建议继续看的文档

- `docs/designs/refactor/04_docgen_pipeline.md`
- `docs/designs/refactor/06_retrieval_strategy.md`
- `docs/designs/refactor/10_langsmith_observability.md`
- `backend/app/workflows/LANGSMITH.md`
- `backend/app/workflows/TRACKED_STEP.md`

## 一句话 handoff

这轮 refactor 已经完成“边界收敛 + 主链路打通 + 最小可观测性统一”。
下一位继续推进的人，应该把精力放在质量、合同和跨引擎协同上，而不是再回头改基础边界。