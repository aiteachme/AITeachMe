# Workflows 模块说明

`backend/app/workflows/` 是后端的业务编排层，承载五大教学引擎的 LangGraph 图。

职责边界：
- `services/` → 接口触发、参数校验、持久化适配
- `workflows/` → 业务编排与状态推进
- `shared/infra/` → 通用能力
- `teaching/` → 教学专属能力

## 五大引擎

| 引擎 | 目录 | 职责 |
|------|------|------|
| ingest | `workflows/ingest/` | 文件解析、分类、结构化抽取、深度增强 |
| digest | `workflows/digest/` | 构建方案规划、知识文档生成、知识图谱构建、课程派生 |
| interact | `workflows/interact/` | 教学对话、上下文检索、教学策略选择、流式回答 |
| examine | `workflows/examine/` | 出题、组卷、判卷、复盘 |
| profile | `workflows/profile/` | 掌握度更新、复习调度、薄弱点分析、画像刷新 |

## 目录约定

```text
workflows/<engine>/
├── graph.py        # LangGraph 拓扑，不写重业务逻辑
├── state.py        # 状态类型
├── runtime.py      # 运行入口
├── exports.py      # 流程图导出
├── prompts/        # 提示词
└── nodes/          # 节点实现（可选）
```

## Digest 的层次

`digest` 下有多条业务 lane（`planner` / `docgen` / `kg` / `curriculum`）和一个 `unified` 编排层。

`unified` 只做总调度：准备共享输入、协调 lane 运行顺序、汇总结果。业务逻辑写在各自 lane 里。

---

## LangSmith 兼容规范

这是整个项目最重要的横切约定。所有 workflow 模块必须遵守，确保 LangSmith 全链路可观测。

### 核心三层结构

一个规范的 workflow 在 LangSmith 中必须呈现三层嵌套：

```
workflow 根 span          ← 由 runtime 统一入口自动创建
└── node span             ← 由 wrap_workflow_node 自动创建
    ├── LLM span          ← 由统一 LLM 层自动创建
    ├── retriever span    ← 由 BaseRetriever 自动创建
    └── skill 内部调用    ← 由 SkillContext 自动传递 metadata
```

这三层分别对应下面三条规则。

---

### 协作开发黄金规则

这部分可以直接当作给 AI 协作者的高优先级提示词。

1. `graph.py` 只负责拓扑、路由和 fan-out/fan-in，不写重业务逻辑。
2. 真正执行外部动作的节点必须能在 LangSmith 中被单独看见；优先做成 `wrap_workflow_node` 包裹的业务节点。
3. 一个业务动作如果内部还要做多步 LLM / retriever / scraper / tool 编排，优先下沉到 `Skill`、`Retriever`、`Scraper` 或 `shared/infra`，不要继续把 graph 切碎。
4. 新增节点前先问自己：这是一个值得在 LangSmith 单独观测、单独计时、单独失败定位的步骤吗？如果不是，放进现有节点或 Skill。
5. state 是 trace 的来源，不要把可观测字段藏在闭包、本地变量、全局变量里。
6. 任何新 workflow 的默认目标都是：LangSmith 打开后，能一眼看懂主流程、输入规模、关键分支、失败位置和主要成本来源。

---

### 规则 1：Workflow 入口 — 统一 runtime

graph 执行必须走 `common/runtime` 提供的统一函数（当前是 `run_state_graph` / `invoke_state_graph`）。

为什么：
- 自动创建 workflow 级 LangSmith 根 span
- 自动设置 `llm_trace_scope`，让内部所有 LLM 调用继承 `subject / build_session_id / workflow` 等 metadata
- 自动提供错误处理和计时

禁止：
- 手写 `graph.compile().ainvoke(...)`
- 自己拼 `llm_trace_scope` 或 `langsmith_tracing_scope`

> **给 AI 协作者的提示词**：当你需要创建一个新的 workflow runtime 入口时，请参考 `workflows/ingest/runtime.py` 或 `workflows/interact/runtime.py` 的写法。核心模式是：创建 `WorkflowContext` → 调用 `run_state_graph()`，不要自己拼 trace。

---

### 规则 2：Node 入口 — 统一 wrapper

所有"真正干活"的业务节点必须用 `wrap_workflow_node` 包裹。

它自动做这些事：
- 打开 LangSmith node span（span 名 = `{lane}.{node_name}`）
- 设置 `llm_trace_scope`，节点内所有 LLM 调用自动继承 workflow / lane / node metadata
- 从 state 中自动提取可观测字段作为 trace inputs（见下文"可观测字段"）
- 从返回值中自动提取 outputs（elapsed_ms / status / 各种 count）
- 自动记录 `node_timings_ms` 和 `node_events` 到 state
- 如果 state 中有 `progress_callback`，自动发布进度事件
- 异常时自动记录 error 到 span 并 re-raise

不需要包的节点：路由函数、纯状态判断、简单常量返回。

> **给 AI 协作者的提示词**：当你需要给 graph 添加一个新节点时，请用 `wrap_workflow_node` 包裹 handler。需要传入 `workflow_name`（格式 `engine.sub`）、`lane`、`node_name` 三个参数。可选传 `timing_field` 让 wrapper 自动把耗时写入 state。参考 `workflows/ingest/graph.py` 中任意一个节点的写法。

---

### 规则 3：LLM 调用 — 统一模型层

所有模型调用走 `shared/infra/llm` 或 `shared/infra/llm_support`，不直接调底层 SDK。

统一层自动提供：
- 模型路由（`TaskType` → 具体模型）
- 降级容错（`acompletion_with_fallback` 的 tier 降级链：REASONING → DOCGEN → DEFAULT 等）
- token 统计（`LLMCallTracker`）
- LangSmith LLM span（自动记录 task_type / model / tokens）

禁止：
- 在 workflow 节点里直接 `import litellm` 或 `import openai`
- 自己拼 LangSmith LLM span

> **给 AI 协作者的提示词**：节点内需要调用 LLM 时，使用 `shared/infra/llm_support` 中的函数（如 `acompletion`），通过 `task_type` 参数选择模型层级。不需要手动传 subject / session_id 等 metadata，`wrap_workflow_node` 已经通过 `llm_trace_scope` 设置好了。

---

### 规则 4：允许的例外边界

上面的规则是默认方案，但协作开发里有少数合理例外。文档必须把例外讲清楚，否则人和 AI 都容易“过度机械化”。

允许手写 `llm_trace_scope()` 的场景：

- 节点内部存在一个长生命周期、流式或生成器式的 LLM 过程，必须人为收紧 span 边界。
- 某个 helper 不是 graph 节点，但它确实是一个独立的 LLM 动作，且需要单独的 `lane` / `node` 标识。
- 历史模块还没完全 Skill 化，但短期内必须先保持 trace 清晰。

不允许手写 `langsmith_tracing_scope()` 或自行创建 workflow 根 span 的场景：

- workflow runtime 内部
- graph 节点边界
- 任何已经被 `run_state_graph()`、`invoke_state_graph()` 或 `wrap_workflow_node()` 覆盖的地方

允许例外时也必须遵守：

- 只能补子级 `llm_trace_scope()`，不能绕开统一 runtime。
- `workflow` / `lane` / `node` 命名必须与 graph 中看到的业务语义一致。
- 如果例外逻辑未来可能复用，应优先收敛成 `BaseSkill` 或统一 helper，而不是继续在节点里复制。

一句话：允许补“子 span”，不允许另起“第二套 tracing 体系”。

---

### Skill / Retriever / Scraper 层

这三类组件已内置 LangSmith tracing，在节点中调用时 trace 会自动嵌套在 node span 下：

- `BaseRetriever` 子类：每次 `retrieve()` 自动记录 retriever_name / query / result_count
- `BaseScraper` 子类：每次 `scrape()` 自动记录 scraper_name / url / success
- `BaseSkill` 子类：通过 `SkillContext.trace_metadata()` 自动注入 skill_name / research_stage 等

在节点中调用 Skill 时，只需正确构建 `SkillContext`（传入 subject / build_session_id / digest_mode / chapter_index 等），Skill 内部所有 LLM 调用会自动携带这些 metadata。

> **给 AI 协作者的提示词**：如果节点内需要调用 Skill（如 ResearchConductor），请参考 `workflows/digest/docgen/nodes/targeted_research_node.py` 中构建 `SkillContext` 的方式。核心是把 state 中的可观测字段传给 SkillContext，Skill 内部会自动处理 tracing。

---

### 可观测字段

wrapper 会自动从 state 中提取以下字段。新建 workflow 时，state 中尽量包含适用的字段：

| 字段 | 适用场景 | 说明 |
|------|---------|------|
| `subject` | 全部 | 学科/主题名 |
| `build_session_id` | digest | 构建会话 ID |
| `planner_session_id` | digest | Planner 会话 ID |
| `confirmed_plan_id` | digest | 确认方案 ID |
| `digest_mode` | digest | "sprint" / "systematic" |
| `tone` | digest | 语言风格 |
| `chapter_index` | digest fan-out | 章节索引 |
| `session_id` | interact | 对话会话 ID |
| `job_id` | ingest | 文件处理任务 ID |
| `file_id` | ingest | 文件 ID |
| `exam_paper_id` | examine | 试卷 ID |
| `user_id` | 全部 | 用户 ID |

`workflow` / `lane` / `node` 由 wrapper 自动注入，不需要放在 state 里。

wrapper 还会自动对 state 中的 list 字段计数（如 `file_ids` → `file_count`、`doc_ids` → `doc_count`、`review_tasks` → `review_task_count`），以及自动记录 `elapsed_ms` / `status` / `error` 到 trace outputs。

---

### State 设计契约

为了让 LangSmith 真正“可读”，新增或重构 workflow 时，state 设计要遵守下面的契约：

1. 稳定标识优先。
   `subject`、`build_session_id`、`session_id`、`job_id`、`planner_session_id` 等字段尽早进入 state，不要拖到中途才补。
2. fan-out 字段显式化。
   并行章节、题目、任务等都要保留 `chapter_index`、`task_id` 一类稳定标识，避免 LangSmith 里看不出哪条分支对应哪一份工作。
3. 错误语义统一。
   可恢复错误写入 `error` 字段；不可恢复异常直接抛出，由 wrapper / runtime 记录失败 span。
4. 统计字段结构化。
   数量信息优先放到 list 字段或明确的 `*_count` / `*_hits` / `*_ms` 字段，避免把关键统计埋进长文本。
5. 返回值保持可合并。
   节点返回的 dict 应能直接 merge 回 state，不要返回难以追踪的匿名 tuple 或位置语义对象。

推荐做法：

- 章节类并行任务统一带 `chapter_index`
- 研究类节点统一带 `retriever_stats`、`local_hits`、`web_hits`
- 写作类节点统一带 `word_count`、`source_count`、`placeholder_count`
- 汇总类节点统一带 `total_*` 字段

---

### 双层 Graph 模式

Examine 和 Profile 采用"主 graph + 子 workflow"结构：

- 主 graph 中的纯状态转发节点 → 不需要 wrapper
- 子 workflow 中的业务节点 → 全部接 wrapper
- 子 workflow 通过 `invoke_state_graph()` 运行，自动获得独立的 workflow 级 trace

后续新引擎如果有类似的"编排层 + 执行层"分离需求，可以参照这个模式。

---

### 各引擎当前接入状态

| 引擎 | 节点覆盖 | Runtime |
|------|---------|---------|
| ingest | 11/11 | `run_state_graph` |
| digest/docgen | 8/8 | `run_state_graph` |
| interact | 6/6 | `run_state_graph` |
| examine | 9/9 (子 workflow) | `invoke_state_graph` |
| profile | 7/7 (pipeline) | `run_state_graph` |

---

### 完整 trace 树参考

以下是各引擎在 LangSmith 中的实际 trace 结构，供调试时对照：

**Ingest**：
```
ingest.fast_parse
├── fast_parse.load_raw_file
├── fast_parse.classify_file → llm [task_type=classify]
├── fast_parse.plan_parse
├── fast_parse.parse_file
└── fast_parse.finalize_success
```

**Digest DocGen**：
```
digest.docgen
├── docs.load_context
├── docs.targeted_research [ch=0]     ← fan-out
│   ├── ResearchConductor
│   │   ├── retriever.local_rag
│   │   ├── retriever.bing
│   │   └── llm.purify [tier=smart]
├── docs.targeted_research [ch=1]     ← 并行
├── docs.collect_materials
├── docs.pedagogy_craft [ch=0]        ← fan-out
│   └── PedagogyWriter → llm [tier=smart]
├── docs.collect_drafts
├── docs.enrich_document
│   ├── MermaidGenerator
│   └── ImageGenerator
├── docs.inject_examine
└── docs.finalize_assemble
```

**Interact**：
```
interact.teaching
├── teaching.load_history_state
├── teaching.retrieve_context → retriever.local_rag
├── teaching.select_teaching_strategy → llm [task_type=chat]
├── teaching.build_prompt
├── teaching.stream_answer → llm.stream [task_type=chat]
└── teaching.persist_turn
```

**Examine**：
```
examine.question_build
├── question_build.load_units
├── question_build.generate_templates → llm [task_type=docgen]
└── question_build.finalize_build
```

**Profile**：
```
profile.pipeline
├── pipeline.resolve_profile_context
├── pipeline.update_mastery
├── pipeline.analyze_weakness → llm [task_type=reasoning]
└── pipeline.refresh_subject_profile
```

---

## 提交前检查清单

- [ ] graph 通过统一 runtime 函数运行
- [ ] 业务节点接了 `wrap_workflow_node`
- [ ] LLM 调用走统一层，不直接调底层 SDK
- [ ] `langgraph.json` 注册了 graph 入口
- [ ] `exports.py` 暴露了流程图导出
- [ ] state 中包含适用的可观测字段
- [ ] 如果调用 Skill，正确构建了 `SkillContext`
- [ ] 如果是双层 graph，子 workflow 全部接了 wrapper
- [ ] 例外场景如果手写了 `llm_trace_scope()`，有明确理由且没有新增第二层 workflow 根 span

## AI 协作者模板

下面三个模板可以直接复制，优先保持结构一致。

### 模板 1：新增 workflow runtime

```python
async def run_xxx_workflow(...):
    context = WorkflowContext(
        workflow_name="engine.sub",
        subject=subject,
        metadata={"build_session_id": build_session_id},
    )
    result = await run_state_graph(
        workflow_name=context.workflow_name,
        graph_builder=lambda: build_xxx_graph(context=context),
        initial_state=initial_state,
        context=context,
    )
    return result
```

### 模板 2：新增 graph 节点

```python
workflow.add_node(
    "node_name",
    wrap_workflow_node(
        build_node_name_node(context=context),
        workflow_name=context.workflow_name,
        lane="lane_name",
        node_name="node_name",
        timing_field="node_name_ms",
    ),
)
```

### 模板 3：节点中调用 Skill

```python
skill = SomeSkill(
    SkillContext(
        subject=state["subject"],
        build_session_id=state.get("build_session_id", ""),
        workflow_context=context,
        planner_session_id=state.get("planner_session_id", ""),
        confirmed_plan_id=state.get("confirmed_plan_id", ""),
        digest_mode=state.get("digest_mode", ""),
        chapter_index=state.get("chapter_index"),
    )
)
result = await skill.run(...)
```

如果你写出的代码明显偏离这三个模板，默认说明实现方式需要重新审视。

## Graph 暴露约定

每个模块至少暴露一个 `build_xxx_graph(*, context) -> StateGraph`。

兼容 `langgraph dev` 的零参数入口用 `get_langgraph_dev_xxx_graph()`。

`langgraph.json` 里只注册真实可调试 graph。

## 流程图导出

```bash
conda run -n atm python backend/scripts/generate_workflow_diagrams.py
```

输出到 `backend/scripts/.generated_workflow_diagrams/`。`exports.py` 优先暴露真实执行图。

## 自检命令

协作开发提交前，建议至少执行下面几条检索，快速排除 tracing 兼容性回退：

```bash
rg -n "compile\\(\\)\\.ainvoke" backend/app/workflows
rg -n "import openai|import litellm" backend/app/workflows
rg -n "langsmith_tracing_scope\\(" backend/app/workflows
rg -n "wrap_workflow_node\\(" backend/app/workflows
```

期望结果：

- `compile().ainvoke` 只应出现在 `workflows/common/runtime.py`
- `import openai` / `import litellm` 不应出现在 `workflows/`
- `langsmith_tracing_scope(` 只应出现在统一 runtime 或 tracing 基础设施
- 新增业务节点应该能在 `wrap_workflow_node(` 检索结果里看到

## 风格

- graph 只编排节点
- skills/tools 承载业务动作
- tracing 只保留一层统一接入，不扩散 adapter / bridge / compat 中间层

目标：

- 读 graph 看懂主流程和并行结构
- 读 skill 看懂动作和策略
- 打开 LangSmith 就能看懂输入、输出、耗时、分支和失败点
