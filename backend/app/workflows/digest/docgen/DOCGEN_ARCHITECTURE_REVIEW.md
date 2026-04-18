# DocGen 架构评估与后续重构判断

最后更新：2026-04-19

适用范围：

```text
backend/app/workflows/digest/docgen/
backend/app/workflows/digest/planner/
backend/app/workflows/digest/common/contracts.py
backend/app/shared/infra/
```

本文档记录当前 `digest/docgen` 的架构评估结论。它不是隐藏推理记录，只保留可验证、可执行、可维护的工程判断。

如果本文档与代码冲突，优先以当前代码和 `README.md`、`FLOW_DESIGN.md` 为准。

## 1. 总体结论

当前 DocGen 主线不需要推倒重来。

真实主线已经从旧的“研究、写作、增强、练习”线性节点，演进成：

```text
load_context
  -> prepare_parallel_inputs
  -> confirm_and_dispatch
  -> build_document_backbone
  -> generate_chapters (Send x N)
  -> enhance_chapters
  -> review_content
  -> repair_or_route
  -> merge_review
  -> finalize_titles
  -> publish_document
```

这条线的方向是对的：先用 Planner 固化用户确认方案，再由 DocGen 细化执行合同、构建知识骨架、按章研究写作、增强表现层、复核、发布结构化产物。

现在不建议做“大拆大建”。更合理的路线是继续补四个闭环：

```text
状态闭环：局部失败和局部修补不污染整本产物
证据闭环：每章主张、证据、来源可追踪
质量闭环：复核后能有限修补，而不是只记录 warning
产物闭环：markdown 之外有 manifest 支撑其他引擎复用
```

## 2. 当前值得保留的设计

### 2.1 Planner 与 DocGen 分离

Planner 负责用户确认级计划，DocGen 只消费 confirmed plan。

保留理由：

- 用户确认前后状态清晰。
- DocGen 不再临时改方向。
- 构建失败可以回溯到 `confirmed_plan_id`。
- 后续增强 Planner research surface 不会打乱 DocGen 执行图。

关键入口：

```text
backend/app/api/knowledge_docs.py
backend/app/workflows/digest/planner/
backend/app/workflows/digest/docgen/builds.py
backend/app/workflows/digest/docgen/graph.py
```

### 2.2 confirmed plan 合同层

`digest/common/contracts.py` 仍是 Planner 和 DocGen 之间最重要的边界。

后续扩展应优先考虑：

- 是否属于用户确认合同。
- 是否属于 DocGen 内部执行合同。
- 是否只是节点运行时 trace。

不要把需要长期维护的字段只塞进节点 dict。

### 2.3 整本文档知识骨架

`build_document_backbone` 已经成为当前主线的一部分。它把章节 seed、文件摘要和高置信证据候选收束为：

- `canonical_glossary`
- `concept_dependency_graph`
- `notation_registry`
- `canonical_claim_pool`
- `confusion_map`
- `source_trust_summary`

这层值得保留，因为它把“按章并行写作”拉回整本一致性，不会让每章各说各话。

### 2.4 主张、证据和冲突账本

当前 `generate_chapters` 已经输出：

- `EvidenceLedger`
- `ClaimLedger`
- `ClaimEvidenceMap`
- `ConflictReport`
- `ChapterResearchTrace`

这比单纯保存 `dense_context` 更有价值。后续 Interact / Examine / Profile 可以复用这些结构，而不是解析 Markdown。

### 2.5 发布级 manifest

`publish_document` 已经把 DocGen artifacts 写入：

```text
knowledge_markdowns/_build/docgen_manifest.json
knowledge_markdowns/docgen_manifest.json
knowledge_markdowns/versions/vXXXX/docgen_manifest.json
```

这是后续跨引擎复用的关键产物，不应因为前端暂时不用而删除。

## 3. 当前重大问题清单

这里只列值得优先关注的问题，普通命名、提示词和样式优化不展开。

### P0. 文档与代码漂移

现状：

- 旧 README 和架构评估曾把旧主线当作当前主线。
- 当前 graph 已经包含 `build_document_backbone`、`review_content`、`repair_or_route`、`finalize_titles`。
- 如果接手者按旧文档开发，很容易把新逻辑补到错误阶段。

影响：

- 架构沟通成本高。
- 后续智能体或开发者容易重复造节点。
- repair loop、manifest、asset 等下一步改造容易走偏。

处理：

- 本次已同步 `README.md`、`FLOW_DESIGN.md`、`REFACTOR_PLAN.md` 和本文档。

验收：

- 文档主线与 `graph.py` 一致。
- 文档明确当前 MVP 缺口，而不是描述已经过时的流程。

### P1. repair_or_route 还不是质量闭环

现状：

- `review_content` 已经能产出 `ReviewAction`。
- `repair_or_route` 当前只做 MVP：轻动作标记、重动作记录 warning。
- graph 仍是一次性路径：

```text
review_content -> repair_or_route -> merge_review
```

影响：

- 复核发现的问题多数不能自动消化。
- `review_actions` 对最终文档质量的提升有限。
- 后续如果直接加循环，state append 字段会带来重复产物风险。

建议：

先做两步：

1. 修正 action 状态语义，不真实 patch 就不要标 `applied`。
2. 扩展 `ReviewAction` 合同，再引入 `RepairLoopState` 和最多两轮路由。

### P1. ReviewAction 合同不足

现状：

`ReviewAction` 主要字段是：

```text
action_id
action_type
chapter_index
severity
reason
status
```

影响：

- repair 层需要靠自然语言 reason 猜修哪里。
- 证据不足被映射成 `regenerate_chapter`，粒度过重。
- 无法稳定实现 targeted patch。

建议新增：

```text
target_anchor
instruction
constraints
expected_effect
```

并补充 `evidence_patch`、`record_only` 类型。

### P1. state reducer 与 repair loop 不兼容

现状：

多个章节产物字段使用 `operator.add`：

```text
chapter_drafts
enhanced_chapter_drafts
research_traces
evidence_ledgers
claim_ledgers
claim_evidence_maps
conflict_reports
asset_manifests
practice_manifests
```

这对一次性 fan-out 很合适，但对 repair loop 和 regenerate chapter 有风险。

影响：

- 重修后的章节可能和旧章节同时存在。
- `merge_review` 如果只按长度或顺序选，很难保证选中最新版本。
- manifest 历史与最终 active 版本容易混淆。

建议：

- 给产物加 `artifact_version` 或 `repair_round`。
- `merge_review` 只消费每章 latest active artifact。
- manifest 同时保留 latest 和 history。

### P1. 图片 disabled manifest 缺失

现状：

- image generation 未启用时，image 请求可能在 plan 阶段被移除。
- `enhance_chapters` 会 strip image 占位。
- `AssetManifest` 看不到 disabled 记录。

影响：

- 用户看到没有图片，但系统无法说明是 disabled、failed 还是 skipped。
- 后续前端或重跑任务缺少资产决策依据。

建议：

- 保留 image intent，但不泄露内部占位符。
- `AssetManifest` 记录：

```text
kind: image
status: disabled
reason: image_generation_disabled
```

### P2. final_merge_patch 尚未实现

现状：

- 合并后才暴露的小问题由 `merge_review` / `finalize_titles` 间接处理。
- 没有独立节点记录 final merge patch。

影响：

- 目录重复、跨章过渡、重复摘要、manifest 小缺字段等问题缺少明确收口点。

建议：

新增 `final_merge_patch`，只修发布级小问题，不检索、不重写章节、不改 claim/evidence。

### P2. 研究预算仍偏静态

现状：

- `ChapterBudgetPolicy` 主要按 `sprint/systematic` 默认值生成。
- 还没有充分利用 local coverage、evidence gap、章节难度动态决策。

影响：

- 资料覆盖充足的章节可能过度检索。
- 证据不足的章节可能检索预算不够精细。

建议：

新增 `ResearchBudgetDecision`，并写入 `research_trace`。

## 4. 不建议现在做的大改

### 4.1 不建议重写整张 DocGen graph

当前阶段边界已经合理。问题主要在回流、合同、manifest 和 state 语义，不在 graph 主线。

### 4.2 不建议把 DocGen 并回 Planner

Planner 是确认面，DocGen 是执行面。二者合并会让确认流程、构建锁、失败恢复和前端状态都变复杂。

### 4.3 不建议优先做完整多 Agent deep research

AITeachMe 的 DocGen 需要的是可控教学文档生成，不是开放式研究代理。多 Agent 动态队列会放大成本、时延和可解释性问题。

### 4.4 不建议让 enhance 修核心知识

`enhance_chapters` 只能处理 Mermaid、图片、交互占位、公式、Markdown 和自检题。核心知识修补必须回到 review/repair。

### 4.5 不建议新增第二套工具系统

检索、reader、tool、workflow、observability 都应继续使用 `shared.infra` 的稳定入口。

## 5. 推荐改造顺序

### Phase 0：文档基线

状态：已完成。

目标：

- 文档与当前 graph 对齐。
- 明确下一步不是补新主线，而是补回流和产物合同。

### Phase 1：修正 repair 状态语义

目标：

- 不真实修改正文时，不标记 `applied`。
- 最小 `repair_trace` 进入 manifest。

收益：

- 低风险。
- 立刻提升调试可信度。

### Phase 2：扩展 ReviewAction

目标：

- 让 action 能驱动定向修补。
- 新增 `evidence_patch` / `record_only`。

收益：

- 为 repair loop 打基础。
- 不强制立刻改 graph。

### Phase 3：有限 repair loop

目标：

- 新增 `RepairLoopState`。
- `review_content` 根据 `review_decision` 路由到 repair 或 merge。
- 最多两轮。

风险：

- 必须先处理 state append 语义，否则容易重复产物。

### Phase 4：章节产物版本化

目标：

- 分清 active artifact 和 history artifact。
- 修补或重写后只发布 latest。

### Phase 5：局部 patch 与 evidence patch

目标：

- 先做 surface / section patch。
- 再做 targeted evidence patch。
- 最后做单章 regenerate。

### Phase 6：asset manifest 收口

目标：

- image disabled / failed / skipped / rendered 状态全部可追踪。

### Phase 7：final_merge_patch

目标：

- 合并后小问题有独立节点收口。

### Phase 8：动态研究预算

目标：

- 按资料覆盖度、证据缺口和章节难度分配预算。

## 6. 修改代码前的检查清单

改 DocGen 前先确认：

- 是否改变 confirmed plan 的章节数量、顺序或语义。
- 是否新增长期字段，是否应放进 `lib/models.py`。
- 是否会影响 `operator.add` fan-in 字段。
- 是否需要写入 `docgen_manifest.json`。
- 是否影响 `KnowledgeDoc.manifest_json`。
- 是否会让 `enhance_chapters` 承担核心知识修补。
- 是否需要更新 `README.md`、`FLOW_DESIGN.md`、`REFACTOR_PLAN.md`。
- 是否触碰前端 Orval 生成目录。

## 7. 验证建议

文档改动：

```text
git diff --check
```

代码改动：

```text
conda run -n atm python -m compileall backend/app/workflows/digest/docgen
```

关键改动额外验证：

```text
graph compile smoke test
小资料 sprint 构建
小资料 systematic 构建
无本地资料 web-first fallback
manifest 字段检查
```

优先补测试的位置：

- `ReviewAction` validate。
- `repair_or_route` 状态语义。
- `asset disabled manifest`。
- `merge_review` latest artifact selection。
- `publish_document` manifest snapshot。

## 8. 后续接手阅读顺序

1. `backend/app/workflows/README.md`
2. `backend/app/workflows/digest/README.md`
3. `backend/app/workflows/digest/planner/README.md`
4. `backend/app/workflows/digest/docgen/README.md`
5. `backend/app/workflows/digest/docgen/FLOW_DESIGN.md`
6. `backend/app/workflows/digest/docgen/graph.py`
7. `backend/app/workflows/digest/docgen/state.py`
8. `backend/app/workflows/digest/docgen/lib/models.py`
9. `backend/app/workflows/digest/docgen/nodes/*.py`
10. `backend/app/workflows/digest/docgen/REFACTOR_PLAN.md`

## 9. 一句话收束

DocGen 当前最重要的不是再发明一条流程，而是把已经成型的主线继续做扎实：

```text
confirmed plan
  -> execution contract
  -> document backbone
  -> evidence-backed chapter generation
  -> content review
  -> bounded repair
  -> publishable manifest
```
