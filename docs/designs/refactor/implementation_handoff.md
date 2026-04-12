# Implementation Handoff

## 这轮改动的核心结果

### 架构

- 长期边界已经固定：
  - `shared/infra` = 基础设施与基础能力
  - `teaching` = 教学语义
  - `workflows` = graph + workflow-local runtime

### 扩展模型

- `tool` 是唯一运行时可调用扩展点
- `skillpack` 是 `SKILL.md` prompt strategy package
- `toolpack` 是真实外部工具扩展

### DocGen

- concrete runtime 已经回到 `workflows/digest/docgen/runtime`
- trace 命名已切到 `workflow_runtime.docgen.*`
- planner -> confirmed plan -> docgen 已支持 `selected_skillpacks`

## 代码级落地点

### 新增

- `backend/app/workflows/digest/docgen/runtime/`
- `backend/app/shared/infra/tools/tool_loader.py`
- `backend/toolpacks/README.md`
- toolpack fixture tests

### 关键修改

- `backend/app/shared/infra/execution.py`
- `backend/app/workflows/digest/planner/*`
- `backend/app/workflows/digest/docgen/*`
- `backend/app/shared/infra/skills/*`
- `backend/app/shared/infra/tools/*`

## 已验证内容

- skillpack scope/default/tool tags
- confirmed plan 合同保留 `selected_skillpacks`
- toolpack manifest / handler 加载
- workflow runtime trace namespace
- DocGen research stack 回归
- research micro-loop / gap query 回归
- interactive asset sidecar 回归
- mode-aware practice layer 回归
- teaching tool registry 自愈与回归

## 仍待继续的工作

- 学科化调优 research micro-loop
- richer asset sidecar（animation 仍待真正接入）
- systematic / sprint 更细章节 contract
- Interact 共享 selected skillpacks
- 更丰富的教学块与练习块
- pre-retrieval planning 强化（借鉴 DeepTutor DeepSolve planner）
- 检索缓存与 source-class 调权

## 新增文档

- `backend/app/workflows/LANGSMITH.md`：LangSmith 全链路可观测性指南（代码级实现文档）
- `backend/app/workflows/TRACKED_STEP.md`：workflow 内部 step、progress、run_type 规范

## 继续开发时的纪律

- 不再往 `shared/infra` 根目录塞 DocGen 业务逻辑
- `orchestrators/` 与 `prompt_builders/` 目录都已删除
- 需要业务多步逻辑时，优先放 `workflows/.../runtime`
- 需要状态可视化和中断能力时，优先做 subgraph
- 保持 LangSmith trace 可读，不要把业务细节重新藏回 infra helper
- 所有新增 workflow 节点默认通过 `@traceable_run(..., run_type="chain")` 或 `wrap_traceable_run(..., run_type="chain")` 接入 LangSmith
- 所有新增 prompt builder 默认通过 `@traceable_run(..., run_type="prompt")` 接入 LangSmith
- node 内部关键步骤默认通过 `tracked_step(...)` 接入 LangSmith / runtime stats / progress
- `BaseTracedExecution` 继续作为 workflow-local runtime 单元的统一 traced execution helper
- asset sidecar 必须有独立 span（tag: `asset:{kind}`），不埋在正文节点输出里
- 章节合同优先落在 `confirmed_plan -> assignment -> runtime`，不要只写在 prompt 或文档里
