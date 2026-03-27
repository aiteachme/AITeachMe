# Core — AI 基础设施层

> 五大引擎（Ingest / Digest / Interact / Examine / Profile）的公共底座。
> 所有改动仅限此目录，上层代码零侵入。

## 定位

`/core` 是纯基础设施，**不包含任何业务逻辑**。它为 `/workflows` 和 `/agents` 提供：

- 统一的 LLM 调用入口（模型路由、重试、并发控制、追踪）
- **Agent Loop — 工具增强的 LLM 推理循环（ReAct 模式）**
- **记忆系统 — 跨会话持久化 + 用户画像**
- **搜索管线 — Web 搜索 + 知识库混合检索**
- **Skill 框架 — 可加载的教学技能（OpenClaw SKILL.md 规范）**
- 安全防护（护栏管线）
- 推理策略（CoT、反思、规划）
- 状态管理（Token 预算、缓存）
- 工具扩展（函数注册、LLM function calling）

## 文件结构

```
core/
│
│  基础文件（稳定）
├── config.py              配置中心
├── database.py            数据库连接
├── exceptions.py          异常定义
├── logger.py              结构化日志
├── prompt_loader.py       Jinja2 模板渲染
│
│  LLM 调用层
├── llm.py                 LLM 入口 — 文本/结构化/流式/工具调用补全
├── embedding.py           向量化 — 自动分批 + 限流
├── model_router.py        按任务类型选模型
│
│  Agent Loop
├── agent_loop.py          🔥 工具增强推理循环（ReAct 模式）
│
│  记忆系统
├── memory/                🔥 多层记忆
│   ├── __init__.py        对外 API：remember / recall / get_user_profile
│   ├── api.py             顶层函数实现
│   ├── types.py           数据类型定义
│   ├── store.py           SQLite 持久化存储
│   └── profile.py         用户画像 UserProfile
│
│  搜索管线
├── search/                🔥 Web + 知识库搜索
│   ├── __init__.py        对外 API：web_search / search_knowledge
│   ├── api.py             统一搜索入口
│   ├── types.py           搜索结果类型
│   └── web.py             Web 搜索提供商（DuckDuckGo 等）
│
│  Skill 框架（代码层 — 定义在 /backend/skills/）
├── skills/                🔥 教学技能引擎（OpenClaw 规范）
│   ├── __init__.py        对外 API：run_skill / list_skills
│   ├── api.py             技能执行入口
│   ├── base.py            @skill 装饰器 + SkillRegistry
│   └── loader.py          SKILL.md 多路径加载器
│
│  工具注册（定义在 /backend/tools/）
├── tools/                 工具注册与调用
│   ├── definition.py      ToolDefinition 数据结构
│   ├── registry.py        ToolRegistry（注册、查询、执行）
│   ├── decorator.py       @tool 装饰器
│   ├── tool_loader.py     Tool YAML 多路径加载器
│   └── builtin/           内置工具实现
│       ├── web_search.py  Web 搜索
│       ├── search_kb.py   知识库检索
│       └── memory_ops.py  记忆读写
│
│  其他能力
├── tracing.py             调用追踪
├── reasoning.py           推理策略
├── token_budget.py        Token 预算 + 上下文组装
├── cache.py               LLM 响应缓存
├── retrievers.py          检索管线基础框架
├── reranker.py            重排序
├── strategies.py          策略编排
│
│  安全护栏
├── guardrails/            安全护栏
│   ├── base.py            基类
│   ├── builtin.py         内置护栏
│   └── pipeline.py        护栏管线
│
│  设计文档
└── .docs/                 核心能力设计文档
```

## 快速上手

```python
# ── 原有代码完全不变 ──
from app.core.llm import acompletion
result = await acompletion(messages=[...])

# ── Agent Loop — 让 LLM 自动调工具 ──
from app.core.agent_loop import run_agent_loop
result = await run_agent_loop(messages, tools=["search_kb", "web_search"])
answer = result.final_answer

# ── 流式 Agent Loop ──
from app.core.agent_loop import run_agent_loop_stream
async for chunk in run_agent_loop_stream(messages, tools=["search_kb"]):
    print(chunk, end="")

# ── 记忆 — 记住 / 回忆 / 画像 ──
from app.core.memory import remember, recall, get_user_profile

await remember("用户线性代数较弱", user_id="u1", tag="weakness")
entries = await recall("线性代数", user_id="u1")
profile = await get_user_profile("u1")
messages = [profile.to_system_message()] + other_messages

# ── 搜索 — Web + 知识库 ──
from app.core.search import web_search, search_knowledge

web_results = await web_search("贝叶斯定理 教程")
kb_chunks = await search_knowledge("特征值", subject_id="linear-algebra")

# ── Skill — 执行教学技能 ──
from app.core.skills import run_skill, list_skills

result = await run_skill("find_resources", topic="微积分")
all_skills = list_skills()

# ── 工具注册 ──
from app.core.tools import tool
@tool("my_tool", "自定义工具描述")
async def my_tool(query: str) -> str: ...
```

## 与 /workflows 的关系

```
/workflows                           /core
├── common/context.py  运行时上下文   ← 不冲突，core 叫 token_budget.py
├── ingest/   用 llm + embedding     ← core 提供统一调用 + 批处理
├── digest/   用 llm + embedding     ← core 提供模型路由 + 追踪
├── interact/ 用 llm_stream          ← core 提供 Agent Loop + 记忆 + 搜索
├── examine/  用 asyncio.gather      ← core 提供记忆（出题参考薄弱点）
└── profile/  用 llm                 ← core 提供用户画像 + 追踪
```
