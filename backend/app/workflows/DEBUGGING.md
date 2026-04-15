# Workflows 调试指南

最后更新：2026-04-15

这份文档回答的是：

- 从哪一层开始调一个 workflow
- `langgraph dev` 在这个仓库里怎么用
- 什么时候看 Studio，什么时候看 LangSmith

它不重复下面两份规范：

- [LANGSMITH.md](./LANGSMITH.md)
- [PROGRESS.md](./PROGRESS.md)

## 先选调试面

同一个问题，通常有 3 条调试路径：

| 调试面 | 适合查什么 | 什么时候优先用 |
| --- | --- | --- |
| 真实业务链路（FastAPI / service） | 鉴权、后台任务、锁、持久化、副作用 | 你怀疑问题不在 graph 本身 |
| `langgraph dev` + Studio | graph 拓扑、节点流转、state、输入输出、分叉重跑 | 你要看“这条 workflow 怎么跑起来” |
| LangSmith trace | prompt、LLM、retriever、tool、runtime 边界、耗时 | 你要查“为什么这一步慢 / 为什么结果不对” |

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

对 Digest 主链来说最重要的是：

- `digest_planner`
- `digest_docgen`
- `digest_unified`

## `langgraph dev` 怎么跑

在 `backend/` 目录执行：

```bash
cd backend
conda activate atm
pip install -e .
pip install -U "langgraph-cli[inmem]"
langgraph dev --config langgraph.json
```

如果只想先看本地 graph / state，不想把 trace 发到 LangSmith：

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

## 如果 `langgraph dev` 报 BlockingError

这类错误的本质是：

- 有同步阻塞调用在异步请求路径里被 LangGraph dev 检测到了
- 它不一定是 workflow graph 逻辑本身错了，而可能是某个依赖在第一次懒加载时做了阻塞初始化

当前仓库已经做过一层处理：

- LiteLLM 的导入经过统一 loader
- 会提前关闭 `python-dotenv` 的隐式扫描，避免开发态首次导入时触发 `os.getcwd()` 一类阻塞调用

如果你仍然遇到 BlockingError，排查顺序建议是：

1. 先确认是不是某个第三方库首次导入触发
2. 再确认是不是 workflow 节点里直接写了同步 I/O
3. 仍无法改造时，最后再考虑 `--allow-blocking` 或隔离 loop 这种兜底方案

优先修代码，不要把“允许阻塞”当正常方案。

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

示意写法：

```python
from app.shared.infra.workflow import project_typed_dict_schema

ExampleGraphInput = project_typed_dict_schema(
    ExampleState,
    name="ExampleGraphInput",
    fields=["subject", "file_ids"],
)
```

这意味着：

- `State` 是唯一真相源
- Studio schema 只是字段白名单
- 不再每个 workflow 都维护 `State + Input + Output` 三份重复定义

## Digest 推荐调试顺序

### 1. `digest_planner`

最适合先调它，因为：

- 图最小，只有 3 个顶层 node
- 观测层最收敛
- 问题通常集中在 prompt、grounding、plan 合同

### 2. `digest_unified`

适合做 Digest 主链端到端调试，因为它是总入口。

### 3. `digest_docgen`

适合隔离文档构建问题，但它不是完全无前提的独立图。

高风险前置条件：

- 它依赖 confirmed plan
- 没有前置方案时，`load_context` 很可能直接失败

### 4. `digest_kg` / `digest_curriculum`

更适合在你已经掌握上下游前置状态后做定向排查，不建议第一次上手就从这里开始。

## 现在该怎么看 LangSmith

短答案：

先看顶层 graph，再看 LangSmith 细节。

原因是当前仓库已经收口成：

- LangGraph 自动提供 root / node span
- `workflow_tracer(...).node(...)` 只补上下文，不再手工创建第二个 node span
- workflow 内部如果需要额外子层，优先通过提 helper 并使用官方 `@traceable`

推荐阅读顺序：

1. 先看 graph 顶层节点是否按预期推进
2. 再看每个节点前后的 state diff
3. 最后看 LangSmith 里的 prompt / retriever / runtime 子层

不要再按旧习惯去找：

- `tracked_step`
- 本地 runtime step 生命周期
- 第二套 trace / track 状态机

这些都已经不是当前规范的一部分。

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
4. 已掌握前置状态时，再单独跑 `digest_kg` 或 `digest_curriculum`
5. 顶层路径没问题后，再开 LangSmith 看 prompt / retriever / runtime 细节

一句话版：

```text
先看图，再看 state，最后再看 LangSmith 细节。
```
