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

## 仍待继续的工作

- research micro-loop
- richer asset sidecar
- systematic / sprint 更细章节 contract
- Interact 共享 selected skillpacks
- 更丰富的教学块与练习块

## 继续开发时的纪律

- 不再往 `shared/infra` 根目录塞 DocGen 业务逻辑
- `orchestrators/` 与 `prompt_builders/` 目录都已删除
- 需要业务多步逻辑时，优先放 `workflows/.../runtime`
- 需要状态可视化和中断能力时，优先做 subgraph
- 保持 LangSmith trace 可读，不要把业务细节重新藏回 infra helper
