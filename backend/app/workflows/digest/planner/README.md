# Planner V3.3 链路说明

最后更新：2026-04-17

`digest/planner/` 负责在正式生成知识文档前，先产出一份用户可确认的高质量构建方案。当前 V3.3 版本重点解决四件事：

1. 草稿和意图识别必须读到真实资料内容，不再只看文件名和规则 hints。
2. 可见思考过程必须真实使用 `reason` 模型，意图识别走 `light` 模型。
3. 思考过程和最终计划必须吃 few-shot 示例。
4. 前端 Planner 预览必须按 Markdown 正确渲染。

## 一句话总览

Planner V3.3 做的事是：先准备资料理解包，再用 light 模型快速提炼一份"资料摘要"写回理解包，再并行生成可见思考过程和结构化学习意图，然后用 light 模型生成证据查询问题并调用全部可用检索器校准概念边界，最后合成并整理出稳定的构建计划合同。

## 当前流程

```text
prepare_material_context
  -> summarize_material_digest     # light 摘要，短路直拼，长文分片并行
  -> bootstrap_plan_brief
       ├─ stream_plan_sketch       # reason + SSE
       └─ extract_learning_intent  # light 结构化
  -> probe_evidence                # 生成查询问题 + 全部可用检索器
  -> compose_build_plan
  -> finalize_plan_contract
```

## 步骤总览

| 顺序 | 节点 | 具体做什么 | 目的 | 主要模块/工具 |
| --- | --- | --- | --- | --- |
| 1 | `prepare_material_context` | 读取 parsed markdown，生成 `DigestMaterialContext`；没有正文时退化成 seed context | 给后续所有规划步骤一份共享"资料理解包" | `prepare_material_context`、`DigestMaterialContext` |
| 2 | `summarize_material_digest` | 拼接资料原文，总字数 < 10k 直接透传；≥ 10k 按 10k 切片并行走 light 模型摘要（最多 10 片） | 让 sketch/intent/compose 都能基于真实资料内容，而不是只看文件名和 hints | `build_material_digest`、`acompletion` (tier=light) |
| 3 | `bootstrap_plan_brief` | 内部并行跑 `stream_plan_sketch` 和 `extract_learning_intent` | 让前端尽快看到格式稳定的可见思考过程，同时产出结构化意图与外部检索计划 | `acompletion_stream`、`acompletion_with_fallback` |
| 4 | `probe_evidence` | light 模型生成检索问题，调用全部可用检索器；筛选并按配置打开来源 | 给最终大纲提供概念边界、标准定义和本地资料命中校准 | `get_retriever`、`SourceCurator`、`read_urls` |
| 5 | `compose_build_plan` | 综合思考过程、意图、证据和资料理解包，生成结构化 `BuildPlannerDraft` | 一次性生成后续 DocGen 可用的大纲合同 | `BuildPlannerDraft`、`build_plan_composer_messages` |
| 6 | `finalize_plan_contract` | normalize、fallback merge、标题去重、字段补齐 | 保持外部 API 与 ConfirmedBuildPlan 合同稳定 | `normalize_planner_draft`、`build_fallback_plan` |

## 资料理解包

当前主命名是：

- `DigestMaterialContext`
- `material_context`

旧命名仍兼容：

- `SharedInputs`
- `shared_inputs`

主要字段：

| 新字段 | 旧兼容名 | 含义 |
| --- | --- | --- |
| `source_documents` | `source_packets` | 文件级资料 |
| `material_sections` | `section_packets` | 正文切片，供本地检索 |
| `material_hints` | `fast_hints` | 规则提取的主题/题目/公式提示 |
| `material_assets` | `asset_registry` | 图片等资料资产 |
| `learning_domain_profile` | `subject_profile` | 学科画像 |
| `material_stats_profile` | `material_profile` | 材料统计画像 |
| `course_mode_decision` | `digest_mode_decision` | 课程模式建议 |
| `material_digest` | — | light 模型输出的资料快速摘要；< 10k 字时直接是拼接原文 |

## 可见思考输出合同

`stream_plan_sketch` 的输出被强约束为两行可读思考摘要：

```text
1. 关注重点：……
2. 预计计划大纲：……
```

硬约束：

- 只能输出两条编号内容：关注重点、预计计划大纲。
- 不允许输出 Markdown 标题、网站名、来源标题、`subj_xxx`、代码块或 JSON。
- few-shot 示例会明确约束格式和风格。

## Few-shot 示例

Planner 现在通过 `planner/prompts/examples.py` 注入示例。

已覆盖：

- `sprint + exam-heavy`
- `sprint + concept-heavy`
- `systematic + textbook-heavy`
- `systematic + mixed-notes`

示例用于：

- `stream_plan_sketch`
- `compose_build_plan`

## 节点细节

### `prepare_material_context`

文件：`planner/nodes/prepare_material_context.py`

做什么：

- 调 `digest/common/prepare.py::prepare_material_context(...)`
- 生成 `material_context`
- 无正文时生成 seed context
- 发 `planner.material.ready`

### `summarize_material_digest`

文件：`planner/nodes/summarize_material.py`（核心逻辑在 `digest/common/material_digest.py`）

做什么：

- 把 `material_context.source_documents` 按 `===== filename =====\n` 拼接
- 总字符数 < 10000 → 直接把拼接结果写入 `material_digest`，不调 LLM
- ≥ 10000 → 按每片 10000 字切，最多 10 片，`asyncio.gather` 并行走 `tier="light"` + `TaskType.SUMMARIZE` 的快速摘要模型
- 每片输出 150-250 字要点型段落，最终以 "段1：...\n\n段2：..." 合并写回 `material_context.material_digest`
- 发 `planner.digest.started` 和 `planner.digest.ready`

### `bootstrap_plan_brief`

节点名：`bootstrap_plan_brief`

实现文件：`planner/nodes/bootstrap_plan_brief.py`

内部并行：

- `stream_plan_sketch`
  - 真实走 `TaskType.REASONING`
  - 输出可见思考过程 markdown
  - token 通过旧 `token_callback` 流给前端
- `extract_learning_intent`
  - 走 `light`
  - 输出 `LearningIntentProfile`

### `probe_evidence`

节点名：`probe_evidence`

实现文件：`planner/nodes/probe_evidence.py`

做什么：

- 用 light 模型生成证据查询问题
- 调用全部可用检索器，包括 `local_rag` 和外部 retriever
- 先筛选来源，再按 `settings.planner.evidence_open_source_limit` 打开外部 URL
- 输出 `EvidenceBrief`

### `compose_build_plan`

节点名：`compose_build_plan`

实现文件：`planner/nodes/compose_build_plan.py`

做什么：

- 吃 few-shot、思考过程、意图、证据、资料理解包
- 一次性生成结构化 `BuildPlannerDraft`

### `finalize_plan_contract`

文件：`planner/nodes/finalize_plan_contract.py`

做什么：

- normalize
- fallback merge
- 标题去重
- 默认值补齐

不会再额外调用一次标题 LLM。

## 前端预览渲染

当前 Planner 预览不再用 `BuildPlanPage.tsx` 里的字符串切割逻辑。

已改为：

- 新增 `PlannerPreviewMarkdown.tsx`
- 直接复用 `MarkdownViewer`
- 新增 `variant="planner"`

这意味着：

- 草稿预览按 Markdown 正确渲染
- 标题、blockquote、ordered list、二级标题都能稳定显示
- 不会再因为格式稍变导致标题/任务列表错位

## SSE 事件

当前 Planner 事件包括：

- `planner.material.loading`
- `planner.material.pending`
- `planner.material.ready`
- `planner.digest.started`
- `planner.digest.ready`
- `planner.sketch.started`
- `planner.sketch.delta`
- `planner.intent.ready`
- `planner.probe.started`
- `planner.sources.triaged`
- `planner.evidence.ready`
- `planner.plan.composing`
- `planner.plan.ready`
- `planner.fallback.used`

同时继续兼容旧 `status/token/done`。
