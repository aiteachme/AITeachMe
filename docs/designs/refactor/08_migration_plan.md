# 08. Migration Plan

## 总原则

- 只主动改 `digest/docgen + shared extension infrastructure`
- 不重写其他四大引擎
- 先修边界，再迁业务 runtime，再做质量增强

## Phase 0

目标：冻结边界与术语。

交付物：

- `infra / teaching / workflows` 边界文档
- `tool / skillpack / toolpack / workflow runtime` 定义
- 过渡态与目标态两套口径

退出标准：

- 团队不再把 `orchestrators` 当长期落点继续生长
- 所有后续设计都能用同一套术语讨论

## Phase 1

目标：先把 skillpack 变成主流程真实字段。

交付物：

- `SkillpackDefinition` 支持 `prompt_scope`
- `recommended_tool_tags`
- `defaults`
- planner / confirmed plan / docgen state 支持 `selected_skillpacks`
- planner/docgen prompt 接入 skillpack guidance

退出标准：

- `selected_skillpacks` 可通过 API 进入 planner
- confirmed plan 中完整保留
- docgen runtime 能读到并消费

## Phase 2

目标：让“用户自己写 tool 并接入”成为真功能。

交付物：

- `toolpack` loader
- `backend/toolpacks` 与 `~/.atm/toolpacks` 发现规则
- `manifest.yaml + handler.py` handler 绑定
- YAML-only tool 退化为过渡态说明

退出标准：

- 外部 toolpack 可以注册真实工具
- disabled / broken toolpack 不会拖垮主流程
- 同名用户 toolpack 可以覆盖项目内 toolpack

## Phase 3

目标：迁回 DocGen concrete runtime。

交付物：

- `workflows/digest/docgen/runtime/chapter_context.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`
- `shared/infra/traced_execution.py` 成为唯一 traced execution base

退出标准：

- workflow-local runtime trace 命名为 `workflow_runtime.docgen.*`
- `shared/infra/orchestrators/` 目录已删除
- `shared/infra/prompt_builders/` 目录已删除

## Phase 4

目标：增强 DocGen 质量，不改主骨架。

交付物：

- research micro-loop
- asset sidecar
- systematic / sprint 更严格 contract
- 更丰富的公式、图示、交互插槽

退出标准：

- 质量增强不破坏主 graph
- LangSmith trace 仍保持清晰

## 回滚策略

- 每个 phase 独立提交
- 保持顶层 shim 一段时间
- 只在 workflow-local runtime 稳定后再删旧入口引用
