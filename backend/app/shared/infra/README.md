# Infra — AI 平台引擎层

> 五大引擎（Ingest / Digest / Interact / Examine / Profile）的公共 AI 底座。
> 所有 AI 能力集中在此，上层 `workflows/` 通过 `from app.shared.infra.xxx` 调用。

---

## 目录

- [目录](#目录)
- [1. 定位与设计原则](#1-定位与设计原则)
  - [设计原则](#设计原则)
- [2. 目录结构](#2-目录结构)
- [3. LLM 调用层](#3-llm-调用层)
  - [核心函数](#核心函数)
- [4. Agent Loop — 工具增强推理](#4-agent-loop--工具增强推理)
- [5. Memory — 记忆与用户画像](#5-memory--记忆与用户画像)
  - [MemoryTag 标签](#memorytag-标签)
  - [LEARNER.md — 学习者档案](#learnermd--学习者档案)
- [6. Search — Web 搜索与知识库检索](#6-search--web-搜索与知识库检索)
- [7. Skills — 教学技能框架](#7-skills--教学技能框架)
- [8. Tools — 工具注册与管理](#8-tools--工具注册与管理)
- [9. Context — 教学上下文组装器](#9-context--教学上下文组装器)
- [10. Events — 教学事件日志](#10-events--教学事件日志)
- [11. Checker — 自动判卷与评分](#11-checker--自动判卷与评分)
- [12. Teaching — 教学函数](#12-teaching--教学函数)
- [13. MCP — 外部工具协议](#13-mcp--外部工具协议)
- [14. Security — 安全确认门](#14-security--安全确认门)
- [15. Sandbox — 实验环境](#15-sandbox--实验环境)
- [16. 其他基础模块](#16-其他基础模块)
- [17. 与 /workflows 的关系](#17-与-workflows-的关系)
  - [典型数据流](#典型数据流)

---

## 1. 定位与设计原则

`/infra` 是 **AI 平台引擎层**，封装了 LLM 调用、向量检索、Agent 编排、教学能力等所有 AI 相关基础能力。
应用基础设施（config / database / exceptions / logger / runtime_paths）位于 [`core/`](../core/README.md)。

### 设计原则

| 原则 | 说明 |
|------|------|
| **一行 import，一次调用** | 外部模块使用 infra 只需 `from app.shared.infra.xxx import func` + `await func(...)` |
| **中文优先** | 提示词、标签、错误信息默认中文 |
| **零配置即可用** | 不装额外包也不报错，只是功能降级（如 DuckDuckGo 搜索） |
| **可扩展** | 新增工具/技能/搜索提供商只需加文件，不改已有代码 |
| **对外极简 API** | 所有模块对外只暴露 2~5 个顶层函数 |

---

## 2. 目录结构

```
infra/
│  LLM 调用
├── llm.py                 LLM 补全入口（文本/结构化/流式/工具调用）
├── embedding.py           向量化（分批 + 限流）
├── model_router.py        按任务类型选模型
│
│  LLM 辅助
├── token_budget.py        Token 预算 + 上下文截断
├── cache.py               LLM 响应缓存
├── prompt_loader.py       Jinja2 Prompt 模板引擎
│
│  观测与推理
├── tracing.py             调用追踪
├── reasoning.py           推理策略（CoT / 反思）
│
│  检索
├── retrievers.py          检索管线
├── reranker.py            Rerank 重排序
│
│  Agent / 编排
├── agent_loop.py          🔥 ReAct 工具增强推理循环
├── strategies.py          策略编排
├── mcp.py                 🔥 Model Context Protocol 客户端
│
│  安全控制
├── security.py            🔥 工具调用安全确认门
│
│  教学能力
├── context.py             🔥 教学上下文自动组装
├── checker.py             🔥 Rubric 评分 + 多策略判定
├── teaching.py            🔥 教学策略级操作（解释/追问/出题/总结）
├── events.py              🔥 结构化事件日志（五大引擎回流基础）
├── sandbox.py             🔥 Lab Mode 实验沙箱抽象
│
│  子包
├── memory/                记忆系统 + 用户画像
│   ├── api.py             remember / recall / get_user_profile
│   ├── types.py           MemoryTag / MemoryEntry
│   ├── store.py           SQLite 持久化
│   ├── profile.py         UserProfile
│   └── learner_doc.py     🔥 LEARNER.md 学习者档案
│
├── search/                Web 搜索 + 知识库检索
│   ├── api.py             web_search / search_knowledge
│   ├── types.py           WebSearchResult
│   └── web.py             DuckDuckGo 搜索提供商
│
├── skills/                技能框架
│   ├── api.py             run_skill / list_skills
│   ├── base.py            @skill 装饰器 + SkillRegistry
│   └── loader.py          SKILL.md 多路径加载器
│
├── tools/                 工具注册 + 内置工具
│   ├── definition.py      ToolDefinition
│   ├── registry.py        ToolRegistry
│   ├── decorator.py       @tool 装饰器
│   ├── tool_loader.py     YAML 配置加载器
│   └── builtin/
│       ├── web_search.py  Web 搜索
│       ├── search_kb.py   知识库检索
│       └── memory_ops.py  记忆读写
│
└── guardrails/            安全护栏
    ├── base.py
    ├── builtin.py
    └── pipeline.py
```

---

## 3. LLM 调用层

**文件**：`llm.py`、`embedding.py`、`model_router.py`

### 核心函数

```python
from app.shared.infra.llm import acompletion, acompletion_stream, acompletion_with_tools
from app.shared.infra.embedding import aembed_texts

# 文本补全
answer = await acompletion(messages=[{"role": "user", "content": "你好"}])

# 流式补全
async for chunk in acompletion_stream(messages):
    print(chunk, end="")

# 工具调用补全（返回完整 response，含 tool_calls）
response = await acompletion_with_tools(messages, tools=[...])

# 向量化
embeddings = await aembed_texts(["文本1", "文本2"])
```

| 函数 | 用途 | 返回值 |
|------|------|--------|
| `acompletion()` | 普通文本补全 | `str` |
| `acompletion_stream()` | 流式补全 | `AsyncIterator[str]` |
| `acompletion_with_tools()` | 带工具的补全 | `ModelResponse`（含 tool_calls） |
| `aembed_texts()` | 批量向量化 | `list[list[float]]` |

---

## 4. Agent Loop — 工具增强推理

**文件**：`agent_loop.py`

让 LLM 自动调用工具完成任务。使用 ReAct 模式：`reason → tool_call → observe → repeat`。

```python
from app.shared.infra.agent_loop import run_agent_loop, run_agent_loop_stream

# 批量模式
result = await run_agent_loop(
    messages=[{"role": "user", "content": "帮我搜索贝叶斯定理的教程"}],
    tools=["web_search", "search_kb"],
    max_iterations=5,
)

# 流式模式
async for chunk in run_agent_loop_stream(
    messages=[{"role": "user", "content": "什么是特征值？"}],
    tools=["search_kb"],
):
    yield chunk
```

---

## 5. Memory — 记忆与用户画像

**文件**：`memory/`（`api.py` / `store.py` / `profile.py` / `types.py` / `learner_doc.py`）

跨会话记住用户信息，自动构建个性化教学画像。SQLite 持久化，首次使用自动建表。

```python
from app.shared.infra.memory import remember, recall, forget, get_user_profile

# 记忆
key = await remember("用户线性代数较弱", user_id="u1", tag="weakness", importance=0.8)

# 回忆
entries = await recall("线性代数", user_id="u1", top_k=5)

# 用户画像
profile = await get_user_profile("u1")
system_msg = profile.to_system_message()
```

### MemoryTag 标签

| 标签 | 用途 | 示例 |
|------|------|------|
| `preference` | 学习偏好 | "喜欢用类比解释" |
| `strength` | 擅长领域 | "Python 基础扎实" |
| `weakness` | 薄弱领域 | "概率论贝叶斯不熟" |
| `background` | 用户背景 | "大三计算机专业" |
| `note` | 学习笔记 | 任意笔记 |
| `insight` | 教学洞察 | "倾向于跳过推导直接看结论" |
| `general` | 通用 | 默认 |

### LEARNER.md — 学习者档案

**文件**：`memory/learner_doc.py`

```python
from app.shared.infra.memory import (
    read_learner_doc, write_learner_doc,
    update_learner_section, read_learner_section,
    sync_profile_to_doc, load_doc_to_context,
)

doc = await read_learner_doc("u1")
await update_learner_section("u1", "薄弱领域", "- 线性代数：特征值计算")
learner_ctx = await load_doc_to_context("u1")
```

---

## 6. Search — Web 搜索与知识库检索

**文件**：`search/`（`api.py` / `web.py` / `types.py`）

```python
from app.shared.infra.search import web_search, search_knowledge

results = await web_search("贝叶斯定理 直觉解释", top_k=5)
chunks = await search_knowledge("什么是特征值", subject_id="linear-algebra", top_k=5)
```

| 提供商 | 状态 | 配置 |
|--------|------|------|
| DuckDuckGo | ✅ 默认 | `pip install duckduckgo-search` |
| Serper | 🔜 计划 | `SERPER_API_KEY` |
| Tavily | 🔜 计划 | `TAVILY_API_KEY` |

---

## 7. Skills — 教学技能框架

**文件**：`skills/`（`api.py` / `base.py` / `loader.py`）

```python
from app.shared.infra.skills import run_skill, list_skills

result = await run_skill("find_resources", topic="微积分", difficulty="入门")
for s in list_skills():
    print(f"{s['name']}: {s['description']}")
```

技能定义文件：`backend/skills/技能名/SKILL.md`，用户自定义：`~/.atm/skills/`。

---

## 8. Tools — 工具注册与管理

**文件**：`tools/`（`decorator.py` / `registry.py` / `definition.py` / `tool_loader.py`）

```python
from app.shared.infra.tools import tool

@tool("my_tool", "工具描述（会展示给 LLM）")
async def my_tool(query: str, limit: int = 10) -> str:
    return f"处理 {query}，限制 {limit}"
```

| 内置工具 | 文件 | 功能 |
|----------|------|------|
| `web_search` | `builtin/web_search.py` | 搜索互联网 |
| `search_kb` | `builtin/search_kb.py` | 检索知识库 |
| `remember_info` | `builtin/memory_ops.py` | 记住用户信息 |
| `recall_info` | `builtin/memory_ops.py` | 回忆用户信息 |

---

## 9. Context — 教学上下文组装器

**文件**：`context.py`

```python
from app.shared.infra.context import build_teaching_context

ctx = await build_teaching_context(
    user_message="什么是特征值？",
    subject_id="linear-algebra",
    user_id="u1",
)
messages = ctx.to_messages()
```

自动组装：系统提示词 + 用户画像 + 知识片段 + 历史记忆 + 对话历史 + 用户消息。

---

## 10. Events — 教学事件日志

**文件**：`events.py`

```python
from app.shared.infra.events import emit_event, get_events, count_events, EventType

await emit_event(EventType.EXAM_COMPLETED,
                 user_id="u1", subject="math",
                 data={"score": 85, "total": 100})

events = await get_events(user_id="u1", event_type=EventType.MISTAKE_MADE, days=7)
```

| 事件类型 | 说明 | 产生方 |
|----------|------|--------|
| `question_asked` | 用户提问 | Interact |
| `answer_given` | 系统回答 | Interact |
| `concept_explained` | 概念讲解完成 | Interact |
| `concept_mastered` | 概念掌握确认 | Profile |
| `mistake_made` | 做错了题 | Examine |
| `exam_completed` | 完成考试 | Examine |
| `exam_graded` | 试卷批改完成 | Examine |
| `material_uploaded` | 上传了资料 | Ingest |
| `skill_practiced` | 练习了技能 | Lab |

---

## 11. Checker — 自动判卷与评分

**文件**：`checker.py`

```python
from app.shared.infra.checker import check_answer

# 自动策略（推荐）— 短答案→精确，中→关键词，长→LLM
result = await check_answer(
    question="解释什么是面向对象编程",
    student_answer="...",
    expected="...",
    strategy="auto",
)
print(result.score, result.feedback)
```

支持：精确匹配 / 关键词匹配 / LLM 语义判定 / Rubric 评分。

---

## 12. Teaching — 教学函数

**文件**：`teaching.py`

```python
from app.shared.infra.teaching import run_teaching_function, list_teaching_functions

explanation = await run_teaching_function("explain_concept", concept="贝叶斯定理")
quiz = await run_teaching_function("check_understanding", concept="特征值")
```

| 名称 | 分类 | 功能 |
|------|------|------|
| `explain_concept` | explain | 通俗解释学术概念 |
| `check_understanding` | quiz | 苏格拉底式追问检查理解 |
| `generate_practice` | quiz | 针对主题生成练习题 |
| `summarize_session` | summarize | 总结学习对话要点 |

---

## 13. MCP — 外部工具协议

**文件**：`mcp.py`

```python
from app.shared.infra.mcp import get_mcp_manager

mgr = get_mcp_manager()
await mgr.connect("filesystem", {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]})
tools = mgr.list_tools()
result = await mgr.call_tool("read_file", path="/data/notes.md")
```

MCP 工具自动注册到 ToolRegistry（名称前缀 `mcp_`），Agent Loop 可直接调用。

---

## 14. Security — 安全确认门

**文件**：`security.py`

```python
from app.shared.infra.security import check_action_safety, require_confirmation, SecurityLevel

decision = await check_action_safety("execute_code", {"command": "rm -rf /"})
if not decision.allowed:
    print(f"🚫 拦截：{decision.reason}")
```

| 工具 | 级别 | 策略 |
|------|------|------|
| `execute_code` | HIGH | 阻止危险命令，需确认 |
| `write_file` | HIGH | 需确认 |
| `web_search` | LOW | 无限制 |
| `search_kb` | LOW | 无限制 |
| `remember_info` | MEDIUM | 无限制 |

---

## 15. Sandbox — 实验环境

**文件**：`sandbox.py`

```python
from app.shared.infra.sandbox import create_sandbox, SandboxType

sb = await create_sandbox(SandboxType.SIMULATED_TERMINAL)
r = await sb.execute("git init")
print(r.output)  # "Initialized empty Git repository..."

# 练习模式
from app.shared.infra.sandbox import create_exercise_sandbox
sb = await create_exercise_sandbox("git_init")
r = await sb.execute("git init")       # ✓ Step 1
grade = sb.grade()
print(grade.score, grade.feedback)
```

| 模式 | 类型 | 适用场景 |
|------|------|----------|
| 模拟终端 | `SIMULATED_TERMINAL` | 考试、在线教学 |
| 本地终端 | `TERMINAL` | 开发调试 |
| 代码执行 | `CODE` | 编程练习 |
| 🔜 SQL 沙箱 | `DATABASE` | 数据库学习 |
| 🔜 浏览器沙箱 | `BROWSER` | 前端训练 |

---

## 16. 其他基础模块

| 文件 | 功能 | 使用方式 |
|------|------|----------|
| `prompt_loader.py` | Jinja2 Prompt 模板 | `from app.shared.infra.prompt_loader import populate_prompt` |
| `tracing.py` | 调用追踪 | `from app.shared.infra.tracing import trace_llm_call` |
| `reasoning.py` | 推理策略 | `from app.shared.infra.reasoning import chain_of_thought` |
| `token_budget.py` | Token 预算 | `from app.shared.infra.token_budget import ContextWindowManager` |
| `cache.py` | LLM 缓存 | `from app.shared.infra.cache import cached_completion` |
| `retrievers.py` | 检索管线 | `from app.shared.infra.retrievers import RetrievalPipeline` |
| `reranker.py` | Rerank | `from app.shared.infra.reranker import rerank_chunks` |
| `strategies.py` | 策略编排 | `from app.shared.infra.strategies import StrategyMode` |

---

## 17. 与 /workflows 的关系

```
/workflows                           /infra 提供的能力
──────────────────────────────        ──────────────────────────
ingest/   资料接入                    ← llm + embedding + events
digest/   知识整理                    ← llm + embedding + events
interact/ 教学对话                    ← context + agent_loop + memory + search + teaching
examine/  考试测验                    ← checker + events + memory + teaching
profile/  用户画像                    ← memory/profile + events + checker
```

### 典型数据流

```
用户提问
  ↓
[context.py]        组装教学上下文
  ↓                   ├── profile → 加载用户画像
  │                   ├── search  → 检索知识片段
  │                   └── memory  → 回忆历史记忆
  ↓
[agent_loop.py]     LLM 推理 + 工具调用
  ↓                   ├── tools   → web_search / search_kb
  │                   └── teaching → explain / quiz
  ↓
[events.py]         记录事件
  ↓                   └── question_asked → Profile 消费
  ↓
[memory]            更新记忆
  ↓                   └── remember → 积累用户认知
  ↓
返回答案
```
