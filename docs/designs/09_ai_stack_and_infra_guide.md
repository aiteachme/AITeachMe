# 09. AI 技术栈与 Infra 接入指南

最后更新：2026-04-19

本文说明当前 AI 能力和基础设施如何接入代码，不再记录历史重构计划。

## 1. 总原则

AITeachMe 的 AI 工程分三层：

```text
规则层：校验、状态流转、客观判分、路径处理
模型层：生成、抽取、改写、判定、OCR
工作流层：多步骤长流程、并发、失败恢复、观测
```

原则：

- 不把所有问题都丢给大模型。
- 代码要优先消费结构化输出。
- Search 只找来源，不直接产最终教学答案。
- Workflow 决定业务策略，Infra 只接能力。

## 2. 当前核心技术栈

| 能力 | 当前技术 / 入口 |
| --- | --- |
| LLM 文本/结构化/流式 | `shared.infra.llm_support` + LiteLLM |
| Embedding | `shared.infra.embedding` |
| Workflow | LangGraph + `shared.infra.workflow` |
| 本地向量索引 | `shared.infra.search.llamaindex_index` |
| 检索与读取 | `shared.infra.search` |
| 工具执行 | `shared.infra.tools` |
| MCP | `shared.infra.mcp` |
| 存储 | `shared.infra.storage` |
| 观测 | `shared.infra.observability` |

## 3. 模型路由

模型名来自 `settings_default.yaml`，用户可在设置页保存非敏感覆盖。

当前逻辑名：

| 逻辑模型 | 用途 |
| --- | --- |
| `reason` | 规划、复杂判断、深度推理 |
| `primary` | 对话、写作、出题、批改、OCR 默认回退 |
| `light` | 分类、摘要、批量轻任务、Mermaid 文本生成 |
| `extract` | 知识抽取，空值时回退 light/primary |
| `embedding` | 向量检索 |
| `ocr` | Vision OCR，空值时使用 primary |
| `image_generation` | 文生图，空值时禁用真实图片生成 |

注意：

- `TaskType` 表示业务语义、温度、超时、重试和观测分类。
- 模型选择优先显式传 `model="reason" / "primary" / "light"`。
- Mermaid 不再有独立模型配置，直接走普通轻量文本模型。

## 4. 结构化输出

凡是后续会被代码消费的 LLM 结果，都优先 Pydantic / structured output。

典型场景：

- Planner plan intent / plan draft。
- DocGen chapter contract、evidence ledger、review report。
- KG 抽取与解析。
- Examine 出题和判卷结果。
- Profile 报告和建议。

规则：

- schema 字段少而稳。
- 字段含义能落库、渲染或被后续 workflow 消费。
- 失败要可重试、可降级、可记录。

## 5. Search / RAG

当前 search 层包含：

- 本地 `local_rag`
- 外部 retriever
- reader
- source curation
- context compression
- rerank

已接入 retriever：

```text
local_rag
duckduckgo
wikipedia
tavily / bocha / brave / exa / bing
google_cse / serper / serpapi / searchapi
perplexity / openrouter_search / baidu_ai_search
arxiv / semantic_scholar / pubmed_central
baidu_baike / zhihu
jina_search / custom_endpoint / mcp_search
```

规则：

- 需要 key 的 provider 未配置时自动跳过。
- 无 key 默认至少可用 `duckduckgo`。
- 答案型搜索只抽取 citations / references 为 `SearchResult`。
- 最终教学表达仍由 workflow 决定。

## 6. Ingest 解析栈

当前解析策略不是“一个万能 parser”，而是：

```text
分类 -> 解析计划 -> parser chain -> Markdown canonicalize -> 后台增强
```

常用能力：

- 文本快速通道。
- MarkItDown / PyMuPDF / PyMuPDF4LLM 等本地 parser。
- MinerU 外部解析。
- Vision OCR。
- assets 规范化。

## 7. 观测

观测分两层：

- LangSmith trace：研发排障。
- progress / build status：前端展示。

当前可记录：

- 模型名。
- token / cost。
- 耗时。
- 检索 provider。
- reader 结果。
- cache hit。
- workflow 节点状态。

## 8. 不再使用的抽象

以下抽象已经删除或不再作为正式架构：

- `shared.infra.facade`
- `shared.infra.guardrails`
- `app.services`
- `app.teaching`
- 独立 prompt 扩展层

## 9. 一句话

当前 AI 路线是：

```text
稳定材料层 + 结构化合同 + 显式 workflow + 可追踪来源
```

不是把系统改成一个黑盒大 Agent。
