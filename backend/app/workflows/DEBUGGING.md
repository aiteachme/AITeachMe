# Workflows 调试指南

最后更新：2026-04-14

这份文档面向 `backend/app/workflows/` 的开发者。
它回答的是：

- 我应该从哪一层开始调一个 workflow
- `langgraph dev` 在这个仓库里怎么用
- Digest 现在适不适合拿来做 LangGraph + LangSmith 调试样板
- Studio 里能看什么、能改什么、不能改什么

它**不重复**下面两份规范文档：

- [LANGSMITH.md](./LANGSMITH.md)
  负责说明 workflow tracing 的统一接法。
- [TRACKED_STEP.md](./TRACKED_STEP.md)
  负责说明 node 内 `tracked_step(...)` 的语义、粒度和 `run_type` 约定。

如果你在写新 graph、补 tracing、压 span 噪音，请先看上面两份。
如果你要实际调一个 workflow，先看这份。

---

## 1. 先选调试面

同一个问题，通常有 3 条调试路径。先选对入口，会省很多时间。

| 调试面 | 适合查什么 | 什么时候优先用 |
| --- | --- | --- |
| 真实业务链路（FastAPI / service） | API 壳、鉴权、后台任务、锁、持久化、副作用 | 你怀疑问题不在 graph 本身，而在 service / DB / 文件系统 |
| `langgraph dev` + Studio | graph 拓扑、节点流转、state、分叉重跑、本地断点 | 你要看“这条 workflow 是怎么跑起来的” |
| LangSmith trace | prompt、LLM、retriever、tool、runtime 边界、耗时 | 你要查“为什么这一步慢 / 为什么 prompt 不对 / 为什么 research 路径怪” |

推荐顺序：

1. 先用 `langgraph dev` 看 graph 顶层是否跑对。
2. 顶层对了，再看 LangSmith trace 的细节。
3. 只有怀疑业务壳、锁或落库问题时，才回到 FastAPI / service。

---

## 2. 仓库当前支持的 `langgraph dev` 入口

当前入口集中在 [backend/langgraph.json](../../langgraph.json)。
README 也明确把它作为调试入口，而不是替代生产调用链的第二套 runtime。

当前可直接用于 `langgraph dev` 的 graph 包括：

- `ingest_fast_parse`
- `ingest_deep_enhance`
- `digest_kg`
- `digest_curriculum`
- `digest_docgen`
- `digest_planner`
- `digest_unified`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

其中对 Digest 来说，最重要的是：

- `digest_planner`
- `digest_docgen`
- `digest_unified`
- `digest_kg`（对应 workflow 名 `digest.graph`）
- `digest_curriculum`

这些入口已经有编译级测试覆盖，可参考：

- [backend/tests/test_langgraph_dev_entrypoints.py](../../tests/test_langgraph_dev_entrypoints.py)

---

## 3. `langgraph dev` 怎么跑

### 3.1 最小启动流程

在 `backend/` 目录执行：

```bash
cd backend
pip install -e .
pip install -U "langgraph-cli[inmem]"
langgraph dev --config langgraph.json
```

启动后，终端会打印类似下面的信息：

```text
Ready!

- API: http://localhost:2024
- Docs: http://localhost:2024/docs
- LangSmith Studio Web UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

然后直接打开 Studio 页面即可。

### 3.2 `.env` 建议

本仓库推荐这样区分：

- 只想本地调 graph / state，不想把 trace 发到 LangSmith：

```env
LANGSMITH_TRACING=false
```

- 想同时看 Studio 和 LangSmith trace：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=AITeachMe
```

经验上：

- 第一次把 graph 跑通时，先关 `LANGSMITH_TRACING`，噪音最少。
- 顶层节点走顺之后，再开 LangSmith 看 prompt / retriever / runtime 细节。

### 3.3 可选：接 IDE 断点

如果要单步调试节点内部逻辑，可以这样启动：

```bash
cd backend
pip install debugpy
langgraph dev --config langgraph.json --debug-port 5678
```

然后用 VS Code / PyCharm 附加到 `5678` 即可。

这条路最适合查：

- 某个 node 为什么返回了异常 state
- 某个 prompt builder / runtime helper 为什么得到意外输入
- 某个条件分支为什么走错

---

## 4. Digest 推荐调试顺序

Digest 是当前 `workflows/` 里最复杂、也是 LangSmith 接得最完整的一组 workflow。
但它不是所有子图都同样适合“第一次就直接在 Studio 里单独调”。

推荐顺序写死如下：

### 4.1 首选：`digest_planner`

最适合先调它，因为：

- 顶层图最小，只有 3 个 node
- `tracked_step(...)` 主要也集中在 planner，适合先熟悉 span 结构
- 主要问题通常是 prompt、grounding、plan 合同，不牵涉太多跨 Lane 状态

适合查：

- 为什么章节方案不合理
- 为什么 research query 不对
- 为什么规划偏“速成”或偏“系统”

### 4.2 第二个：`digest_unified`

最适合做端到端 Digest 主链调试，因为它就是当前 `build_type=all` 的总入口。

它会串起：

- `prepare_shared`
- `run_parallel_lanes`
- `derive_curriculum`
- `publish_outputs`

如果你想判断“整条 Digest 主链有没有跑顺”，先看它。

### 4.3 第三个：`digest_docgen`

适合隔离文档链，但它**不是无前提的独立玩具图**。

高风险前置条件：

- 它要求 `confirmed_plan`
- 没有已确认方案时，`load_context` 会直接返回错误

也就是说，`digest.docgen` 不应该被理解为“只给个 subject 和 file_ids 就能直接开始写文档”。

### 4.4 进阶：`digest_kg` / `digest.graph`

不建议把它当成第一次上手 Studio 的首选样例。

高风险前置条件：

- 它依赖 `build_session_id`
- `prepare` 节点会从 unified session 里取 `shared_inputs` 和物化后的 `chunk_ids`
- 缺少 unified session 时，KG prepare 会失败

所以 `digest.graph` 更适合：

- 你已经通过 `digest_unified` 跑过一轮
- 或者你明确知道自己在构造什么前置状态

### 4.5 进阶：`digest_curriculum`

Curriculum Lane 更偏“下游派生图”。
它依赖 `graph_job_id / curriculum_job_id / impact_set / build_session_id` 这些上游上下文。

结论：

- 第一次入门不要先调它
- 它更适合在 KG 已经跑通后做定向排查

---

## 5. Digest 最小可运行输入样例

下面的样例字段都来自真实的 `create_*_initial_state(...)`。
没有额外虚构字段。

说明：

- Studio 输入是 JSON，所以时间字段请用 ISO 8601 字符串表达。
- 如果你遇到某个 `datetime` 字段在本地 dev server 中表现不一致，最稳妥的办法是：
  1. 先从一次真实运行拿到 state
  2. 再在 Studio 里 fork / rerun

### 5.1 `digest_planner` 样例

来源：

- `backend/app/workflows/digest/planner/graph.py:create_planner_initial_state`

```json
{
  "subject": "subj_demo_math",
  "file_ids": [1],
  "user_goal": "请给我一套高考数学考前冲刺的知识文档方案。",
  "digest_mode": "sprint",
  "course_type": "sprint",
  "retrieval_profile": "planner_grounding",
  "teaching_action": "plan_course",
  "tone": "encouraging",
  "selected_skillpacks": [],
  "planner_session_id": "planner_debug_session_001",
  "message_history": [],
  "latest_plan": null,
  "runtime_steps": [],
  "_runtime_step_starts": {},
  "progress_callback": null,
  "token_callback": null,
  "error": null
}
```

### 5.2 `digest_unified` 样例

来源：

- `backend/app/workflows/digest/unified/graph.py:create_unified_initial_state`

```json
{
  "subject": "subj_demo_math",
  "file_ids": [1],
  "user_prompt": "请生成一份偏考前冲刺的数学知识讲义。",
  "requested_at": "2026-04-14T15:30:00+08:00",
  "build_session_id": "unified_debug_session_001",
  "planner_session_id": "planner_debug_session_001",
  "confirmed_plan_id": "confirmed_plan_debug_001",
  "confirmed_plan": {
    "subject": "subj_demo_math",
    "user_goal": "请生成一份偏考前冲刺的数学知识讲义。",
    "digest_mode": "sprint",
    "tone": "encouraging",
    "selected_skillpacks": [],
    "chapter_plan": [
      {
        "chapter_index": 1,
        "title": "函数与导数冲刺",
        "objective": "聚焦函数图像、单调性、极值和导数应用。",
        "required_elements": [
          "核心概念",
          "典型题型"
        ],
        "search_queries": [
          "函数与导数 高考 冲刺",
          "导数 应用 典型题型"
        ],
        "writing_instructions": "优先讲高频考点与易错点。",
        "source_file_ids": [1]
      }
    ],
    "research_queries": [
      "函数与导数 高考 冲刺"
    ],
    "media_plan": {},
    "build_constraints": {
      "include_exercises": true,
      "include_sources": true
    },
    "plan_summary": "先用一章覆盖函数与导数高频考点。",
    "selected_file_ids": [1],
    "planner_session_id": "planner_debug_session_001",
    "confirmed_plan_id": "confirmed_plan_debug_001",
    "mode_reason": "manual_debug"
  },
  "digest_mode": "sprint",
  "tone": "encouraging",
  "graph_job_id": 1001,
  "curriculum_job_id": 1002,
  "error": null
}
```

### 5.3 `digest_docgen` 样例

来源：

- `backend/app/workflows/digest/docgen/graph.py:create_docgen_initial_state`

```json
{
  "subject": "subj_demo_math",
  "file_ids": [1],
  "user_prompt": "请生成一份偏考前冲刺的数学知识讲义。",
  "requested_at": "2026-04-14T15:30:00+08:00",
  "build_session_id": "docgen_debug_session_001",
  "shared_inputs": null,
  "confirmed_plan": {
    "subject": "subj_demo_math",
    "user_goal": "请生成一份偏考前冲刺的数学知识讲义。",
    "digest_mode": "sprint",
    "tone": "encouraging",
    "selected_skillpacks": [],
    "chapter_plan": [
      {
        "chapter_index": 1,
        "title": "函数与导数冲刺",
        "objective": "聚焦函数图像、单调性、极值和导数应用。",
        "required_elements": [
          "核心概念",
          "典型题型"
        ],
        "search_queries": [
          "函数与导数 高考 冲刺",
          "导数 应用 典型题型"
        ],
        "writing_instructions": "优先讲高频考点与易错点。",
        "source_file_ids": [1]
      }
    ],
    "research_queries": [
      "函数与导数 高考 冲刺"
    ],
    "media_plan": {},
    "build_constraints": {
      "include_exercises": true,
      "include_sources": true
    },
    "plan_summary": "先用一章覆盖函数与导数高频考点。",
    "selected_file_ids": [1],
    "planner_session_id": "planner_debug_session_001",
    "confirmed_plan_id": "confirmed_plan_debug_001",
    "mode_reason": "manual_debug"
  },
  "planner_session_id": "planner_debug_session_001",
  "confirmed_plan_id": "confirmed_plan_debug_001",
  "digest_mode": "sprint",
  "course_type": "sprint",
  "retrieval_profile": "docgen_sprint",
  "teaching_action": "docgen_build",
  "tone": "encouraging",
  "selected_skillpacks": [],
  "document_context": null,
  "error": null
}
```

### 5.4 `digest_kg` / `digest.graph` / `digest_curriculum` 为什么不放“开箱即跑”样例

不是因为它们没有初始 state，而是因为仅有初始 state 还不够。

对 `digest_kg`（workflow 名 `digest.graph`）：

- `prepare` 依赖 `build_session_id`
- `build_session_id` 对应的 unified session 需要已经在当前进程里创建
- 没有 unified session，就会在 `prepare` 阶段失败

对 `digest_curriculum`：

- 它更像 KG 成功后的派生链
- 单独调时通常还要构造 `impact_set`

所以这两条图在教程里只建议作为“进阶调试对象”，不建议当成第一次上手样例。

---

## 6. Digest 的 trace 会不会太多看不懂

短答案：**现在的顶层 trace 还算可读，不至于一上来就炸掉。**

原因是当前仓库已经明确约束：

- graph node 由 LangGraph 自动建 node span
- `workflow_tracer(...).node(...)` 只补上下文，不再手动再包一层 node span
- 真正的细粒度 span 主要来自：
  - `tracked_step(...)`
  - `@traceable_run(...)`
  - infra 层 LLM / retriever / runtime 边界

### 6.1 先看顶层图，不要一上来就钻细 span

推荐阅读顺序：

1. 先看 graph 顶层节点有没有按预期推进
2. 再看每个节点前后的 state diff
3. 再看 node 内 `tracked_step(...)`
4. 最后才下钻到 prompt / retriever / runtime span

如果你反过来，一开始就点进 LangSmith 最深层，很容易把“业务路径问题”和“prompt 细节问题”混在一起。

### 6.2 当前 Digest 顶层图规模

按 graph 顶层 node 数量看：

| 图 | 顶层 node 数 |
| --- | --- |
| `digest_planner` | 3 |
| `digest_unified` | 6 |
| `digest_docgen` | 9 |
| `digest_kg` | 9 |
| `digest_curriculum` | 5 |

这意味着：

- Planner 最适合入门
- Unified 最适合看主链
- DocGen / KG 进入“中等复杂度”
- 还没有到“光顶层就完全看不懂”的程度

### 6.3 当前 `tracked_step(...)` 的密度

从当前仓库实现看，`tracked_step(...)` 主要集中在 `digest.planner`。
这反而是个好事：

- 顶层 graph 不会因为每个 node 都被手工切太碎而炸成一屏 span
- 细粒度步骤主要出现在最需要解释规划过程的地方

真正会让 trace 变密的，通常不是 graph 顶层，而是继续往下看：

- prompt builder
- retriever / reader
- runtime helper
- infra LLM 调用

所以当前建议是：

- 先看“顶层图是否可读”
- 只有顶层方向对了，才去看细 span

---

## 7. Studio 里能做什么，不能做什么

这部分一定要和“官方能力”以及“本仓库现状”分开看。

### 7.1 当前仓库里，Studio 能做什么

在本仓库当前接法下，Studio 适合做这些事：

- 跑 graph
- 看 graph 拓扑
- 看 node 执行顺序
- 看 state 输入 / 输出
- 观察某个节点失败在哪
- 配合 LangSmith trace 看 prompt、LLM、retriever、runtime 边界
- 在本地改代码后，由 `langgraph dev` watch mode 自动重启，再重新运行

### 7.2 当前仓库里，Studio 不能当成什么

#### 不能直接在页面里改 graph 流程

当前 graph 结构仍然是代码定义：

- `planner/graph.py`
- `docgen/graph.py`
- `unified/graph.py`
- `kg/graph.py`

所以：

- 要改节点编排、路由、边、并发 fan-out
- 正确路径是改代码，不是改 Studio 页面

#### 不能把“页面里改 prompt / tool / assistant 配置”当成当前仓库的通用能力承诺

从当前仓库实现看：

- 没有暴露 Studio 可编辑的配置 schema
- 没有把 prompt / tool 选择系统性接成“页面可改配置”
- `graph_export.py` 只导出图展示元数据和 prompt 名称说明，不是可编辑 runtime config

当前真实情况更接近：

- prompt 主要还是代码里的常量或 prompt builder
- tool 选择主要还是代码路径里的调用与白名单
- 正确工作流是：

```text
改代码 -> langgraph dev 自动重启 -> 在 Studio 重跑
```

### 7.3 官方文档里提到的 Studio 配置化能力，和本仓库是什么关系

官方 Studio 的确支持一部分更强的调试 / 配置能力，例如：

- 本地 Agent Server
- thread / checkpoint 视角
- fork / rerun / inspect
- 某些场景下的 assistant / prompt 迭代

但这些能力要在仓库里“真正变成好用的 UI 配置项”，通常需要项目主动把配置字段接出来。

本仓库当前**还没有**把这层配置化暴露完整接好。
所以文档里的默认口径应当是：

- **Studio 现在主要用于运行、观察、定位、重跑**
- **不是当前仓库里的通用可视化配置后台**

---

## 8. Prompt 与工具的改动落点

如果你是边调边改，先看下面这张地图。

### 8.1 Prompt 落点

- Planner prompt：
  - `backend/app/workflows/digest/prompts/planner_prompts.py`
- DocGen prompt：
  - `backend/app/workflows/digest/prompts/docgen_prompts.py`
- KG prompt：
  - `backend/app/workflows/digest/prompts/kg_prompts.py`

当前 Digest 的命名 prompt span 也主要集中在这些文件里。

### 8.2 节点编排落点

- Planner graph：
  - `backend/app/workflows/digest/planner/graph.py`
- DocGen graph：
  - `backend/app/workflows/digest/docgen/graph.py`
- Unified graph：
  - `backend/app/workflows/digest/unified/graph.py`
- KG graph：
  - `backend/app/workflows/digest/kg/graph.py`

### 8.3 Tool / runtime 边界

Digest 当前并不是一个“主要靠 agent loop 调工具”的 workflow 家族。
它更多是：

- graph node
- workflow-local runtime
- retriever / reader
- prompt builder
- LLM 调用

所以如果你想改 Digest 的“工具行为”，通常要先分清是在改哪一层：

- prompt 里推荐工具标签
- runtime 里直接调用的 helper
- infra 层 retriever / reader / tool registry

不要默认把 Digest 理解成 Interact 那种“一个 node 里主要靠 tool-calling 驱动”的图。

---

## 9. 推荐的日常调试流程

如果你接下来主要调 Digest，建议日常就按这个顺序：

1. 先跑 `digest_planner`
   看 prompt、grounding、plan 合同。
2. 再跑 `digest_unified`
   看主链有没有把 docs / graph / curriculum 串起来。
3. 只在需要隔离文档问题时，单独跑 `digest_docgen`
   但记得带 `confirmed_plan`。
4. 只在已经掌握上下游前置状态时，单独跑 `digest_kg` 或 `digest_curriculum`。
5. 顶层路径没问题后，再开 LangSmith 看 prompt / retriever / runtime 细节。

一句话版：

```text
先看图，再看 state，再看 tracked_step，最后再看最深的 LangSmith span。
```

---

## 10. 官方资料

下面这些是这份文档最相关、也最值得直接看的官方页面：

- Local server / `langgraph dev`
  - https://docs.langchain.com/langsmith/local-server
- Studio quickstart
  - https://docs.langchain.com/langsmith/quick-start-studio
- Studio / 本地连接与使用
  - https://docs.langchain.com/langsmith/studio
- Studio 中查看 thread、编辑节点状态、fork / rerun
  - https://docs.langchain.com/langsmith/use-studio
- Threads / checkpoints / inspect
  - https://docs.langchain.com/langsmith/use-threads
- Time-travel / replay / fork
  - https://docs.langchain.com/oss/python/langgraph/use-time-travel
- Prompt 管理与 Playground
  - https://docs.langchain.com/langsmith/create-a-prompt

如果后面仓库要继续演进成“Studio 页面里可编辑更多 runtime 配置”的模式，下一步通常不是改这份文档，而是先把配置 schema 与 assistant 级配置真正接出来。
