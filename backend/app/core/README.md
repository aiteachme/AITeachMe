# Core — AI 基础设施层

> 五大引擎（Ingest / Digest / Interact / Examine / Profile）的公共底座。
> 所有新能力仅限此目录，上层代码零侵入。

---

## 目录

- [目录](#目录)
- [1. 定位与设计原则](#1-定位与设计原则)
  - [设计原则](#设计原则)
- [2. 目录结构](#2-目录结构)
- [3. LLM 调用层](#3-llm-调用层)
  - [核心函数](#核心函数)
- [4. Agent Loop — 工具增强推理](#4-agent-loop--工具增强推理)
  - [使用方式](#使用方式)
  - [参数说明](#参数说明)
- [5. Memory — 记忆与用户画像](#5-memory--记忆与用户画像)
  - [使用方式](#使用方式-1)
  - [MemoryTag 标签](#memorytag-标签)
  - [LEARNER.md — 学习者档案（OpenClaw 风格）](#learnermd--学习者档案openclaw-风格)
- [6. Search — Web 搜索与知识库检索](#6-search--web-搜索与知识库检索)
  - [使用方式](#使用方式-2)
  - [搜索提供商](#搜索提供商)
- [7. Skills — 教学技能框架（OpenClaw 规范）](#7-skills--教学技能框架openclaw-规范)
  - [使用方式](#使用方式-3)
  - [SKILL.md 规范（OpenClaw 格式）](#skillmd-规范openclaw-格式)
  - [扫描路径](#扫描路径)
  - [自定义 Python 技能](#自定义-python-技能)
- [8. Tools — 工具注册与管理](#8-tools--工具注册与管理)
  - [@tool 装饰器（推荐方式）](#tool-装饰器推荐方式)
  - [已注册的内置工具](#已注册的内置工具)
  - [工具在 Agent Loop 中的使用](#工具在-agent-loop-中的使用)
- [9. Context — 教学上下文组装器](#9-context--教学上下文组装器)
  - [使用方式](#使用方式-4)
  - [自动组装的维度](#自动组装的维度)
- [10. Events — 教学事件日志](#10-events--教学事件日志)
  - [使用方式](#使用方式-5)
  - [预定义事件类型](#预定义事件类型)
- [11. Checker — 自动判卷与评分](#11-checker--自动判卷与评分)
  - [使用方式](#使用方式-6)
  - [Rubric JSON 格式](#rubric-json-格式)
- [12. Teaching — 教学函数](#12-teaching--教学函数)
  - [使用方式](#使用方式-7)
  - [内置教学函数](#内置教学函数)
  - [@teaching\_function vs @tool](#teaching_function-vs-tool)
- [13. MCP — 外部工具协议](#13-mcp--外部工具协议)
  - [使用方式](#使用方式-8)
  - [依赖](#依赖)
- [14. Security — 安全确认门](#14-security--安全确认门)
  - [使用方式](#使用方式-9)
  - [内置规则](#内置规则)
- [15. Sandbox — 实验环境](#15-sandbox--实验环境)
  - [使用方式](#使用方式-10)
  - [沙箱类型](#沙箱类型)
- [16. 其他基础模块](#16-其他基础模块)
- [17. 与 /workflows 的关系](#17-与-workflows-的关系)
  - [典型数据流](#典型数据流)

---

## 1. 定位与设计原则

`/core` 是纯基础设施层，**不包含任何业务逻辑**。

### 设计原则

| 原则 | 说明 |
|------|------|
| **一行 import，一次调用** | 外部模块使用 core 只需 `from app.core.xxx import func` + `await func(...)` |
| **中文优先** | 提示词、标签、错误信息默认中文 |
| **零配置即可用** | 不装额外包也不报错，只是功能降级（如 DuckDuckGo 搜索） |
| **可扩展** | 新增工具/技能/搜索提供商只需加文件，不改已有代码 |
| **对外极简 API** | 所有模块对外只暴露 2~5 个顶层函数 |

---

## 2. 目录结构

```
core/
│  基础设施
├── config.py              配置中心
├── database.py            SQLite 数据库（sqlite-vec 支持）
├── exceptions.py          异常定义
├── logger.py              structlog 结构化日志
├── prompt_loader.py       Jinja2 Prompt 模板引擎
│
│  LLM 调用
├── llm.py                 LLM 补全入口（文本/结构化/流式/工具调用）
├── embedding.py           向量化（分批 + 限流）
├── model_router.py        按任务类型选模型
│
│  Agent Loop
├── agent_loop.py          🔥 ReAct 工具增强推理循环
│
│  教学上下文
├── context.py             🔥 教学上下文自动组装
│
│  教学事件
├── events.py              🔥 结构化事件日志（五大引擎回流基础）
│
│  自动判卷
├── checker.py             🔥 Rubric 评分 + 多策略判定
│
│  教学函数
├── teaching.py            🔥 教学策略级操作（解释/追问/出题/总结）
│
│  MCP 协议
├── mcp.py                 🔥 Model Context Protocol 客户端
│
│  安全控制
├── security.py            🔥 工具调用安全确认门
│
│  沙箱环境
├── sandbox.py             🔥 Lab Mode 实验沙箱抽象
│
│  记忆系统
├── memory/
│   ├── __init__.py        对外 API
│   ├── api.py             remember / recall / get_user_profile / ...
│   ├── types.py           MemoryTag / MemoryEntry / LearningLogEntry
│   ├── store.py           SQLite 持久化
│   ├── profile.py         UserProfile（to_system_message / to_summary）
│   └── learner_doc.py     🔥 LEARNER.md 学习者档案读写
│
│  搜索管线
├── search/
│   ├── __init__.py        对外 API
│   ├── api.py             web_search / search_knowledge
│   ├── types.py           WebSearchResult
│   └── web.py             DuckDuckGo 搜索提供商
│
│  技能框架
├── skills/
│   ├── __init__.py        对外 API
│   ├── api.py             run_skill / list_skills
│   ├── base.py            @skill 装饰器 + SkillRegistry
│   └── loader.py          SKILL.md 多路径加载器
│
│  工具注册
├── tools/
│   ├── definition.py      ToolDefinition
│   ├── registry.py        ToolRegistry
│   ├── decorator.py       @tool 装饰器
│   ├── tool_loader.py     YAML 配置加载器
│   └── builtin/
│       ├── web_search.py  Web 搜索
│       ├── search_kb.py   知识库检索
│       └── memory_ops.py  记忆读写
│
│  其他
├── tracing.py             调用追踪
├── reasoning.py           推理策略（CoT / 反思）
├── token_budget.py        Token 预算 + 上下文截断
├── cache.py               LLM 响应缓存
├── retrievers.py          检索管线
├── reranker.py            Rerank 重排序
├── strategies.py          策略编排
│
├── guardrails/            安全护栏
│   ├── base.py
│   ├── builtin.py
│   └── pipeline.py
│
└── .docs/                 设计文档
```

**项目级目录**（不在 core/ 内）：

```
backend/
├── skills/                SKILL.md 教学技能定义（OpenClaw 规范）
│   ├── find_resources/SKILL.md
│   ├── explain_with_analogy/SKILL.md
│   └── review_mistakes/SKILL.md
│
├── tools/                 工具配置 YAML（可选，覆盖描述/启禁用）
│   ├── web_search.yaml
│   ├── search_kb.yaml
│   ├── remember_info.yaml
│   └── recall_info.yaml
│
~/.atm/skills/             用户自定义技能
~/.atm/tools/              用户自定义工具配置
```

---

## 3. LLM 调用层

**文件**：`llm.py`、`embedding.py`、`model_router.py`

### 核心函数

```python
from app.core.llm import acompletion, acompletion_stream, acompletion_with_tools
from app.core.embedding import aembed_texts

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

### 使用方式

```python
from app.core.agent_loop import run_agent_loop, run_agent_loop_stream

# 批量模式 — 返回完整结果
result = await run_agent_loop(
    messages=[{"role": "user", "content": "帮我搜索贝叶斯定理的教程"}],
    tools=["web_search", "search_kb"],   # 只传工具名
    max_iterations=5,
)
print(result.final_answer)        # LLM 最终回答
print(result.tool_calls_made)     # 调用了哪些工具
print(result.iterations)          # 循环了几轮

# 流式模式 — 适合 SSE / 聊天界面
async for chunk in run_agent_loop_stream(
    messages=[{"role": "user", "content": "什么是特征值？"}],
    tools=["search_kb"],
):
    yield chunk   # 直接推给前端
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `messages` | `list[dict]` | 必填 | 对话历史 |
| `tools` | `list[str]` | `[]` | 可用工具名（从 ToolRegistry 查找） |
| `max_iterations` | `int` | `5` | 最大循环轮数 |
| `system_prompt` | `str` | `""` | 覆盖系统提示词 |

---

## 5. Memory — 记忆与用户画像

**文件**：`memory/`（`api.py` / `store.py` / `profile.py` / `types.py`）

跨会话记住用户信息，自动构建个性化教学画像。SQLite 持久化，首次使用自动建表。

### 使用方式

```python
from app.core.memory import remember, recall, forget, get_user_profile

# ── 记忆 ──
key = await remember(
    "用户线性代数较弱，特征值概念不清楚",
    user_id="u1",
    tag="weakness",      # preference | strength | weakness | background | note
    importance=0.8,      # 0.0 ~ 1.0，越高越容易被回忆
)

# ── 回忆 ──
entries = await recall("线性代数", user_id="u1", top_k=5)
for e in entries:
    print(f"[{e.tag}] {e.content}")
# [weakness] 用户线性代数较弱，特征值概念不清楚

# ── 忘记 ──
await forget(key)

# ── 用户画像 ──
profile = await get_user_profile("u1")
print(profile.to_summary())
# "大三计算机专业，学习风格偏好类比解释，擅长Python基础，薄弱点线性代数"

# 直接注入 LLM 上下文
system_msg = profile.to_system_message()
messages = [system_msg] + other_messages
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

### LEARNER.md — 学习者档案（OpenClaw 风格）

**文件**：`memory/learner_doc.py`

参考 OpenClaw 的 `USER.md` / `SOUL.md` 思路，为每位学习者维护一份**人类可读可编辑**的 Markdown 档案。
系统在学习过程中自动更新，用户也可以手动编辑。

**文件位置**：

| 场景 | 路径 |
|------|------|
| 单用户（默认） | `~/.atm/LEARNER.md` |
| 多用户 | `~/.atm/users/{user_id}/LEARNER.md` |

**默认模板章节**：

```markdown
# 📚 学习者档案
## 基本信息
## 学习风格偏好
## 擅长领域
## 薄弱领域
## 学习笔记
## 最近学习主题
## 教学备注
```

**使用方式**：

```python
from app.core.memory import (
    read_learner_doc,
    write_learner_doc,
    update_learner_section,
    read_learner_section,
    append_to_learner_section,
    sync_profile_to_doc,
    load_doc_to_context,
    get_learner_doc_path,
)

# ── 读取完整档案 ──
doc = await read_learner_doc("u1")        # 不存在则自动创建默认模板
print(doc)

# ── 更新某个章节 ──
await update_learner_section("u1", "薄弱领域",
    "- 线性代数：特征值计算\n- 概率论：贝叶斯公式")

# ── 读取某个章节 ──
weaknesses = await read_learner_section("u1", "薄弱领域")

# ── 追加一行到章节 ──
await append_to_learner_section("u1", "学习笔记",
    "- 特征值 = 矩阵拉伸的倍数（2026-03-27）")

# ── 从 UserProfile 同步到文件 ──
await sync_profile_to_doc("u1")      # profile 各维度自动写入对应章节

# ── 加载为 LLM 上下文 ──
learner_ctx = await load_doc_to_context("u1")
messages = [{"role": "system", "content": learner_ctx}] + messages

# ── 获取文件路径 ──
path = get_learner_doc_path("u1")     # ~/.atm/users/u1/LEARNER.md
```

**API 表**：

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `read_learner_doc(user_id)` | 读取完整档案 | `str` (Markdown) |
| `write_learner_doc(user_id, content)` | 写入完整档案 | `None` |
| `update_learner_section(user_id, section, content)` | 替换某章节 | `None` |
| `read_learner_section(user_id, section)` | 读取某章节 | `str` |
| `append_to_learner_section(user_id, section, line)` | 追加一行（自动去重） | `None` |
| `sync_profile_to_doc(user_id)` | UserProfile → 文件 | `None` |
| `load_doc_to_context(user_id)` | 文件 → LLM 上下文 | `str` |
| `get_learner_doc_path(user_id)` | 获取文件路径 | `Path` |

---

## 6. Search — Web 搜索与知识库检索

**文件**：`search/`（`api.py` / `web.py` / `types.py`）

### 使用方式

```python
from app.core.search import web_search, search_knowledge

# ── Web 搜索 ──
results = await web_search("贝叶斯定理 直觉解释", top_k=5)
for r in results:
    print(f"{r.title}: {r.url}")
    print(r.snippet)

# ── 知识库检索 ──
chunks = await search_knowledge(
    "什么是特征值",
    subject_id="linear-algebra",
    top_k=5,
    enable_rerank=True,    # 需配置 rerank 模型
)
for c in chunks:
    print(f"[{c.title}] {c.content[:100]}")
```

### 搜索提供商

| 提供商 | 状态 | 配置 |
|--------|------|------|
| DuckDuckGo | ✅ 默认可用 | `pip install duckduckgo-search` |
| Serper | 🔜 计划 | `SERPER_API_KEY` |
| Tavily | 🔜 计划 | `TAVILY_API_KEY` |

---

## 7. Skills — 教学技能框架（OpenClaw 规范）

**文件**：`skills/`（`api.py` / `base.py` / `loader.py`）

### 使用方式

```python
from app.core.skills import run_skill, list_skills

# 执行技能
result = await run_skill("find_resources", topic="微积分", difficulty="入门")

# 列出所有技能
for s in list_skills():
    print(f"{s['name']}: {s['description']}")
```

### SKILL.md 规范（OpenClaw 格式）

技能定义文件放在 `backend/skills/技能名/SKILL.md`，格式：

```markdown
---
name: find_resources
description: 根据学习主题搜索免费学习资料
version: "1.0"
tags:
  - 教学
  - 检索
parameters:
  topic:
    type: string
    description: 学习主题
    required: true
---

# 搜索学习资料

执行步骤：
1. 构建搜索查询
2. 搜索互联网
3. 整理推荐列表
```

### 扫描路径

| 路径 | 用途 | 优先级 |
|------|------|--------|
| `backend/skills/` | 项目内置技能 | 先加载 |
| `~/.atm/skills/` | 用户自定义技能 | 后加载（同名覆盖） |

### 自定义 Python 技能

```python
from app.core.skills import skill

@skill("my_skill", "我的自定义技能", tags=["自定义"])
async def my_skill(topic: str) -> str:
    return f"处理主题：{topic}"
```

---

## 8. Tools — 工具注册与管理

**文件**：`tools/`（`decorator.py` / `registry.py` / `definition.py` / `tool_loader.py`）

### @tool 装饰器（推荐方式）

```python
from app.core.tools import tool

@tool("my_tool", "工具描述（会展示给 LLM）")
async def my_tool(query: str, limit: int = 10) -> str:
    """工具实现。参数自动提取为 JSON Schema。"""
    return f"处理 {query}，限制 {limit}"
```

### 已注册的内置工具

| 工具名 | 文件 | 功能 |
|--------|------|------|
| `web_search` | `builtin/web_search.py` | 搜索互联网 |
| `search_kb` | `builtin/search_kb.py` | 检索知识库 |
| `remember_info` | `builtin/memory_ops.py` | 记住用户信息 |
| `recall_info` | `builtin/memory_ops.py` | 回忆用户信息 |

### 工具在 Agent Loop 中的使用

```python
# Agent Loop 自动发现并调用已注册工具
result = await run_agent_loop(
    messages=messages,
    tools=["web_search", "search_kb", "remember_info"],
)
```

---

## 9. Context — 教学上下文组装器

**文件**：`context.py`

**解决什么问题**：Interact 引擎需要把知识片段、用户画像、历史记忆、教学提示词等多个维度组装成 LLM 消息列表。手动拼装容易遗漏，Context Assembler 自动完成一切。

### 使用方式

```python
from app.core.context import build_teaching_context

ctx = await build_teaching_context(
    user_message="什么是特征值？",
    subject_id="linear-algebra",
    user_id="u1",
    tool_names=["search_kb"],           # 可选：指定可用工具
    chat_history=[...],                  # 可选：对话历史
)

# 获取组装好的 messages
messages = ctx.to_messages()
# → [system_prompt, profile, knowledge_snippets, memory, ..., user_message]

# 直接传给 LLM 或 Agent Loop
answer = await acompletion(messages)
```

### 自动组装的维度

| 维度 | 来源 | 控制参数 |
|------|------|----------|
| 系统提示词 | 内置教学提示词 / 自定义 | `system_prompt` |
| 用户画像 | `memory/profile` | `include_profile=True` |
| 知识片段 | `search/search_knowledge()` | `include_knowledge=True` |
| 历史记忆 | `memory/recall()` | `include_memory=True` |
| 对话历史 | 外部传入 | `chat_history` |
| 用户消息 | 直接传入 | `user_message` |

---

## 10. Events — 教学事件日志

**文件**：`events.py`

**解决什么问题**：五大引擎的闭环回流需要结构化事件。Interact 记录"用户提了什么问题"，Examine 记录"考了多少分"，Profile 消费这些事件来更新掌握度。

### 使用方式

```python
from app.core.events import emit_event, get_events, count_events, EventType

# ── 发射事件 ──

# Interact 引擎中
await emit_event(EventType.QUESTION_ASKED,
                 user_id="u1", subject="math",
                 data={"topic": "特征值", "answer_quality": "partial"})

# Examine 引擎中
await emit_event(EventType.EXAM_COMPLETED,
                 user_id="u1", subject="math",
                 data={"score": 85, "total": 100, "weak_points": ["贝叶斯"]})

# 错题记录
await emit_event(EventType.MISTAKE_MADE,
                 user_id="u1", subject="math",
                 data={"question": "P(A|B)=?", "wrong_answer": "0.5"})

# ── 查询事件 ──

events = await get_events(user_id="u1", event_type=EventType.MISTAKE_MADE, days=7)
for e in events:
    print(f"{e.created_at}: {e.data}")

# 统计
count = await count_events(user_id="u1", event_type=EventType.EXAM_COMPLETED, days=30)
```

### 预定义事件类型

| 事件类型 | 说明 | 产生方 |
|----------|------|--------|
| `question_asked` | 用户提问 | Interact |
| `answer_given` | 系统回答 | Interact |
| `concept_explained` | 概念讲解完成 | Interact |
| `concept_mastered` | 概念掌握确认 | Profile |
| `mistake_made` | 做错了题 | Examine |
| `exam_completed` | 完成考试 | Examine |
| `exam_graded` | 试卷批改完成 | Examine |
| `review_started` | 开始复习 | Profile |
| `review_completed` | 复习完成 | Profile |
| `material_uploaded` | 上传了资料 | Ingest |
| `skill_practiced` | 练习了技能 | Lab |
| `session_started` | 学习会话开始 | Interact |
| `session_ended` | 学习会话结束 | Interact |

---

## 11. Checker — 自动判卷与评分

**文件**：`checker.py`

**解决什么问题**：Examine 引擎需要自动判定学生答案的正确性。支持精确匹配、关键词匹配和 LLM 语义判定三种策略。

### 使用方式

```python
from app.core.checker import check_answer, load_rubric, Rubric

# ── 精确匹配 ──
result = await check_answer(
    student_answer="42",
    expected="42",
    strategy="exact",
)
print(result.passed)     # True
print(result.score)      # 10.0

# ── 关键词匹配 ──
result = await check_answer(
    student_answer="HTTP 200 表示请求成功，服务器正常返回",
    expected="请求成功,OK,正常响应",
    strategy="keywords",
)
print(result.passed)     # True
print(result.feedback)   # "基本正确，命中关键词 2/3"

# ── LLM 语义判定 ──
result = await check_answer(
    question="解释什么是面向对象编程",
    student_answer="面向对象是一种编程范式，用类和对象来组织代码...",
    expected="面向对象编程使用类、对象、继承、封装、多态等概念...",
    strategy="llm",
)
print(result.score)           # 8.5
print(result.feedback)        # "回答较完整，但缺少对多态的说明"
print(result.criteria_scores) # {"概念覆盖": 4, "表述清晰": 4.5}

# ── 自动策略（推荐） ──
result = await check_answer(
    question="...",
    student_answer="...",
    expected="...",
    strategy="auto",   # 短答案→精确，中→关键词，长→LLM
)

# ── 使用 Rubric ──
rubric = load_rubric("math/eigenvalue")   # 从 backend/rubrics/ 加载
result = await check_answer(..., rubric=rubric)
```

### Rubric JSON 格式

放在 `backend/rubrics/` 目录下：

```json
{
  "full_marks": 10,
  "pass_threshold": 0.6,
  "criteria": [
    {"name": "找到所有特征值", "weight": 0.6, "description": "需找出全部特征值"},
    {"name": "计算过程正确", "weight": 0.4}
  ],
  "common_mistakes": [
    {"pattern": "只找到一个", "feedback": "注意：n阶矩阵有n个特征值", "deduction": 3}
  ]
}
```

---

## 12. Teaching — 教学函数

**文件**：`teaching.py`

**解决什么问题**：教学策略级操作（解释概念、苏格拉底追问、出练习题、总结要点），比 `@tool` 更高层级。参考 OpenMAIC 的 `Agenda → Function → Action`。

### 使用方式

```python
from app.core.teaching import (
    teaching_function,
    run_teaching_function,
    list_teaching_functions,
)

# ── 执行内置教学函数 ──
explanation = await run_teaching_function("explain_concept", concept="贝叶斯定理")
quiz = await run_teaching_function("check_understanding", concept="特征值")
practice = await run_teaching_function("generate_practice", topic="概率论", count=3)
summary = await run_teaching_function("summarize_session", conversation="...")

# ── 列出可用教学函数 ──
funcs = list_teaching_functions(category="quiz")
for f in funcs:
    print(f"{f['name']}: {f['description']}")

# ── 自定义教学函数 ──
@teaching_function("guide_step_by_step", "分步引导学生解决问题",
                    category="guide")
async def guide(problem: str, hints: int = 3) -> str:
    from app.core.llm import acompletion
    return await acompletion(messages=[
        {"role": "system", "content": f"请分{hints}步引导学生自己解决以下问题"},
        {"role": "user", "content": problem},
    ])
```

### 内置教学函数

| 名称 | 分类 | 功能 |
|------|------|------|
| `explain_concept` | explain | 通俗解释学术概念 |
| `check_understanding` | quiz | 苏格拉底式追问检查理解 |
| `generate_practice` | quiz | 针对主题生成练习题 |
| `summarize_session` | summarize | 总结学习对话要点 |

### @teaching_function vs @tool

| 维度 | `@tool` | `@teaching_function` |
|------|---------|---------------------|
| 层级 | 原子操作 | 教学策略 |
| 例子 | 搜索、计算、读写 | 解释、追问、出题、总结 |
| 被谁调用 | Agent Loop（LLM 自动选择） | Interact 引擎（根据教学计划调度） |
| 注册去向 | ToolRegistry | 独立的 teaching 函数表 |

---

## 13. MCP — 外部工具协议

**文件**：`mcp.py`

**解决什么问题**：标准化接入外部数据源和工具（Notion / 文件系统 / 数据库等），遵循 Anthropic 的 Model Context Protocol 标准。

### 使用方式

```python
from app.core.mcp import get_mcp_manager

mgr = get_mcp_manager()

# ── 连接 MCP 服务器 ──
await mgr.connect("filesystem", {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
})

# ── 列出工具 ──
tools = mgr.list_tools()
for t in tools:
    print(f"{t.name}: {t.description}")

# ── 调用工具 ──
result = await mgr.call_tool("read_file", path="/data/notes.md")

# ── 列出服务器 ──
servers = mgr.list_servers()

# ── 断开 ──
await mgr.disconnect("filesystem")
```

### 依赖

```bash
pip install mcp    # 可选，不装也不报错
```

MCP 工具自动注册到 ToolRegistry（名称前缀 `mcp_`），Agent Loop 可直接调用。

---

## 14. Security — 安全确认门

**文件**：`security.py`

**解决什么问题**：Agent Loop 调用高风险工具时需要安全控制（拦截危险命令、限制调用频率、要求确认）。

### 使用方式

```python
from app.core.security import (
    check_action_safety,
    require_confirmation,
    register_security_rule,
    SecurityLevel,
    SecurityRule,
)

# ── 方式 1：手动检查 ──
decision = await check_action_safety("execute_code", {"command": "rm -rf /"})
if not decision.allowed:
    print(f"🚫 拦截：{decision.reason}")
    # "🚫 拦截：参数包含被禁止的模式: rm -rf"

# ── 方式 2：装饰器 ──
from app.core.tools import tool

@tool("execute_code", "执行用户代码")
@require_confirmation(level=SecurityLevel.HIGH)
async def execute_code(code: str) -> str:
    ...   # 调用时自动检查安全

# ── 自定义规则 ──
register_security_rule(SecurityRule(
    tool_name="delete_data",
    level=SecurityLevel.CRITICAL,
    max_calls_per_session=1,
    requires_confirmation=True,
))
```

### 内置规则

| 工具 | 级别 | 策略 |
|------|------|------|
| `execute_code` | HIGH | 阻止 `rm -rf`、`os.system` 等，需确认 |
| `write_file` | HIGH | 需确认 |
| `web_search` | LOW | 无限制 |
| `search_kb` | LOW | 无限制 |
| `remember_info` | MEDIUM | 无限制 |

---

## 15. Sandbox — 实验环境与 CLI 学习

**文件**：`sandbox.py`

**解决什么问题**：让学生在考试和学习中通过模拟终端练习 git / docker / linux 等 CLI 命令，
无需真实环境即可交互式学习和考核。同时支持 Python 代码执行练习。

### 15.1 三种沙箱模式

| 模式 | 类型常量 | 说明 | 适用场景 |
|------|---------|------|---------|
| **模拟终端** | `SIMULATED_TERMINAL` | 不真实执行，返回逼真模拟输出 | 考试、在线教学、安全练习 |
| **本地终端** | `TERMINAL` | 真实执行命令 | 开发调试 |
| **代码执行** | `CODE` | 执行 Python 代码 | 编程练习 |
| 🔜 SQL 沙箱 | `DATABASE` | 执行 SQL 查询 | 数据库学习 |
| 🔜 浏览器沙箱 | `BROWSER` | 网页操作自动化 | 前端/产品操作训练 |

### 15.2 模拟终端（考试/教学首选）

内置 200+ 常见命令的模拟响应（git / linux / docker / 网络 / 包管理），**跨平台、零风险**。

```python
from app.core.sandbox import create_sandbox, SandboxType

sb = await create_sandbox(SandboxType.SIMULATED_TERMINAL)

r = await sb.execute("git init")
print(r.output)   # "Initialized empty Git repository in /home/student/workspace/.git/"

r = await sb.execute("ls -la")
print(r.output)   # 逼真的文件列表输出

r = await sb.execute("docker ps")
print(r.output)   # 模拟的容器列表

# 命令历史（可注入 LLM 上下文做分析）
print(sb.get_history_text())
# 1. [✓] $ git init
# 2. [✓] $ ls -la
# 3. [✓] $ docker ps

await sb.destroy()
```

**模拟终端的智能特性**：

- Git 状态追踪（`git init` 后 `git status` 会反映已初始化状态）
- 虚拟文件系统（`touch` 创建的文件可以被 `cat` 读取）
- `cd` 正确更新工作目录
- `echo` 返回正确内容
- 未知命令返回 `bash: xxx: command not found`

### 15.3 练习模式（Exercise Sandbox）

将练习题与模拟终端结合，学生按步骤操作，**自动判定每一步是否正确**。

```python
from app.core.sandbox import create_exercise_sandbox

# 使用内置练习
sb = await create_exercise_sandbox("git_init")

# 查看当前步骤提示
print(sb.current_instruction)
# "[步骤 1/5] 初始化一个新的 Git 仓库"

# 学生操作
r1 = await sb.execute("git init")       # ✓ Step 1
print(sb.current_instruction)
# "[步骤 2/5] 查看当前仓库状态"

r2 = await sb.execute("git status")     # ✓ Step 2
r3 = await sb.execute("git add .")      # ✓ Step 3
r4 = await sb.execute('git commit -m "Initial commit"')  # ✓ Step 4
r5 = await sb.execute("git log")        # ✓ Step 5

# 查看进度
print(sb.progress)
# {"current_step": 6, "total_steps": 5, "completed": True, "correct_count": 5}

# 评分
grade = sb.grade()
print(grade.passed)     # True
print(grade.score)      # 5.0
print(grade.feedback)   # "🎉 完美完成！全部 5 步正确。"

# 命令历史（可回流到 Profile / Events）
for cmd in grade.command_history:
    print(f"{'✓' if cmd.is_correct else '✗'} {cmd.command}")
```

### 15.4 内置练习题

| 名称 | 类别 | 难度 | 步骤数 | 学什么 |
|------|------|------|--------|--------|
| `git_init` | git | 入门 | 5 | 初始化仓库、暂存、提交、查看日志 |
| `git_branch` | git | 基础 | 3 | 查看分支、创建切换分支 |
| `linux_basics` | linux | 入门 | 4 | pwd、ls、mkdir、touch |
| `docker_basics` | docker | 入门 | 3 | 查看容器、镜像、运行容器 |

```python
from app.core.sandbox import get_builtin_exercises, get_exercise

# 列出所有内置练习
for name, ex in get_builtin_exercises().items():
    print(f"{name}: {ex.title} ({ex.category}, {ex.difficulty})")

# 获取单个练习
ex = get_exercise("git_init")
print(ex.description)
```

### 15.5 自定义练习题

```python
from app.core.sandbox import Exercise, ExerciseStep, create_exercise_sandbox

exercise = Exercise(
    title="Linux 权限管理",
    description="学习 chmod 和文件权限概念",
    category="linux",
    difficulty="进阶",
    steps=[
        ExerciseStep(
            instruction="查看 script.py 的详细权限",
            expected_commands=["ls -la script.py", "ls -l script.py"],
            hints=["ls -l 可以看到文件权限"],
        ),
        ExerciseStep(
            instruction="给 script.py 添加可执行权限",
            expected_commands=["chmod +x script.py", "chmod 755 script.py"],
            hints=["chmod +x 给文件添加执行权限"],
            points=2.0,
        ),
    ],
)

sb = await create_exercise_sandbox(exercise)
```

### 15.6 与 Examine 引擎集成

```python
# 在考试中使用沙箱作为答题环境
from app.core.sandbox import create_exercise_sandbox
from app.core.events import emit_event, EventType

# 创建练习
sb = await create_exercise_sandbox("git_init")

# ... 学生操作 ...

# 评分并记录事件
grade = sb.grade()
await emit_event(EventType.SKILL_PRACTICED,
                 user_id="u1", subject="git",
                 data={"exercise": "git_init",
                       "score": grade.score,
                       "total": grade.total,
                       "passed": grade.passed})
```

### 15.7 未来扩展方向

| 方向 | 说明 | 价值 |
|------|------|------|
| **SQL 沙箱** | 内置 SQLite 数据库，学生写 SQL 查询练习 | 数据分析、后端开发课程 |
| **浏览器沙箱** | 模拟网页操作（表单填写、导航、信息查找） | 前端开发、产品流程培训 |
| **Python 评判** | 运行学生代码 + 验证输出/断言 | 编程课、算法题 |
| **场景模拟** | 模拟运维排障（日志分析 → 定位 → 修复） | DevOps 培训 |
| **命令链任务** | 多命令组合完成目标（管道、重定向） | Linux 进阶 |
| **Docker Compose 沙箱** | 模拟多容器编排操作 | 容器化部署学习 |
| **Git 协作模拟** | 模拟多人分支合并冲突解决 | 团队协作培训 |
| **网络诊断** | 模拟 ping/traceroute/curl 排查网络问题 | 网络基础课程 |

> 🔑 **核心思路**：模拟终端让"实操练习"不再依赖真实环境，考试中可以安全使用，
> 而且命令历史可以完整回流到 Profile，形成"练→判→记→复"闭环。

---

## 16. 其他基础模块

| 文件 | 功能 | 使用方式 |
|------|------|----------|
| `config.py` | 配置中心 | `from app.core.config import get_settings` |
| `database.py` | SQLite + sqlite-vec | `from app.core.database import get_engine, get_session` |
| `exceptions.py` | 自定义异常 | `from app.core.exceptions import LLMCallError` |
| `logger.py` | structlog 日志 | `import structlog; logger = structlog.get_logger()` |
| `prompt_loader.py` | Jinja2 Prompt 模板 | `from app.core.prompt_loader import render_prompt` |
| `tracing.py` | 调用追踪 | `from app.core.tracing import trace_llm_call` |
| `reasoning.py` | 推理策略 | `from app.core.reasoning import chain_of_thought` |
| `token_budget.py` | Token 预算 | `from app.core.token_budget import fit_messages` |
| `cache.py` | LLM 缓存 | `from app.core.cache import cached_completion` |
| `retrievers.py` | 检索管线 | `from app.core.retrievers import retrieve_chunks` |
| `reranker.py` | Rerank | `from app.core.reranker import rerank_chunks` |

---

## 17. 与 /workflows 的关系

```
/workflows                           /core 提供的能力
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
