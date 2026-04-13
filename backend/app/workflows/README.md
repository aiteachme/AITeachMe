# Workflows 分层说明

最后更新：2026-04-14

`backend/app/workflows/` 是业务编排层。
这里负责把 `infra` 提供的能力、`teaching` 提供的教学语义、数据库状态和前端回调组织成真正可运行的业务流程。

一句话理解：

> `workflows` 负责“这轮业务流程怎么跑”。

## 1. 它在系统里的位置

当前推荐依赖方向：

```text
api -> services -> workflows -> teaching -> shared.infra -> shared.kernel
```

这条链表示：

- `services` 是 API 的业务组合层。
- `workflows` 是真正的流程编排层。
- `workflows` 可以调用 `teaching` 和 `infra`。
- `workflows` 不应该把底层能力重新复制一遍。

## 2. 先看 `workflows` 里现在有哪些引擎

当前目录：

```text
workflows/
├── common/
├── ingest/
├── digest/
├── interact/
├── examine/
├── profile/
├── LANGSMITH.md
└── TRACKED_STEP.md
```

可以这样理解：

| 目录 | 负责什么 |
| --- | --- |
| `common/` | workflow 编写的公共基座 |
| `ingest/` | 上传资料后的解析、增强、收口 |
| `digest/` | 规划、知识文档、知识图谱、课程结构的构建主链 |
| `interact/` | 伴读对话、策略路由、流式输出 |
| `examine/` | 出题、组卷、评分、导出 |
| `profile/` | 学习画像、弱点分析、复习计划 |

## 3. 先读 `common/`，再看具体引擎

对新同学来说，`common/` 是最重要的目录。
因为它定义了“一个 workflow 在这个项目里应该怎么写”。

### 3.1 `common/` 里最重要的文件

- `context.py`
  `WorkflowContext`，统一 workflow 名称、subject、event bus、metadata。
- `runtime.py`
  `run_state_graph(...)` 与 `invoke_state_graph(...)`，统一 LangGraph 调用方式。
- `observability.py`
  `workflow_tracer(...).node(...)` 和 `@traceable_run(...)`。
- `runtime_stats.py`
  `tracked_step(...)`、runtime step 记录和进度回调。
- `events.py`
  workflow 级事件总线实现。
- `result.py`
  `WorkflowResult`、`ok_result(...)`、`err_result(...)`。
- `graph_export.py`
  LangGraph dev / graph 导出相关辅助。

### 3.2 新 workflow 默认应该用的公共入口

团队现在应优先使用下面这组 API：

- `run_state_graph(...)`
- `workflow_tracer(...).node(...)`
- `@traceable_run(...)`
- `tracked_step(...)`

如果新代码绕开这几套公共入口，后面 tracing、日志和 runtime stats 往往会不统一。

## 4. 每个引擎现在实际长什么样

### 4.1 `ingest/`

`ingest` 负责把原始资料变成系统可以继续消费的结构化输入。

当前主要目录和文件：

- `runtime.py`
  入口函数，当前是两阶段解析链路的核心。
- `graph.py`、`state.py`
  ingest graph 与状态定义。
- `nodes/`
  `file / parse / enhance / finalize` 等节点。
- `parsing/`
  真正的多格式解析实现，包含 PDF、DOCX、PPTX、图片、MinerU、OCR、canonicalizer 等。
- `events.py`、`exports.py`、`recovery.py`
  事件、导出和恢复辅助。

一句话：

- `ingest` 解决“资料怎么变成干净的 markdown、asset 和解析元数据”。

### 4.2 `digest/`

`digest` 是当前最复杂的 workflow 家族。
它不是一个单独 graph，而是一组围绕“知识构建”展开的流程。

#### 4.2.1 先记住 Digest 现在的主入口

当前最重要的三条运行入口是：

- `run_graph_digest_workflow(...)`
- `run_docgen_workflow(...)`
- `run_unified_digest_build(...)`

其中：

- `graph` 负责知识图谱相关构建
- `docgen` 负责知识文档构建
- `unified` 负责把文档、图谱、课程结构并到一条总构建链里

#### 4.2.2 `digest/` 里的主要子目录

| 目录 | 作用 |
| --- | --- |
| `planner/` | 构建方案草案、章节规划、研究查询规划 |
| `docgen/` | 章节 research、写作、富媒体、练习注入、发布 |
| `kg/` | 知识图谱节点解析、变更处理、图谱收口 |
| `curriculum/` | 教学单元、主题树、先修 DAG |
| `shared/` | Digest 家族内部共享输入、模型、准备逻辑 |
| `unified/` | 当前知识构建主链的顶层 orchestrator |
| `build/` | Unified 相关的兼容与协调层，不是新的主链入口 |
| `prompts/` | Digest 专属 prompt 文本 |

#### 4.2.3 `planner/` 是什么

`planner/` 负责“构建前”的规划阶段，核心产物包括：

- chapter plan
- research queries
- media plan
- build constraints
- confirmed plan

它不是最终文档生成器，而是后续统一构建的合同来源。

#### 4.2.4 `unified/` 是什么

`unified/` 是当前 `build_type=all` 的主构建入口。
服务层最终会调用：

- `services/knowledge/digest_service.py`
- `run_unified_build_background(...)`
- `workflows.digest.unified.runtime.run_unified_digest_build(...)`

当前 unified graph 的主阶段是：

```text
prepare_shared
-> run_parallel_lanes
-> derive_curriculum
-> publish_outputs
-> cleanup / fail
```

其中 `run_parallel_lanes` 会并行触发：

- `run_docgen_workflow(...)`
- `run_graph_digest_workflow(...)`

所以 unified 是“顶层总调度”，不是替代 docgen / kg 的单一实现。

#### 4.2.5 `docgen/` 是什么

`docgen/` 是知识文档生成主链。

当前 graph 主要阶段是：

```text
load_context
-> targeted_research
-> collect_materials
-> resolve_titles
-> pedagogy_craft
-> collect_drafts
-> enrich_document
-> inject_examine
-> finalize_assemble
```

其中 `docgen/runtime/` 下放的是 workflow-local runtime 单元，例如：

- `chapter_context.py`
  单章节 research micro-loop
- `query_planning.py`
  子查询规划
- `writer.py`
  章节写作
- `assets.py`
  富媒体 sidecar

这些 runtime 是业务实现，不是共享基础设施。

#### 4.2.6 `kg/` 是什么

`kg/` 负责知识图谱构建与收口。

当前主要包括：

- `prepare_nodes.py`
- `resolve_nodes.py`
- `finalize_nodes.py`
- `mutations.py`
- `routes.py`
- `services/`

它解决的是“知识节点和边如何从资料中抽取出来并更新到图里”。

#### 4.2.7 `curriculum/` 是什么

`curriculum/` 负责课程结构派生，包括：

- Teaching Unit
- Theme Tree
- Prereq DAG

它依赖图谱结果，但目标是面向教学结构，而不是面向原始知识片段。

#### 4.2.8 `shared/` 是什么

`digest/shared/` 放 Digest 家族自己的共享合同。

这里的共享范围是“Digest 内部复用”，不是整个后端通用。
例如：

- shared input prepare
- 章节分段
- semantic title 辅助
- source hint / asset indexer
- build contracts / models

### 4.3 `interact/`

`interact` 负责伴读式对话。

当前主要结构：

- `runtime.py`
  interact 的对外运行入口与 SSE 流式封装。
- `graph.py`、`state.py`
  interact graph 与状态。
- `nodes/`
  history、retrieval、strategy、prompt、execution、stream、persist 等节点。
- `support/`
  节点下沉的执行辅助，例如 retrieval、execution、streaming、strategies。
- `prompts/`
  interact 专属 prompt。

一句话：

- `interact` 解决“在对话里如何引导用户、如何检索上下文、如何流式回传结果”。

### 4.4 `examine/`

`examine` 负责考试链路。

当前主要内容：

- `question_builder.py`
- `paper_assembler.py`
- `paper_exporter.py`
- `answer_grader.py`
- `exam_grade_workflow.py`
- `graph.py`、`state.py`
- `prompts/`

另外还有一个重要点：

- `runtime.py` 里保留了一个从纯文本直接生成试题的 helper，主要用于 playground / debug，不是考试主链的全部实现。

### 4.5 `profile/`

`profile` 负责学习画像。

当前主要内容：

- `runtime.py`
  学习报告建议等 runtime helper。
- `graph.py`、`state.py`
  profile graph。
- `weakness_analyzer.py`
- `mastery_updater.py`
- `review_scheduler.py`
- `subject_profile.py`
- `user_profile.py`
- `prompts/`

一句话：

- `profile` 解决“用户学得怎么样，接下来应该怎么复习”。

## 5. `runtime.py`、`runtime/`、`graph.py` 怎么区分

这是新同学最容易混的点。

### 5.1 `workflows/<engine>/runtime.py`

通常是该引擎对外暴露的高层入口。

例子：

- `ingest/runtime.py`
- `interact/runtime.py`
- `digest/runtime.py`
- `profile/runtime.py`

这些文件负责把 graph、事件、context、结果收口成可调用的入口函数。

### 5.2 `workflows/<engine>/<subflow>/runtime/`

这是 workflow-local runtime 单元目录。

例子：

- `digest/docgen/runtime/chapter_context.py`
- `digest/docgen/runtime/query_planning.py`
- `digest/docgen/runtime/writer.py`
- `digest/docgen/runtime/assets.py`

它们通常是：

- 多步逻辑
- 强依赖当前 workflow 语义
- 可能复用 `BaseTracedExecution`
- 但本质上还是业务实现

### 5.3 `graph.py`

`graph.py` 负责定义 LangGraph 本身：

- 节点有哪些
- 边怎么连
- 条件路由怎么走
- 初始状态怎么创建

简单说：

- `graph.py` 定义流程图
- `runtime.py` 暴露运行入口
- `runtime/` 承载流程里的复杂执行单元

## 6. Prompt 应该放哪里

当前规则很明确：

- workflow 专属 prompt 放 `workflows/<engine>/prompts/`
- prompt 变量填充可以调用 `shared.infra.prompt_loader`
- 但 prompt 文本的归属仍然是 workflow 自己

这能避免把业务 prompt 又塞回 `infra`。

## 7. LangSmith 和可观测性怎么接

workflow 级 tracing 的主入口在：

- `workflows/common/runtime.py`
- `workflows/common/observability.py`
- `workflows/common/runtime_stats.py`

团队现在应优先使用：

- `run_state_graph(...)`
- `workflow_tracer(...).node(...)`
- `@traceable_run(...)`
- `tracked_step(...)`

进一步约定见：

- [LANGSMITH.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe/backend/app/workflows/LANGSMITH.md)
- [TRACKED_STEP.md](/c:/Project/Project0GIT/aiteachme/AiTeachMe/backend/app/workflows/TRACKED_STEP.md)

## 8. 哪些东西不应该放进 `workflows`

下面这些内容不要回流到 `workflows`：

- 底层数据库、存储、LLM、retriever、reader 接入
- 通用 tool registry、skillpack registry
- 教学表达本身
- 可以脱离当前 workflow 独立存在的共享基础能力

判断方法：

- 如果你在决定“这轮流程怎么跑”，放 `workflows`
- 如果你在决定“怎么教”，放 `teaching`
- 如果你在决定“能力怎么接”，放 `infra`

## 9. 新代码放置速查

| 需求 | 更合适的目录 |
| --- | --- |
| 新增一个 Digest graph 节点 | `workflows/digest/...` |
| 新增一个 Interact 检索策略节点 | `workflows/interact/nodes` 或 `support` |
| 新增一个 DocGen 章节 runtime 单元 | `workflows/digest/docgen/runtime/` |
| 新增一个 workflow 公共 tracing helper | `workflows/common` |
| 新增一个教学脚手架函数 | `teaching/documents` |
| 新增一个共享 retriever | `shared.infra.search` |

## 10. 阅读建议

第一次读 `workflows`，建议顺序如下：

1. `common/__init__.py`
2. `common/context.py`
3. `common/runtime.py`
4. `common/observability.py`
5. `common/runtime_stats.py`
6. `digest/runtime.py` 与 `digest/unified/runtime.py`
7. `digest/docgen/graph.py`
8. `interact/runtime.py`
9. `examine/graph.py`
10. `profile/graph.py`

## 11. 一句话总结

`workflows` 是业务编排层。
它负责把 `infra` 的能力和 `teaching` 的教学语义组织成一条真正能运行、能观测、能收口的流程。
