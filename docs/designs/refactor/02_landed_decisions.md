# 已落地决策记录

> 本文档记录本轮 refactor 中已经完全落地、不应再反复讨论的关键决策。
> 如需了解实现细节，请直接阅读对应代码。

## 架构边界（已固定）

- `shared/infra` = 基础设施（LLM / tracing / storage / search / tools / skills）
- `teaching` = 教学语义（脚手架、表达块、teaching-owned 原子工具）
- `workflows` = graph + workflow-local runtime + workflow tracing 主入口

## 扩展模型（已固定）

- `tool`：原子动作，统一注册到 canonical tool registry
- `skillpack`：`SKILL.md` prompt strategy package，不执行代码
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
- Skillpack：`selected_skillpacks` 已打通 planner → confirmed plan → docgen
- Research：已升级为受控 micro-loop（seed → retrieve → assess → gap → stop）
- Asset sidecar：Mermaid / image / interactive HTML 最小执行链已落地
- Mode awareness：`sprint / systematic` 已进入 contract、research、writer、practice layer

## Workflow Tracing（已落地）

统一收口为 4 个入口：

1. `run_state_graph(...)` — graph 执行
2. `workflow_tracer(...).node(...)` — node 装饰
3. `@traceable_run(...)` — 稳定 prompt/helper/retriever
4. `tracked_step(...)` — node 内部子步骤

## Teaching Tools（已落地）

teaching tool 不是第二套工具系统，而是 canonical registry 中带教学语义的原子函数。注册在 `app.teaching.tools`，执行通过 `app.shared.infra.tools`。
