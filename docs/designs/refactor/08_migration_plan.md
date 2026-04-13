# 08. Migration Plan

最后更新：2026-04-13

## 总原则

- 不重写五大引擎总骨架。
- 优先收敛边界、合同与观测，再继续加深质量。
- 能在现有 workflow graph 内解决的问题，不轻易再新起一套 runtime 体系。
- 每一轮迁移都要明确“已完成 / 部分完成 / 未开始”，避免计划文档和代码状态脱节。

## 当前阶段状态总表

| Phase | 目标 | 当前状态 | 说明 |
| --- | --- | --- | --- |
| Phase 0 | 冻结边界与术语 | 已完成 | `infra / teaching / workflows` 三层边界与 `tool / skillpack / toolpack / workflow runtime` 术语已经固定 |
| Phase 1 | skillpack 进入主流程 | 已完成 | `selected_skillpacks` 已进入 planner -> confirmed plan -> docgen |
| Phase 2 | toolpack 变成真实扩展点 | 已完成 | `manifest.yaml + handler.py` loader 已落地，YAML-only 仅保留过渡语义 |
| Phase 3 | DocGen concrete runtime 回归 workflows | 已完成 | `workflows/digest/docgen/runtime/*` 已成为 canonical runtime 落点 |
| Phase 4 | 在不改主骨架的前提下增强 DocGen 质量 | 进行中 | micro-loop、minimal asset sidecar、mode-aware practice 已落地，但仍需继续做深 |
| Phase 5 | 跨引擎合同收敛 | 未完成 | Interact / Examine / Profile 与 Digest 的更深协同仍待推进 |

## 各阶段的当前判断

### Phase 0：边界冻结

退出标准已经满足：

- 团队不再把 `orchestrators` 当长期目录继续生长。
- `prompt_builders` 不再作为业务 prompt 的 canonical 落点。
- 讨论新能力时，能稳定使用同一套术语。

### Phase 1：skillpack 主流程接入

退出标准已经满足：

- `selected_skillpacks` 可通过 API 进入 planner。
- confirmed plan 会保留 skillpack 选择。
- DocGen 的 `load_context` 与 runtime 能消费 scoped guidance/defaults/tool tags。

### Phase 2：toolpack 扩展模型

退出标准已经基本满足：

- 外部 toolpack 可以注册真实 handler。
- disabled / broken toolpack 不会拖垮主流程。
- YAML-only `backend/tools/*.yaml` 已退化为过渡态元信息，而不再宣称是完整扩展模型。

### Phase 3：DocGen runtime 回归 workflows

退出标准已经满足：

- `workflows/digest/docgen/runtime/*` 已稳定承担 workflow-local 多步逻辑。
- `shared/infra/traced_execution.py` 成为唯一通用 traced execution base。
- trace namespace 已切到 `workflow_runtime.docgen.*`。

### Phase 4：DocGen 质量增强

当前已完成的部分：

- chapter research 已进入 micro-loop
- `requested_profile / applied_profile / research_rounds / source_class_breakdown` 已进入 summary/trace
- retriever / reader / compression 已接入最小 runtime cache
- Mermaid / image / interactive HTML 已进入最小 asset sidecar 主线
- mode-aware practice layer 已接入文档构建链
- workflow tracing 已收敛到最小 4 入口

当前未完成的部分：

- 学科化 retrieval weighting / source class 调权
- 持久化检索、读取、压缩缓存策略
- richer interactive/image sidecar
- animation 真正执行链
- 更细颗粒度的章节质量合同与教学块

### Phase 5：跨引擎合同收敛

这是当前下一阶段最容易被低估、但真正重要的工作：

- Interact 需要进一步复用 Digest 的课程合同与 skillpack 语义。
- Examine 需要和 Digest 更深共享章节研究上下文、教学动作和知识焦点。
- Profile 需要把课程产物、练习结果和交互行为连接成更稳定的画像输入。

## 当前迁移重点

### 重点 1：不要再回头争边界

下面这些结论当前不应再反复讨论：

- DocGen business runtime 放在 `workflows/.../runtime`
- `tool / skillpack / toolpack` 三分模型成立
- workflow tracing 主入口放在 `workflows/common`

### 重点 2：开始从“打通”转向“做深”

当前已经过了最危险的“能力没接起来”阶段。
接下来重点应该转成：

- 质量做深
- 合同做稳
- 跨引擎打通
- dashboard/trace 可比较

### 重点 3：把未完成项写成清晰 backlog，而不是继续写抽象愿景

当前未完成项需要继续写成：

- 学科化 profile 与调权策略
- 持久化 research cache 策略
- richer asset sidecar 设计与验收标准
- Interact / Examine / Profile 的共享合同设计

## 回滚策略

- 继续保持阶段性提交，而不是超大改动混在一起。
- 保留少量顶层兼容 shim，但不再为 legacy 口径新增新功能。
- 回滚优先回滚 workflow-local 增强逻辑，不要先动基础边界。

## 一句话结论

Digest refactor 当前已经完成“基础设施重排 + 主链路打通”。
后续迁移不该再围绕“边界怎么定”打转，而应该转向“质量如何继续做深、跨引擎如何继续收敛”。
