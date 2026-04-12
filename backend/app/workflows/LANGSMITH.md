# LangSmith 全链路可观测性指南

> 本文档基于当前代码实现，详细说明 AITeachMe 在 LangSmith 上的 trace 结构、每层的输入输出、metadata 和 tags。
> 目标：让开发者打开 LangSmith 后能立刻理解每个 span 是什么、为什么在那里、记录了什么。

---

## 1. 启用条件

LangSmith tracing 需要同时满足三个条件（见 `shared/infra/tracing.py:langsmith_tracing_enabled`）：

1. `config.yaml` 中 `observability.tracing_enabled: true`
2. `config.yaml` 中 `langsmith.tracing: true`
3. 环境变量 `LANGSMITH_API_KEY` 或 `LANGCHAIN_API_KEY` 已设置

项目名由 `langsmith.project` 配置，默认 `AITeachMe`。

---

## 2. Trace 树总览

一次完整的 Digest DocGen 构建在 LangSmith 中呈现为如下层级：

```
API / Service 调用
└── [workflow root] langsmith_tracing_scope (digest.unified / digest.docgen)
    │
    ├── [node span] unified.prepare_shared          ← wrap_workflow_node 创建
    │
    ├── [node span] docgen.load_context             ← wrap_digest_node → wrap_workflow_node
    │
    ├── [node span] docgen.targeted_research        ← 每章一个 (fan-out via Send)
    │   └── [runtime span] workflow_runtime.docgen.research   ← BaseTracedExecution.run
    │       ├── [llm span] generate_sub_queries     ← acompletion_with_fallback
    │       ├── [retriever calls]                   ← 各 retriever 的调用
    │       ├── [reader calls]                      ← read_urls
    │       ├── [runtime metadata] research_rounds  ← round/gap/coverage 在 runtime metadata 中展开
    │       └── [llm span] purify_material          ← 可选的 LLM 精炼
    │
    ├── [node span] docgen.collect_materials
    ├── [node span] docgen.resolve_titles
    │
    ├── [node span] docgen.pedagogy_craft           ← 每章一个 (fan-out via Send)
    │   └── [runtime span] workflow_runtime.docgen.writer    ← BaseTracedExecution.run
    │       └── [llm span] chapter_write            ← acompletion_with_fallback
    │
    ├── [node span] docgen.collect_drafts
    ├── [node span] docgen.enrich_document
    │   └── [runtime span] workflow_runtime.docgen.assets    ← 可选
    │       ├── [llm span] mermaid_generation
    │       ├── [runtime span] image_placeholder
    │       └── [runtime span] interactive_placeholder
    │
    ├── [node span] docgen.inject_examine
    ├── [node span] docgen.finalize_assemble
    │
    ├── [node span] kg.acquire_lock                 ← KG lane (并行)
    ├── [node span] kg.prepare
    ├── [node span] kg.extract                      ← 每 chunk 的 LLM 抽取
    ├── ...
    │
    └── [node span] unified.publish_outputs
```

关键原则：
- **node span** = LangGraph 图中的一个节点，由 `wrap_workflow_node` 创建
- **runtime span** = 节点内部的多步业务逻辑，由 `BaseTracedExecution.run` 创建
- **llm span** = 单次 LLM 调用，由 LiteLLM/LangSmith 自动捕获
- fan-out 节点（`targeted_research`、`pedagogy_craft`）每章产生独立的 node span

---

## 3. 三层 Span 详解

### 3.1 Node Span（节点层）

**创建者**：`wrap_workflow_node()` in `workflows/common/observability.py`

**Span 名称格式**：`{lane}.{node_name}`
- 例：`docgen.targeted_research`、`kg.extract`、`unified.prepare_shared`

**run_type**：`"chain"`

**Inputs 记录内容**（由 `_node_trace_inputs` 从 state 中提取）：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `subject` | state | 学科/主题名 |
| `build_session_id` | state | 本次构建会话 ID |
| `planner_session_id` | state | Planner 会话 ID |
| `confirmed_plan_id` | state | 已确认方案 ID |
| `digest_mode` | state | `sprint` / `systematic` |
| `course_type` | state | 课程类型 |
| `retrieval_profile` | state | 检索策略 |
| `teaching_action` | state | 教学动作（如 `chapter_research`、`chapter_write`） |
| `asset_kind` | state | 资产类型 |
| `tone` | state | 写作语气 |
| `session_id` / `job_id` / `user_id` | state | 其他引擎的会话标识 |
| `chapter_index` | state 或 `chapter_assignment.chapter_index` | fan-out 章节索引 |
| `chapter_count` | `len(state["chapter_assignments"])` | 章节总数（列表字段自动计数） |

列表字段会自动转为计数值（`_COUNT_FIELDS` 映射），例如：
- `file_ids` → `file_count`
- `chapter_materials` → `chapter_material_count`
- `chapter_drafts` → `chapter_draft_count`

**Outputs 记录内容**（由 `_node_trace_outputs` 从节点返回值中提取）：

| 字段 | 说明 |
| --- | --- |
| `elapsed_ms` | 节点执行耗时（毫秒） |
| `status` | `"ok"` 或 `"failed"` |
| `output_keys` | 返回字典的所有 key 列表 |
| `*_ms` | 所有以 `_ms` 结尾的计时字段 |
| `source_count` | 来源总数 |
| `local_hits` / `web_hits` | 本地/外部命中数 |
| `fallback_used` | 是否使用了 fallback 检索 |
| `word_count` | 章节草稿总字数 |
| `final_word_count` | 最终文档字数 |
| `retriever_names` / `retriever_count` | 使用的检索器名称和数量 |
| `compression_mode` | 压缩模式 |
| `error` | 错误信息（如有） |

**Metadata**（由 `_node_trace_metadata` 提取，附加到 LangSmith span）：

从 state 中提取以下字段（非空时）：
`planner_session_id`、`confirmed_plan_id`、`digest_mode`、`course_type`、
`retrieval_profile`、`teaching_action`、`asset_kind`、`session_id`、
`job_id`、`user_id`、`file_id`、`exam_paper_id`、`chapter_index`

**Tags**（由 `_node_trace_tags` 生成）：

固定 tags：
- `aiteachme`
- `workflow:{workflow_name}`（如 `workflow:digest.docgen`）
- `lane:{lane}`（如 `lane:docgen`）
- `node:{lane}.{node_name}`（如 `node:docgen.targeted_research`）

动态 tags（非空时追加）：
- `mode:{digest_mode}`（如 `mode:systematic`）
- `course:{course_type}`（如 `course:systematic`）
- `retrieval:{retrieval_profile}`（如 `retrieval:docgen_systematic`）
- `teaching:{teaching_action}`（如 `teaching:chapter_research`）
- `asset:{asset_kind}`（如 `asset:mermaid`）
- `chapter:{chapter_index}`（如 `chapter:0`）

**附加行为**：
- 自动记录 `node_timings_ms` 到 state（累积各节点耗时）
- 自动记录 `node_events` 到 state（最近 64 条节点事件）
- 如果 state 中有 `progress_callback`，自动触发进度回调

---

### 3.2 Runtime Span（业务运行单元层）

**创建者**：`BaseTracedExecution.run()` in `shared/infra/traced_execution.py`

**Span 名称格式**：`{trace_namespace}.{trace_name}`
- 例：`workflow_runtime.docgen.research`、`workflow_runtime.docgen.writer`、`workflow_runtime.docgen.assets`

**run_type**：`"chain"`

**嵌套关系**：Runtime span 嵌套在 node span 内部。例如 `docgen.targeted_research` 节点内部会创建 `workflow_runtime.docgen.research` 的 runtime span。

**Inputs**：传入 `execute(**kwargs)` 的所有关键字参数。

**Outputs**（由 `_traced_execution_outputs` 从 `TracedExecutionResult` 中提取）：

| 字段 | 说明 |
| --- | --- |
| `content_length` | 生成内容的字符长度 |
| `source_count` | 来源数量 |
| `image_count` | 图片数量 |
| `metadata_keys` | result.metadata 的所有 key 列表 |
| `local_hits` / `web_hits` | 本地/外部命中数 |
| `query_count` | 执行的查询数 |
| `read_url_count` | 读取的 URL 数 |
| `document_count` | 处理的文档数 |
| `research_round_count` | research 微循环轮次数 |
| `curated_source_count` | 筛选后的来源数 |
| `trusted_source_count` | 可信来源数 |
| `fallback_used` / `purify_used` | 是否使用了 fallback/精炼 |
| `requested_profile` / `applied_profile` | 请求 / 实际执行的 profile |
| `coverage_score` | 当前运行单元的覆盖分 |
| `quality_score` | 当前运行单元的质量分 |
| `gap_count` | 剩余 gap 数 |
| `source_class_breakdown` | 来源类别分布 |
| `compression_mode` | 压缩模式 |
| `applied_retrieval_profile` | 实际执行的检索 profile |
| `retriever_names` | 使用的检索器列表 |
| `retriever_call_count` | 检索器调用总次数 |
| `configured_retriever_count` | 配置的检索器数 |
| `active_retriever_count` | 实际激活的检索器数 |

**Metadata**（由 `TracedExecutionContext.trace_metadata()` 生成）：

核心业务字段（非空时写入）：

```
planner_session_id    ← Planner 会话 ID
confirmed_plan_id     ← 已确认方案 ID
digest_mode           ← sprint / systematic
course_type           ← 课程类型
retrieval_profile     ← 检索策略
teaching_action       ← 教学动作
asset_kind            ← 资产类型（mermaid/image/...）
chapter_index         ← 章节索引
```

Runtime 层额外注入的 metadata：

```
traced_unit_name      ← 运行单元类名（如 DocGenResearchRuntime）
trace_namespace       ← 命名空间（如 workflow_runtime.docgen）
trace_name            ← 运行单元名（如 research）
```

各运行单元在 `execute()` 内部的 LLM 调用还会追加：

```
runtime_name          ← 运行单元类名
research_stage        ← 研究阶段（如 plan_sub_queries / purify_material）
template_kind         ← 资产 sidecar 模板类型（如 formula_expander / concept_check）
```

**Tags**：

固定 tags：
- `aiteachme`
- `workflow:{workflow_name}`
- `lane:{lane}`
- `node:{trace_namespace}.{trace_name}`
- `{trace_namespace}:{trace_name}`（如 `workflow_runtime.docgen:research`）

动态 tags（同 node span）：
- `mode:{digest_mode}`
- `course:{course_type}`
- `retrieval:{retrieval_profile}`
- `teaching:{teaching_action}`
- `asset:{asset_kind}`
- `chapter:{chapter_index}`

**LLM Trace Scope**：Runtime span 内部通过 `llm_trace_scope()` 设置环境上下文，使得所有嵌套的 LLM 调用自动继承 `(subject, build_session_id, workflow, lane, node)` 五元组。

---

### 3.3 LLM Span（模型调用层）

**创建者**：LiteLLM + LangSmith 自动集成（通过 `langsmith.tracing_context` 环境）

LLM span 不需要手动创建。当 `llm_trace_scope` 和 `langsmith_tracing_scope` 处于活跃状态时，所有通过 `acompletion_with_fallback()` 发起的 LLM 调用会自动被 LangSmith 捕获为子 span。

**自动记录的内容**：

| 字段 | 说明 |
| --- | --- |
| `model` | 实际使用的模型名（如 `qwen-plus-latest`） |
| `prompt` / `messages` | 发送给模型的完整 prompt（受 `langsmith.capture_inputs` 控制） |
| `completion` | 模型返回的完整响应（受 `langsmith.capture_outputs` 控制） |
| `token_usage` | prompt_tokens / completion_tokens / total_tokens |
| `latency` | 调用耗时 |

**隐私控制**（`config.yaml`）：

```yaml
langsmith:
  capture_inputs: true    # 是否记录输入文本，null = 本地 true / 云端 false
  capture_outputs: true   # 是否记录输出文本
  max_text_chars: 2000    # 单段文本保留上限
```

`_sanitize_langsmith_metadata_value()` 会自动：
- 截断超长文本到 `max_text_chars`
- 脱敏 `data:` 开头的 URL（替换为 `[redacted:data-url]`）
- 过滤空值

**Tier 与 Fallback 追踪**：

`acompletion_with_fallback()` 在 LLM span 的 metadata 中记录：

| 字段 | 说明 |
| --- | --- |
| `llm_tier` | 请求的层级（`strategic` / `smart` / `fast`） |
| `llm_candidate_tier` | 当前候选的层级 |
| `llm_candidate_task_type` | 当前候选的 TaskType |
| `llm_fallback_from` | 降级前的模型 |
| `llm_fallback_to` | 降级后的模型 |

这使得在 LangSmith 中可以清楚看到：哪些调用发生了降级、从哪个模型降到了哪个模型。

---

### 3.4 本地观测层（非 LangSmith）

除了 LangSmith 外，系统还维护了一套内存中的观测数据：

**LLMCallTracker**（`shared/infra/tracing.py`）：

每次 LLM 调用都会记录一条 `LLMCallRecord`：

```python
@dataclass
class LLMCallRecord:
    task_type: str          # TaskType 值
    model: str              # 模型名
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_s: float
    success: bool
    subject: str            # 继承自 llm_trace_scope
    build_session_id: str
    workflow: str
    lane: str
    node: str
```

通过 `get_tracker().get_summary(...)` 可以按 `build_session_id` / `subject` / `workflow` / `lane` / `node` 过滤，获取：
- 总调用数、失败数、token 用量
- 按模型/TaskType/lane/node 的 token 分布
- 轻量模型 vs 重量模型的调用比例
- 模型混合比例（`model_mix_ratio`）

**Digest 观测摘要**（`workflows/digest/observability.py`）：

`build_token_summary()` 在构建完成后生成完整的 token 使用报告，包含：
- 各 lane 的 token 分布
- 最慢的 chunk/章节排名（`timing_top_k` 配置）
- 模型使用比例

---

## 4. 各引擎 Trace 详解

### 4.1 Digest Unified（统一构建）

**Graph**：`digest/unified/graph.py`
**Workflow name**：`digest.unified`
**Lane**：`unified`

| Node Span | 说明 | 关键 Outputs |
| --- | --- | --- |
| `unified.prepare_shared` | 准备共享输入、物化文档/chunks/embeddings | `digest_mode`、`course_type`、`file_count` |
| `unified.run_parallel_lanes` | 并行运行 DocGen + KG lane | `docgen_status`、`kg_status` |
| `unified.derive_curriculum` | 从 KG impact 推导课程体系（仅 graph_ready 时） | `curriculum_version` |
| `unified.publish_outputs` | 发布文档到 DB/存储 | `published_doc_count` |
| `unified.cleanup` | 清理 build session mailbox | — |

注意：`run_parallel_lanes` 内部会启动完整的 DocGen 和 KG 子图，它们的 trace 会作为嵌套子树出现。

### 4.2 Digest DocGen（文档生成）

**Graph**：`digest/docgen/graph.py`
**Workflow name**：`digest.docgen` 或 `digest.docgen.langgraph_dev`
**Lane**：`docgen`

#### 完整节点链与 trace 内容

**`docgen.load_context`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 加载 confirmed plan、解析 skillpacks、构建 document_context |
| Inputs | `subject`、`build_session_id`、`confirmed_plan_id`、`digest_mode` |
| Outputs | `chapter_count`、`course_type`、`retrieval_profile`、`has_confirmed_plan` |
| 关键判断 | 如果缺少 `confirmed_plan` 则直接报错 |

**`docgen.targeted_research`**（fan-out，每章一个 span）

| 维度 | 内容 |
| --- | --- |
| 作用 | 为单章执行检索、抓取、压缩、精炼 |
| Inputs | `chapter_index`、`teaching_action=chapter_research`、`retrieval_profile` |
| 内嵌 Runtime | `workflow_runtime.docgen.research` |
| Runtime Outputs | `local_hits`、`web_hits`、`query_count`、`curated_source_count`、`compression_mode`、`requested_profile`、`applied_profile`、`research_round_count`、`coverage_score`、`gaps_remaining`、`source_class_breakdown`、`retriever_names`、`fallback_used`、`purify_used` |
| 内嵌 LLM 调用 | `generate_sub_queries`（stage: `plan_sub_queries`）、`purify_material`（stage: `purify_material`，可选） |

Research Runtime 的完整 metadata 输出（写入 `TracedExecutionResult.metadata`）：

```
local_hits, web_hits, query_count, base_queries, planned_queries,
fallback_queries, fallback_used, executed_queries, read_url_count,
document_count, requested_profile, applied_profile,
requested_retrieval_profile, applied_retrieval_profile, configured_retrievers,
active_retrievers, compression_mode, purify_used, curated_source_count,
trusted_source_count, local_source_count, web_source_count,
unique_domain_count, top_domains, retriever_stats, research_rounds,
research_round_count, coverage_score, gaps_remaining, source_class_breakdown,
stop_reason, source_details, selected_skillpacks, recommended_tool_tags
```

**`docgen.collect_materials`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 汇总所有章节的研究材料 |
| Outputs | `chapter_material_count`、`source_count`、`local_hits`（汇总） |

**`docgen.resolve_titles`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 用 LLM 为每章解析更精确的标题 |
| 内嵌 LLM | `TaskType.DOCGEN_LIGHT`、`tier=fast`、`max_tokens=48` |
| Outputs | 每章的 `resolved_title` |

**`docgen.pedagogy_craft`**（fan-out，每章一个 span）

| 维度 | 内容 |
| --- | --- |
| 作用 | 为单章生成教学文档 |
| Inputs | `chapter_index`、`teaching_action=chapter_write`、`retrieval_profile` |
| 内嵌 Runtime | `workflow_runtime.docgen.writer` |
| Runtime Outputs | `content_length`、`source_count`、`coverage_score`、`quality_score`、`repair_applied` |
| 内嵌 LLM | `TaskType.DOCGEN`、`tier=smart` |
| 后处理 | `ensure_chapter_learning_scaffold()` + mode contract repair + media placeholder enforcement |

**`docgen.collect_drafts`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 汇总草稿、合并 markdown、生成目录 |
| Outputs | `word_count`（汇总）、`staged_chapter_count` |

**`docgen.enrich_document`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 富媒体增强：Mermaid 展开、图片占位、interactive_html sidecar、LaTeX 规范化、参考文献 |
| 内嵌 Runtime | `workflow_runtime.docgen.assets`（可选） |
| Outputs | `mermaid_count`、`image_count`、`interactive_count`、`formula_block_count`、`final_word_count` |
| 内嵌 LLM | Mermaid 生成用 `TaskType.DOCGEN_LIGHT`、`tier=fast` |

**`docgen.inject_examine`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 注入 digest-local 的模式感知 practice layer（冲刺课偏高频题型/自检，系统课偏理解/推理/迁移） |
| Outputs | `question_count`、`practice_count` |

**`docgen.finalize_assemble`**

| 维度 | 内容 |
| --- | --- |
| 作用 | 暂存或发布最终文档 |
| Outputs | `published_doc_count`、`final_word_count` |

### 4.3 Digest KG（知识图谱）

**Graph**：`digest/kg/graph.py`
**Lane**：`kg`

| Node Span | 说明 | 关键 Outputs |
| --- | --- | --- |
| `kg.acquire_lock` | 获取学科构建锁 | `lock_acquired` |
| `kg.prepare` | 从 unified session 获取物化 chunks | `chunk_count` |
| `kg.extract` | 并行抽取实体/关系候选（每 chunk 一次 LLM） | `candidate_count`、`slowest_chunks` |
| `kg.cluster` | 基于 embedding 的候选聚类 | `cluster_count` |
| `kg.resolve_nodes` | 与已有节点匹配/合并/新建 | `resolved_node_count`、`new_node_count` |
| `kg.resolve_edges` | 端点解析、边创建/更新 | `resolved_edge_count` |
| `kg.analyze_impact` | 计算影响范围（课程体系重建范围） | `affected_unit_count` |
| `kg.finalize_graph` | 激活实体、发布 topic snapshot | `graph_ready`、`topic_anchor_count` |

KG extract 节点的 LLM 调用使用 `TaskType.EXTRACT`，并有 fast-path 和 topic-fallback 两种降级策略。

### 4.4 Digest Planner（规划器）

**Graph**：`digest/planner/graph.py`
**Lane**：`planner`

| Node Span | 说明 | 关键 Outputs |
| --- | --- | --- |
| `planner.load_context` | 准备共享输入、设置 `teaching_action=plan_course` | `digest_mode`、`course_type` |
| `planner.ground_concepts` | 用本地/Web 锚点丰富主题提示 | `topic_hint_count` |
| `planner.draft_plan` | 流式生成快速方案（`TaskType.DOCGEN_LIGHT`，`max_tokens=260`） | `chapter_count`、`plan_preview` |

Planner 的 LLM 调用通过 `acompletion_stream()` 流式输出，token 通过 `token_callback` 实时推送到前端。

### 4.5 Digest Curriculum（课程体系推导）

**Graph**：`digest/curriculum/graph.py`
**Lane**：`curriculum`

从 KG 的 `ImpactSet` 出发，推导主题树、前置依赖 DAG、教学单元。仅在 KG `graph_ready=true` 时执行。

### 4.6 其他引擎

所有引擎都使用相同的 `wrap_workflow_node` 机制，trace 结构一致。

**Interact（伴读引擎）**：
- Workflow name：`interact`
- 主要 trace 内容：对话历史、检索上下文、tool calling、流式响应

**Examine（诊断引擎）**：
- 包含 `examine_question_build`（题目生成）和 `examine_exam_grade`（评分）两个子图
- 题目生成的 trace 包含：题型分布、知识点覆盖、难度分级

**Profile（显影引擎）**：
- 包含 mastery 更新、review 调度、weakness 排序、summary 刷新
- trace 中可看到 `mastery_updated`、`review_scheduled`、`weaknesses_ranked`

---

## 5. Metadata 全局字典

以下是所有可能出现在 LangSmith metadata 中的业务字段汇总：

### 5.1 基础字段（所有 span 都带）

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `app` | 固定值 `aiteachme-backend` | 应用标识 |
| `app_version` | `settings.app_version` | 应用版本 |
| `subject` | state / context | 学科/主题 |
| `build_session_id` | state / context | 构建会话 ID |
| `workflow` | `WorkflowContext.workflow_name` | 工作流名（如 `digest.docgen`） |
| `lane` | graph 定义时指定 | 泳道名（如 `docgen`、`kg`、`unified`） |
| `node` | graph 定义时指定 | 节点名（如 `docgen.targeted_research`） |

### 5.2 业务上下文字段（非空时写入）

| 字段 | 典型值 | 说明 |
| --- | --- | --- |
| `planner_session_id` | UUID | Planner 会话标识 |
| `confirmed_plan_id` | UUID | 已确认方案标识 |
| `digest_mode` | `sprint` / `systematic` | 消化模式 |
| `course_type` | `sprint` / `systematic` | 课程类型 |
| `retrieval_profile` | `docgen_sprint` / `docgen_systematic` / `planner_grounding` | 检索策略 |
| `teaching_action` | `chapter_research` / `chapter_write` / `plan_course` / `docgen_build` | 教学动作 |
| `asset_kind` | `mermaid` / `image` / `interactive_html` / `animation` | 资产类型 |
| `chapter_index` | `0`, `1`, `2`... | 章节索引（fan-out 追踪） |
| `tone` | `encouraging` / `professional` / `concise` | 写作语气 |

### 5.3 Runtime 专属字段

| 字段 | 说明 |
| --- | --- |
| `traced_unit_name` | 运行单元类名（如 `DocGenResearchRuntime`） |
| `trace_namespace` | 命名空间（如 `workflow_runtime.docgen`） |
| `trace_name` | 运行单元名（如 `research`） |
| `runtime_name` | 同 `traced_unit_name`，在 LLM 调用时传入 |
| `research_stage` | 研究阶段（`plan_sub_queries` / `purify_material`） |

### 5.4 LLM Tier 字段

| 字段 | 说明 |
| --- | --- |
| `llm_tier` | 请求层级 |
| `llm_candidate_tier` | 当前候选层级 |
| `llm_candidate_task_type` | 当前候选 TaskType |
| `llm_fallback_from` | 降级前模型 |
| `llm_fallback_to` | 降级后模型 |

### 5.5 其他引擎字段

| 字段 | 引擎 | 说明 |
| --- | --- | --- |
| `session_id` | interact / examine | 对话/考试会话 |
| `job_id` | kg / ingest | 任务 ID |
| `user_id` | 全局 | 用户标识 |
| `file_id` | ingest | 文件 ID |
| `exam_paper_id` | examine | 试卷 ID |

---

## 6. Tags 全局字典

Tags 用于在 LangSmith 中快速过滤和分组 trace。

### 6.1 固定 Tags

| Tag | 说明 |
| --- | --- |
| `aiteachme` | 全局标识，所有 span 都带 |
| `workflow:{name}` | 工作流名，如 `workflow:digest.docgen` |
| `lane:{name}` | 泳道名，如 `lane:docgen`、`lane:kg` |
| `node:{lane}.{node}` | 节点全名，如 `node:docgen.targeted_research` |

### 6.2 动态 Tags（非空时追加）

| Tag 格式 | 示例 | 用途 |
| --- | --- | --- |
| `mode:{digest_mode}` | `mode:systematic` | 按消化模式过滤 |
| `course:{course_type}` | `course:sprint` | 按课程类型过滤 |
| `retrieval:{profile}` | `retrieval:docgen_systematic` | 按检索策略过滤 |
| `teaching:{action}` | `teaching:chapter_research` | 按教学动作过滤 |
| `asset:{kind}` | `asset:mermaid` | 按资产类型过滤 |
| `chapter:{index}` | `chapter:0` | 按章节索引过滤 |

### 6.3 Runtime 专属 Tags

| Tag 格式 | 示例 | 说明 |
| --- | --- | --- |
| `{namespace}:{name}` | `workflow_runtime.docgen:research` | 标识具体运行单元 |

---

## 7. 实际使用场景

### 7.1 定位某次构建的完整 trace

在 LangSmith 中搜索：
- **Filter by tag**: `aiteachme` + `workflow:digest.unified`
- **Filter by metadata**: `build_session_id = <your_id>`

你会看到完整的 unified 构建树，包含所有子节点。

### 7.2 对比 sprint vs systematic 的研究质量

1. Filter by tag: `course:sprint` 或 `course:systematic`
2. 选择 `docgen.targeted_research` 节点
3. 对比 outputs 中的：
   - `local_hits` vs `web_hits`（来源分布）
   - `curated_source_count`（筛选后来源数）
   - `compression_mode`（压缩策略）
   - `applied_retrieval_profile`（实际检索策略）

### 7.3 追踪某章的研究 → 写作全链路

1. Filter by tag: `chapter:2`（第 3 章）
2. 你会看到两个主要 span：
   - `docgen.targeted_research`（研究阶段）
   - `docgen.pedagogy_craft`（写作阶段）
3. 展开研究阶段，可以看到：
   - `workflow_runtime.docgen.research` runtime span
   - 内部的 `generate_sub_queries` 和 `purify_material` LLM 调用
4. 展开写作阶段，可以看到：
   - `workflow_runtime.docgen.writer` runtime span
   - 内部的章节写作 LLM 调用

### 7.4 分析 LLM 降级情况

1. 在 LangSmith 中搜索包含 `llm_fallback_from` metadata 的 span
2. 查看 `llm_tier`、`llm_fallback_from`、`llm_fallback_to` 字段
3. 统计哪些节点最容易发生降级

### 7.5 检查富媒体生成效果

1. Filter by tag: `asset:mermaid` 或 `asset:image`
2. 查看 `enrich_document` 节点的 outputs：
   - `mermaid_count`、`image_count`
   - `asset_failures`（如有）

---

## 8. 代码对照表

| 功能 | 代码位置 | 说明 |
| --- | --- | --- |
| LangSmith 启用判断 | `shared/infra/tracing.py:langsmith_tracing_enabled` | 三条件检查 |
| 创建 LangSmith span | `shared/infra/tracing.py:langsmith_trace` | 上下文管理器 |
| LLM trace scope | `shared/infra/tracing.py:llm_trace_scope` | 设置嵌套 LLM 调用的环境上下文 |
| Workflow scope | `shared/infra/tracing.py:langsmith_tracing_scope` | 工作流级 tracing 上下文 |
| Metadata 构建 | `shared/infra/tracing.py:build_langsmith_metadata` | 标准化 metadata payload |
| Tags 构建 | `shared/infra/tracing.py:build_langsmith_tags` | 标准化 tag 列表 |
| Node span 包装 | `workflows/common/observability.py:wrap_workflow_node` | 节点层 span 创建 |
| Digest node 包装 | `workflows/digest/observability.py:wrap_digest_node` | Digest 专用（委托给 wrap_workflow_node） |
| Runtime span 基类 | `shared/infra/traced_execution.py:BaseTracedExecution` | 运行单元层 span 创建 |
| Trace context | `shared/infra/traced_execution.py:TracedExecutionContext` | 业务上下文数据类 |
| Node inputs 提取 | `workflows/common/observability.py:_node_trace_inputs` | 从 state 提取 trace inputs |
| Node outputs 提取 | `workflows/common/observability.py:_node_trace_outputs` | 从 result 提取 trace outputs |
| Runtime outputs 提取 | `shared/infra/traced_execution.py:_traced_execution_outputs` | 从 TracedExecutionResult 提取 |
| LLM 调用追踪 | `shared/infra/tracing.py:LLMCallTracker` | 内存中的调用记录 |
| Token 摘要 | `workflows/digest/observability.py:build_token_summary` | Digest 构建后的 token 报告 |

---

## 9. langgraph.json 与 LangGraph Studio

`backend/langgraph.json` 注册了所有可在 `langgraph dev` 中可视化的图：

```json
{
  "ingest_fast_parse":     "workflows/ingest/graph.py:get_langgraph_dev_fast_parse_graph",
  "ingest_deep_enhance":   "workflows/ingest/graph.py:build_deep_enhance_graph",
  "digest_kg":             "workflows/digest/kg/graph.py:build_kg_digest_graph",
  "digest_curriculum":     "workflows/digest/curriculum/graph.py:build_curriculum_derive_graph",
  "digest_docgen":         "workflows/digest/docgen/graph.py:get_langgraph_dev_docgen_graph",
  "digest_planner":        "workflows/digest/planner/graph.py:get_langgraph_dev_planner_graph",
  "digest_unified":        "workflows/digest/unified/graph.py:get_langgraph_dev_unified_graph",
  "interact_chat":         "workflows/interact/graph.py:get_langgraph_dev_interact_graph",
  "examine_question_build":"workflows/examine/question_build_workflow.py:build_question_build_graph",
  "examine_exam_grade":    "workflows/examine/exam_grade_workflow.py:build_exam_grade_graph",
  "profile_pipeline":      "workflows/profile/graph.py:build_profile_pipeline_graph"
}
```

运行 `langgraph dev` 后可以：
- 在 LangGraph Studio 中可视化图拓扑
- 手动触发单个图执行
- 实时查看 state 变化
- 所有执行自动发送到 LangSmith（如已配置）

---

## 10. 命名规范总结

### Span 命名

| 层级 | 命名格式 | 示例 |
| --- | --- | --- |
| Node span | `{lane}.{node_name}` | `docgen.targeted_research` |
| Runtime span | `{trace_namespace}.{trace_name}` | `workflow_runtime.docgen.research` |
| LLM span | 由 LiteLLM 自动命名 | `ChatCompletion` |

### 命名纪律

- workflow node 名称必须直接表达业务语义
- workflow-local runtime 的 trace 命名必须落在 `workflow_runtime.*`，不伪装成 infra
- trace 里必须能看见 planner session、confirmed plan、digest mode、retrieval profile、teaching action
- graph 结构要让后续优化人员一眼看懂"主骨架"和"章节并发骨架"

