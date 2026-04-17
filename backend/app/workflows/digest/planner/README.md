# Planner 链路说明

最后更新：2026-04-17

`digest/planner/` 负责在正式生成知识文档前，产出一份用户可确认的构建方案。当前版本的核心目标是：用原始资料上下文取代摘要预处理，并把一次规划稳定收敛到 3 次 LLM 调用。

## 一句话总览

Planner 现在做的是：先读取资料和历史，再把每份资料的前 10000 tokens 直接拼成原始上下文；随后并行输出可见思考和结构化意图；再用意图里的查询执行检索增强；最后用一次 reason 流式调用同时生成用户可见大纲和系统可解析的计划合同。

## 当前流程

```text
load_planner_materials            # create/append 时顺手落库并装配文件与历史
  -> pack_raw_material_context    # 不调 LLM；每份资料截前 10000 tokens 后拼接
  -> stream_brief_and_extract_intent
       ├─ stream_planner_brief     # reason + SSE，可见第 1 段
       └─ extract_learning_intent   # primary 结构化，同时生成检索查询
  -> retrieve_planning_evidence    # 不调 LLM；用 intent 查询调用本地/外部检索器
  -> stream_and_parse_plan_draft   # reason + SSE，可见第 3 段，同时解析 BuildPlannerDraft
  -> normalize_and_persist_plan    # normalize 后保存 latest_plan 和 assistant turn
```

## LLM 调用合同

一次正常 planner run 只包含 3 个逻辑 LLM 步骤：

| 顺序 | 步骤 | 模型 | 是否展示给前端 | 产物 |
| --- | --- | --- | --- | --- |
| 1 | `stream_planner_brief` | `reason` | 是 | `PlannerBrief` |
| 2 | `extract_learning_intent` | `primary` | 否 | `LearningIntent`，含 `evidence_queries` |
| 3 | `stream_and_parse_plan_draft` | `reason` | 是 | 可见大纲 + `BuildPlannerDraft` JSON |

不再存在的模型调用：

- 资料摘要 light 模型
- 单独证据查询 light 模型
- 最终 compose 的第二次结构化 primary 模型

## 步骤总览

| 顺序 | 节点 | 具体做什么 | 目的 |
| --- | --- | --- | --- |
| 1 | `load_planner_materials` | create 时创建 session/user turn；append 时追加 user turn 并读取历史与文件；随后读取 parsed markdown，生成 `DigestMaterialContext` | 把会话落库纳入真实业务节点 |
| 2 | `pack_raw_material_context` | 将 `source_documents` 逐份按 token 截断并拼接到 `material_context.material_digest`；每份最多前 10000 tokens | 让后续模型直接吃原始上下文，不再先做摘要 |
| 3 | `stream_brief_and_extract_intent` | 并行跑 `stream_planner_brief` 与 `extract_learning_intent` | 前端快速看到规划思考，同时拿到结构化意图和检索查询 |
| 4 | `retrieve_planning_evidence` | 使用 `learning_intent.evidence_queries` 调用全部可用检索器；打开可用来源并压缩成 `EvidenceBrief` | 给最终大纲提供本地/外部概念边界校准 |
| 5 | `stream_and_parse_plan_draft` | 一次 reason 流式调用输出可见整理文本，并在同一响应的 JSON 段解析 `BuildPlannerDraft` | 避免可见输出和最终合同由两次模型各说各话 |
| 6 | `normalize_and_persist_plan` | normalize、fallback merge、标题去重、字段补齐；随后保存 latest plan、assistant turn 与会话状态快照 | 保持外部 API 与 ConfirmedBuildPlan 合同稳定 |

## State 合同

Planner graph state 只保留这些业务字段：

| 字段 | 作用 |
| --- | --- |
| `material_context` | Digest 资料理解包，含原始资料拼接上下文、切片、画像和主题提示 |
| `planner_brief` | 可见思考过程解析后的简表：`markdown / focus_points / outline_items / clarifying_questions` |
| `learning_intent` | 极简学习意图：`goal_type / audience / success_criteria / constraints / evidence_queries / focus_concepts / confidence` |
| `evidence_brief` | 证据包：`queries / sources / summary / core_concepts / chapter_hints / gap_notes / hit counts` |
| `plan_outline_markdown` | 第三次 reason 调用中展示给前端的可见大纲整理文本 |
| `build_plan_draft` | compose 节点从同一次 reason 响应里解析出的未 normalize 草案 |
| `plan` | 对外稳定的最终计划 payload |
| `planner_record / planner_turns` | create/append 工作流返回给 API 的会话快照 |

运行时兼容摘要保留顶层耗时：

- `prepare_ms`
- `context_ms`
- `bootstrap_ms`
- `evidence_ms`
- `compose_ms`
- `finalize_ms`

## 关键实现细节

### `pack_raw_material_context`

文件：`planner/nodes/summarize_material.py`，核心逻辑在 `digest/common/material_digest.py`。

虽然文件名仍沿用历史命名，但节点语义已经不是摘要：

- 不调用任何 LLM
- 每份资料独立截取前 `FILE_CONTEXT_TOKENS = 10000`
- 优先使用 LiteLLM tokenizer 计算 token，失败时退回 `ContextWindowManager` 的 token 估算
- 输出写入 `material_context.material_digest`
- 发 `planner.context.started` 和 `planner.context.ready`

### `stream_brief_and_extract_intent`

内部并行：

- `stream_planner_brief`
  - `model="reason"`
  - token 通过 `token_callback` 流给前端
- `extract_learning_intent`
  - `model="primary"`
  - 输出 `LearningIntent`
  - 同时生成后续检索用的 `evidence_queries`

### `retrieve_planning_evidence`

现在不再生成检索词，也不再调用 LLM。

查询来源按优先级：

1. `learning_intent.evidence_queries`
2. `fallback_probe_queries(material_context, planner_brief)`
3. `user_goal` 或 `subject`

随后调用全部可用检索器，包括 `local_rag` 和外部 retriever，并按配置打开外部 URL。

### `stream_and_parse_plan_draft`

第三次 LLM 调用必须同时输出两段：

1. 用户可见文本：
   - `3. 计划大纲整理：...`
   - `4. 暂定章节方向：...`
2. 系统 JSON 段：
   - 从 `<PLAN_JSON>` 开始
   - 到 `</PLAN_JSON>` 结束
   - 解析为 `BuildPlannerDraft`

流式输出时，后端只把 `<PLAN_JSON>` 之前的可见文本推给前端；JSON 段只用于解析，不展示。

## SSE 事件

当前 Planner 事件包括：

- `planner.material.loading`
- `planner.material.pending`
- `planner.material.ready`
- `planner.context.started`
- `planner.context.ready`
- `planner.thinking.started`
- `planner.thinking.delta`
- `planner.intent.ready`
- `planner.probe.started`
- `planner.sources.triaged`
- `planner.evidence.ready`
- `planner.plan.composing`
- `planner.plan.delta`
- `planner.plan.ready`
- `planner.fallback.used`

同时继续兼容旧 `status/token/done`。
