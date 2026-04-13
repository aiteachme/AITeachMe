# 09. Execution Plan

最后更新：2026-04-13

## 本轮已经落实的关键结果

### 1. 基础边界

- `shared/infra/traced_execution.py` 已成为 canonical traced execution helper。
- `shared/infra/execution.py` 退化为兼容 shim。
- `shared/infra/orchestrators/` 与 `shared/infra/prompt_builders/` 已退出主线设计。
- workflow tracing 已统一收口到 `workflows/common` 的最小 4 入口。

### 2. DocGen runtime 迁移

- `workflows/digest/docgen/runtime/chapter_context.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`

这些 runtime 已承担 DocGen 的 concrete multi-step logic，节点层直接依赖 workflow-local runtime，不再绕回 infra 业务层。

### 3. Skillpack 主流程接入

当前已经落地：

- `selected_skillpacks`
- `prompt_scope`
- `recommended_tool_tags`
- `defaults`
- planner / confirmed plan / docgen state 的贯通
- planner 与 docgen prompt/runtime 对 scoped guidance 的消费

### 4. Toolpack 扩展

当前已经落地：

- `manifest.yaml + handler.py` 扩展模型
- 项目内与用户目录两级扫描
- toolpack handler 真正注册到 canonical registry
- YAML-only 工具目录退化为过渡元信息

### 5. Workflow tracing 收敛

当前已经落地：

- `workflow_tracer(...).node(...)`
- `@traceable_run(...)`
- `tracked_step(...)`
- `run_state_graph(...)`

而且这一套 tracing 不只覆盖 Digest，也已经扩散到 ingest / interact / examine / profile 的 graph 接线层。

## 当前最重要的未完成差距

### 差距 1：retrieval 还缺学科化调权与持久化缓存策略

当前 `retrieval_profile` 已经真实进入执行链，而且 retriever / reader / compression 也已经有最小 runtime cache；剩余重点转成：

- 学科化 profile
- source class 权重
- 持久化 cache 与隔离策略
- micro-loop 调参与收益分析

### 差距 2：课程质量合同还不够强

当前 confirmed plan 和 chapter execution contract 已经存在，但后续还要继续加强：

- richer teaching blocks
- 更细的 repair / quality gate
- 更稳定的 coverage / quality 评估
- 更清晰的 mode-specific 质量阈值

### 差距 3：asset sidecar 还是 MVP

当前 asset sidecar 已进入最小主线，但仍偏轻：

- image 仍偏占位式
- interactive HTML 仍偏模板式
- animation 尚未进入执行链
- richer media planning 还没展开

### 差距 4：跨引擎协同还没进入第二阶段

当前还没有真正完成的协同点包括：

- Interact 复用 Digest 的 `selected_skillpacks` 与课程合同
- Examine 共享更深的章节研究上下文
- Profile 吃到更稳定的课程产物 / 练习 / 交互三方信号

## 下一批开发建议

### 批次 A：retrieval quality

- 学科化 retrieval profile
- source class 调权
- 持久化检索缓存策略
- coverage / stop 条件调优

### 批次 B：content quality

- richer teaching blocks
- 更细 chapter execution contract
- repair / quality gate 强化
- mode-specific 质量分析

### 批次 C：rich media

- richer interactive templates
- image sidecar 真正内容化
- animation 进入首轮执行链的准入条件
- asset planning 与 chapter contract 对齐

### 批次 D：cross-engine convergence

- Interact 共享 selected skillpacks
- Examine 共享 Digest 章节研究上下文
- Profile 对齐 Digest / Examine / Interact 的关键合同字段

## 当前代码检查点

### `shared/infra`

- 保留基础设施、通用 helper、canonical registry、search/llm/tracing
- 继续允许少量兼容 shim 存在
- 不再新增业务 runtime 目录

### `teaching`

- 继续承载教学语义与 teaching-owned 原子工具
- 不新增第二套 registry 或 workflow runtime

### `workflows`

- graph/state/router 继续是主入口
- workflow-local runtime 是业务多步逻辑的落点
- tracing 主入口继续收口在 `workflows/common`

## 验证要求

- skillpack / toolpack 合同测试继续稳定
- workflow runtime trace 测试继续覆盖关键路径
- docgen research / writer / asset / practice 回归测试继续存在
- 非 Digest 引擎行为不被这轮 refactor 破坏
- 文档中的“已落地”描述必须能在代码中找到对应落点

## 一句话结论

当前 execution plan 的核心不是再开新大项，而是把已经打通的链路做深、做稳，并把 Digest 的成熟合同继续向其他引擎扩散。
