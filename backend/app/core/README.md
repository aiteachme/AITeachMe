# Core — AI 基础设施层

> 五大引擎（Ingest / Digest / Interact / Examine / Profile）的公共底座。
> 所有改动仅限此目录，上层代码零侵入。

## 定位

`/core` 是纯基础设施，**不包含任何业务逻辑**。它为 `/workflows` 和 `/agents` 提供：

- 统一的 LLM 调用入口（模型路由、重试、并发控制、追踪）
- 安全防护（护栏管线）
- 工具扩展能力（函数注册、LLM function calling）
- 推理策略（CoT、反思、规划）
- 状态管理（记忆、Token 预算、缓存）
- 检索管线（向量 + 关键词）
- 策略编排（模式选择）

## 文件结构

```
core/
│
│  原有文件（不动）
├── config.py           配置中心
├── database.py         数据库连接
├── exceptions.py       异常定义
├── logger.py           结构化日志
├── prompt_loader.py    Jinja2 模板渲染
│
│  改造文件（向后兼容）
├── llm.py              LLM 入口 — 模型路由 + 调用追踪 + 并发控制
├── embedding.py        向量化 — 自动分批 + 限流
│
│  新增单文件
├── model_router.py     按任务类型选模型
├── tracing.py          调用追踪（LLMCallRecord + Span + Tracker）
├── reasoning.py        推理策略（Direct / CoT / Reflect / Plan-and-Solve）
├── memory.py           记忆管理（短期 / 长期 / 语义）
├── token_budget.py     Token 预算 + 上下文智能组装
├── cache.py            LLM 响应缓存（哈希 + TTL + LRU）
├── retrievers.py       检索管线（向量 + 关键词 + rerank）
├── strategies.py       策略编排（模式注册 + 意图匹配）
│
│  新增目录
├── tools/              工具注册与调用
│   ├── definition.py   ToolDefinition 数据结构
│   ├── registry.py     ToolRegistry（注册、查询、执行）
│   └── decorator.py    @tool 装饰器
│
└── guardrails/         安全护栏
    ├── base.py         InputGuardrail / OutputGuardrail 基类
    ├── builtin.py      ContentSafety + PII 过滤
    └── pipeline.py     GuardrailPipeline 编排
```

## 与 /workflows 的关系

```
/workflows                          /core
├── common/context.py  运行时上下文   ← 不冲突，core 叫 token_budget.py
├── ingest/   用 llm + embedding     ← core 提供统一调用 + 批处理
├── digest/   用 llm + embedding     ← core 提供模型路由 + 追踪
├── interact/ 用 llm_stream          ← core 提供并发控制 + 缓存
├── examine/  用 asyncio.gather      ← core 的 Semaphore(5) 限流
└── profile/  用 llm                 ← core 提供追踪 + 统计
```

## 快速上手

```python
# 原有代码完全不变
from app.core.llm import acompletion
result = await acompletion(messages=[...])

# 想用新功能？加个参数
from app.core.model_router import TaskType
result = await acompletion(messages=[...], task_type=TaskType.CHAT)

# 注册工具
from app.core.tools import tool
@tool("search", "搜索知识库")
async def search(query: str) -> str: ...

# 护栏
from app.core.guardrails import GuardrailPipeline, ContentSafetyGuardrail
pipeline = GuardrailPipeline().add_input(ContentSafetyGuardrail(["违禁词"]))
```
