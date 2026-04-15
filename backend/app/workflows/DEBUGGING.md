# Workflows 调试指南

最后更新：2026-04-15

这份文档回答的是：

- 从哪一层开始调一个 workflow
- `langgraph dev` 在这个仓库里怎么用
- 什么时候该看 Studio，什么时候该看 LangSmith

它不重复下面两份规范：

- [LANGSMITH.md](./LANGSMITH.md)
- [PROGRESS.md](./PROGRESS.md)

## 先选调试面

同一个问题，通常有 3 条调试路径：

| 调试面 | 适合查什么 | 什么时候优先用 |
| --- | --- | --- |
| 真实业务链路（FastAPI / service） | 鉴权、后台任务、锁、持久化、副作用 | 你怀疑问题不在 graph 本身 |
| `langgraph dev` + Studio | graph 拓扑、节点流转、state、分叉重跑、本地断点 | 你要看“这条 workflow 是怎么跑起来的” |
| LangSmith trace | prompt、LLM、retriever、tool、runtime 边界、耗时 | 你要查“为什么这一步慢 / 为什么 prompt 不对” |

推荐顺序：

1. 先用 `langgraph dev` 看 graph 顶层是否跑对
2. 顶层对了，再看 LangSmith trace
3. 只有怀疑 service / DB / 文件系统时，才回到真实业务链路

## 仓库当前支持的 `langgraph dev` 入口

入口集中在 [backend/langgraph.json](../../langgraph.json)。

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

对 Digest 来说最重要的是：

- `digest_planner`
- `digest_docgen`
- `digest_unified`
- `digest_kg`
- `digest_curriculum`

## `langgraph dev` 怎么跑

在 `backend/` 目录执行：

```bash
cd backend
pip install -e .
pip install -U "langgraph-cli[inmem]"
langgraph dev --config langgraph.json
```

如果只想看本地 graph / state，不想把 trace 发到 LangSmith：

```env
LANGSMITH_TRACING=false
```

如果想同时看 Studio 和 LangSmith：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=AITeachMe
```

经验上：

- 第一次把 graph 跑通时，先关 `LANGSMITH_TRACING`
- 顶层节点走顺之后，再开 LangSmith 看 prompt / retriever / runtime 细节

## Digest 推荐调试顺序

### 1. `digest_planner`

最适合先调它，因为：

- 顶层图最小，只有 3 个 node
- 现在的 planner 观测层也最收敛
- 主要问题通常集中在 prompt、grounding、plan 合同

### 2. `digest_unified`

最适合做端到端 Digest 主链调试，因为它是当前 `build_type=all` 的总入口。

### 3. `digest_docgen`

适合隔离文档链，但它不是无前提的独立玩具图。

高风险前置条件：

- 它要求 `confirmed_plan`
- 没有已确认方案时，`load_context` 会直接失败

### 4. `digest_kg` / `digest_curriculum`

更适合在你已经掌握上游前置状态后做定向排查，不建议作为第一次上手样例。

## 现在该怎么看 LangSmith

短答案：

先看顶层 graph，再看 LangSmith 细节，不要一上来就钻最深 span。

原因是当前仓库已经收口成：

- LangGraph 自动提供 root / node span
- `workflow_tracer(...).node(...)` 只补上下文，不再手工创建第二个 node span
- workflow 内部如果需要额外子层，优先通过提取 helper 并使用官方 `@traceable`

推荐阅读顺序：

1. 先看 graph 顶层节点是否按预期推进
2. 再看每个节点前后的 state diff
3. 再看 LangSmith 里 prompt / retriever / runtime 的子层

不要再按旧习惯去找：

- `tracked_step`
- 本地 runtime step 生命周期
- 第二套 trace / track 状态机

这些已经不是当前规范的一部分。

## Studio 里能做什么，不能做什么

### 能做什么

- 跑 graph
- 看 graph 拓扑
- 看 node 执行顺序
- 看 state 输入 / 输出
- 配合 LangSmith trace 看 prompt、LLM、retriever、runtime 边界
- 改完本地代码后重新运行验证

### 不能当成什么

- 不能直接在页面里改 graph 流程
- 不能把“页面里改 prompt / tool / assistant 配置”当成当前仓库的通用能力承诺

当前真实工作流仍然是：

```text
改代码 -> langgraph dev 自动重启 -> 在 Studio 重跑
```

## Prompt 与节点改动落点

### Prompt 落点

- Planner prompt：
  `backend/app/workflows/digest/prompts/planner_prompts.py`
- DocGen prompt：
  `backend/app/workflows/digest/prompts/docgen_prompts.py`
- KG prompt：
  `backend/app/workflows/digest/prompts/kg_prompts.py`

### 节点编排落点

- Planner graph：
  `backend/app/workflows/digest/planner/graph.py`
- DocGen graph：
  `backend/app/workflows/digest/docgen/graph.py`
- Unified graph：
  `backend/app/workflows/digest/unified/graph.py`
- KG graph：
  `backend/app/workflows/digest/kg/graph.py`

## 推荐的日常调试流程

1. 先跑 `digest_planner`
2. 再跑 `digest_unified`
3. 需要隔离文档问题时，单独跑 `digest_docgen`
4. 已掌握上下游前置状态时，再单独跑 `digest_kg` 或 `digest_curriculum`
5. 顶层路径没问题后，再开 LangSmith 看 prompt / retriever / runtime 细节

一句话版：

```text
先看图，再看 state，最后再看 LangSmith 细节。
```
