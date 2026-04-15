# Workflows 调试指南

最后更新：2026-04-15

这份文档只讲三件事：

1. 先从哪一层开始调 workflow
2. `langgraph dev` 在这个仓库里怎么用
3. 什么时候看 Studio，什么时候看 LangSmith

## 先选调试面

同一个问题通常有 3 条路径：

| 调试面 | 适合查什么 | 什么时候优先用 |
| --- | --- | --- |
| 真实业务链路（FastAPI / service） | 鉴权、后台任务、锁、持久化、副作用 | 你怀疑问题不在 graph 本身 |
| `langgraph dev` + Studio | graph 拓扑、节点流转、state、输入输出、分叉重跑 | 你要看“这条 workflow 怎么跑起来” |
| LangSmith trace | prompt、LLM、retriever、tool、runtime 边界、耗时 | 你要查“为什么这一步慢 / 为什么结果不对” |

推荐顺序：

1. 先看 graph 顶层是否跑对
2. 再看 state 输入输出
3. 最后再看 LangSmith 细节

## `langgraph dev` 入口

入口集中在 [../../langgraph.json](../../langgraph.json)。

当前常用 graph：

- `ingest_fast_parse`
- `ingest_deep_enhance`
- `digest_planner`
- `digest_docgen`
- `digest_unified`
- `digest_kg`
- `digest_curriculum`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

对知识文档主链来说，最适合优先调的是：

1. `digest_planner`
2. `digest_unified`
3. `digest_docgen`

## `langgraph dev` 怎么跑

在 `backend/` 目录执行：

```bash
cd backend
conda activate atm
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

## 如果 `langgraph dev` 报 BlockingError

排查顺序建议是：

1. 先确认是不是某个第三方库首次导入触发了阻塞初始化
2. 再确认是不是 workflow 节点里直接写了同步 I/O
3. 实在无法改造时，最后再考虑 `--allow-blocking` 一类兜底方案

优先修代码，不要把“允许阻塞”当成正常方案。

## Studio 里应该看什么

Studio 很适合看这些东西：

- graph 拓扑
- 顶层 node 顺序
- 每个 node 前后的 state 变化
- 输入输出 schema 是否合理
- 同一条运行的分叉重跑

但不要把 Studio 当成：

- 在线改 graph 的设计器
- 线上真相源
- 复杂内部 state 的全量展示面板

## 为什么要收口 Studio schema

如果直接把整个内部 state 暴露给 Studio，会有几个问题：

- 输入表单很臃肿
- 输出页面会塞满内部中间态
- workflow 作者会为了 Studio 被迫维护多份重复 schema

当前推荐模式是：

1. 内部维护完整 `State`
2. 只给 Studio 暴露必要输入输出字段
3. 用 `project_typed_dict_schema(...)` 从主 `State` 投影，不手写重复类型

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

