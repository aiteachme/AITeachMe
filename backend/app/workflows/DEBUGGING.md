# Workflows 调试指南

最后更新：2026-04-15

这份文档只回答三个问题：

1. 先从哪一层开始查 workflow
2. `langgraph dev` 在这个仓库里怎么跑
3. 什么时候看 Studio，什么时候看 LangSmith

## 1. 先看哪一层

推荐顺序：

1. 先看链路 `graph.py`
2. 再看 `state.py`
3. 再看 `nodes/`
4. 最后看 LangSmith 的 prompt / retriever / tool trace

如果问题看起来像“整条链路没按预期走”，优先看 graph。
如果问题像“某一步结果不对”，优先看对应 node 和 lib。

## 2. langgraph dev 入口

入口统一配置在 [backend/langgraph.json](../../backend/langgraph.json)。

当前主要图：

- `ingest_fast_parse`
- `ingest_deep_enhance`
- `digest_planner`
- `digest_docgen`
- `digest_kg`
- `interact_chat`
- `examine_question_build`
- `examine_exam_grade`
- `profile_pipeline`

其中已经切到 canonical lane 路径的有：

- `interact/chat/graph.py`
- `examine/question_build/graph.py`
- `examine/exam_grade/graph.py`
- `profile/pipeline/graph.py`

## 3. 运行方式

在 `backend/` 目录执行：

```bash
cd backend
conda activate atm
pip install -e .
pip install -U "langgraph-cli[inmem]"
langgraph dev --config langgraph.json
```

如果只是看本地图和 state，先关闭 LangSmith：

```env
LANGSMITH_TRACING=false
```

如果要同时看 Studio 和 LangSmith：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=AITeachMe
```

## 4. Studio 适合看什么

Studio 适合：

- 图拓扑
- 节点执行顺序
- state 的前后变化
- `Send` 分发是否符合预期

Studio 不适合：

- 深挖 prompt 内容质量
- 排查底层 retriever / tool 调用细节
- 分析 token 和耗时热点

这些问题请看 LangSmith。

## 5. Prompt 与图入口

Planner：

- graph: `backend/app/workflows/digest/planner/graph.py`
- prompts: `backend/app/workflows/digest/planner/prompts/`

DocGen：

- graph: `backend/app/workflows/digest/docgen/graph.py`
- prompts: `backend/app/workflows/digest/docgen/prompts/`

Interact：

- graph: `backend/app/workflows/interact/chat/graph.py`

Examine：

- graph: `backend/app/workflows/examine/question_build/graph.py`
- graph: `backend/app/workflows/examine/exam_grade/graph.py`

Profile：

- graph: `backend/app/workflows/profile/pipeline/graph.py`

## 6. 一句话建议

先看图，再看状态，再看节点内部实现；不要一上来就扎进 LangSmith 追细节。
