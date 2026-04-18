# 已落地决策记录

> 本文档记录本轮 refactor 中已经完全落地、不应再反复讨论的关键决策。
> 如需了解实现细节，请直接阅读对应代码。

## 架构边界（已固定）

- `shared/infra` = 基础设施（LLM / observability / storage / search / tools / workflow support）
- `workflows` = 唯一业务层，承接五大业务引擎、graph 编排主体与教学语义
- `support` = `workflows` 下的非引擎业务模块区

## 扩展模型（已固定）

- `tool`：原子动作，统一注册到 canonical tool registry
- `toolpack`：`manifest.yaml + handler.py`，向 canonical registry 注册真实可执行工具

## 三级模型策略（已落地）

| 层级 | 场景 | 优先级 |
| --- | --- | --- |
| `reason` | 规划、子查询生成、Contract 校验、缺口评估 | 推理深度优先 |
| `primary` | 章节写作、题目生成、批改、对话、OCR | 质量均衡 |
| `light` | KG 抽取、标题解析、分类、Mermaid 规划 | 吞吐/成本优先 |

调用纪律：`TaskType` 声明业务语义，`tier` 只在需要速度/质量偏置时显式覆盖。Strict failure 模式，无静默 fallback。

## DocGen Pipeline（已落地）

骨架：`load_context → targeted_research (fan-out) → collect_materials → resolve_titles → pedagogy_craft (fan-out) → collect_drafts → enrich_document → inject_examine → finalize_assemble`

- Workflow-local runtime：`workflows/digest/docgen/runtime/` (chapter_context, writer, assets)
- Confirmed plan contract：typed contract 从 planner 贯通到 docgen
- Prompt 扩展层：已决定移除独立策略层；教学策略回收到 Planner、DocGen 节点和 confirmed plan
- Research：已升级为受控 micro-loop（seed → retrieve → assess → gap → stop）
- Asset sidecar：Mermaid / image / interactive HTML 最小执行链已落地
- Mode awareness：`sprint / systematic` 已进入 contract、research、writer、practice layer

## Workflow Observability（已落地）

统一收口为两层语义：

1. `LangSmith trace` — 给研发排障
2. `progress` — 给前端展示

workflow 作者当前只保留 3 个公开入口：

1. `run_state_graph(...)` / `invoke_state_graph(...)`
2. `workflow_tracer(...).node(handler, ...)`
3. `emit_progress(...)`

prompt / helper tracing 统一直接使用官方 `@traceable`。

补充边界：

- 底层 tracing 的真实实现统一在 `app.shared.infra.observability`
- `app.shared.infra.workflow` 只保留 workflow authoring / runtime / progress 支撑
- `traceable_with_context`、`llm_trace_scope` 等能力保留在 infra-private 边界，不再作为 workflow 公开规范

## Teaching Tools（已落地）

teaching tool 不是第二套工具系统，而是 canonical registry 中带教学语义的原子函数。工具注册语义在 `app.shared.infra.tools.teaching_registry`，通用内置实现位于 `app.shared.infra.tools.builtin.teaching_tools`，执行通过 `app.shared.infra.tools`。
