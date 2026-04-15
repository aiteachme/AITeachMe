# Workflows 调试指南

最后更新：2026-04-15

这份文档只讲三件事：

1. 先从哪一层开始调 workflow
2. `langgraph dev` 在这个仓库里怎么用
3. 什么时候看 Studio，什么时候看 LangSmith

## 先选调试面

同一个问题通常有 3 条路径：

| 调试面 | 适合查什么 |
| --- | --- |
| 真实业务链路（FastAPI / service） | 鉴权、后台任务、锁、持久化、副作用 |
| `langgraph dev` + Studio | graph 拓扑、节点流转、state、分叉重跑 |
| LangSmith trace | prompt、LLM、retriever、tool、runtime 边界、耗时 |

推荐顺序：

1. 先看 graph 顶层是否跑对
2. 再看 state 输入输出
3. 最后再看 LangSmith 细节

## `langgraph dev` 入口

入口集中在 [../../langgraph.json](../../langgraph.json)。

当前常用 graph：

- `digest_planner`
- `digest_docgen`
- `digest_unified`
- `digest_kg`
- `digest_curriculum`
- `ingest_fast_parse`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

## `langgraph dev` 怎么跑

在 `backend/` 目录执行：

```bash
cd backend
pip install -e .
pip install -U "langgraph-cli[inmem]"
langgraph dev --config langgraph.json
```

如果只看本地 graph / state：

```env
LANGSMITH_TRACING=false
```

如果要同时看 Studio 和 LangSmith：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=AITeachMe
```

经验规则：

- 第一次跑通 graph 时，先关 `LANGSMITH_TRACING`
- 顶层节点走顺后，再开 LangSmith 看 prompt / runtime 细节

## Digest 推荐调试顺序

1. `digest_planner`
   顶层图最小，最适合先看 contract 和 prompt
2. `digest_unified`
   最适合做 Digest 端到端验证
3. `digest_docgen`
   适合隔离文档链，但前提是 confirmed plan 已经存在
4. `digest_kg` / `digest_curriculum`
   更适合在掌握上游前置状态后做定向排查

## Prompt 与节点落点

- Planner prompt：`backend/app/workflows/digest/prompts/planner_prompts.py`
- DocGen prompt：`backend/app/workflows/digest/prompts/docgen_prompts.py`
- KG prompt：`backend/app/workflows/digest/prompts/kg_prompts.py`

- Planner graph：`backend/app/workflows/digest/planner/graph.py`
- DocGen graph：`backend/app/workflows/digest/docgen/graph.py`
- Unified graph：`backend/app/workflows/digest/unified/graph.py`
- KG graph：`backend/app/workflows/digest/kg/graph.py`

## 一句话版

```text
先看图，再看 state，最后看 LangSmith 细节。
```

