## 二、三级模型策略（通过 TaskType 实现 LLMTier 概念）

> **最后更新**：2026-04-08 — `acompletion_with_fallback()` 已在 `llm_support/fallback.py` 落地，实际实现比原设计更丰富（支持 `tier` 参数 + `extra_metadata` 注入）

### 2.1 设计原则：复用 TaskType 而非新增 tier 参数

当前 `model_router.py` 已有 11 个 `TaskType`，每个 TaskType 有独立的 temperature / timeout / max_retries。
`llm_support/` 包已经围绕 `TaskType → TaskProfile → CompletionContext` 构建了完整的调用链。

**我们的做法**：不新增 `LLMTier` enum 或 `tier` 参数，而是将 gpt-researcher 的三级概念
**映射到已有的 TaskType**，通过 `model_overrides` 配置实现差异化模型路由。

> [!IMPORTANT]
> **LLMTier 是概念，TaskType 是实现。**
> 
> | gpt-researcher 概念 | 我们的实现 | 含义 |
> |:---|:---|:---|
> | Strategic（规划脑） | `TaskType.REASONING` | 复杂推理、大纲架构、子查询生成 |
> | Smart（写作脑） | `TaskType.DOCGEN` | 高质量长文本生成、章节写作 |
> | Fast（苦力脑） | `TaskType.DOCGEN_LIGHT` | 摘要提取、元数据生成、上下文压缩 |

### 2.2 模型映射表

| 概念层级 | TaskType | Qwen 映射 | 调用场景举例 |
|:---|:---|:---|:---|
| **Strategic** | `REASONING` | `qwq-32b` 或 `qwen-max` | `edu_planner` 教学大纲规划 |
| **Smart** | `DOCGEN` | `qwen-max` 或 `qwen-plus`（默认） | `pedagogy_craft` 章节写作 |
| **Fast** | `DOCGEN_LIGHT` | `qwen-turbo` 或 `qwen-plus` | `targeted_research` 素材压缩、`enrich` 占位符解析 |

### 2.3 配置方式

通过现有的 `model_overrides` 字典实现，**不新增 config 字段**：

```env
# .env 示例 — 为 DocGen 流程配置差异化模型
# 不配则全部走 LLM_MODEL (qwen-plus) 兜底

# 方式 1: model_overrides (最灵活)
MODEL_OVERRIDES={"reasoning": "qwq-32b", "docgen": "qwen-max", "docgen_light": "qwen-turbo"}

# 方式 2: 快捷配置 (已有)
LLM_MODEL_LIGHT=qwen-turbo     # → TaskType.DOCGEN_LIGHT
LLM_MODEL_EXTRACT=qwen-turbo   # → TaskType.EXTRACT
```

**与 config.py 的对应关系**（已有字段，无需新增）：

```python
# config.py — 已经存在的字段
model_overrides: dict[str, str] = {}          # {"reasoning": "qwq-32b", ...}
llm_model_light: str | None = None            # TaskType.DOCGEN_LIGHT 快捷方式
llm_model_extract: str | None = None          # TaskType.EXTRACT 快捷方式
```

### 2.4 调用方式（对齐 llm_support/ API）

各 DocGen 节点通过 `task_type` 参数选择模型，**不传 tier**：

```python
# ── edu_planner 节点（Strategic = REASONING）──
outline = await acompletion(
    messages=planner_messages,
    task_type=TaskType.REASONING,     # → 使用 qwq-32b / qwen-max
)

# ── pedagogy_craft 节点（Smart = DOCGEN）──
chapter_md = await acompletion(
    messages=craft_messages,
    task_type=TaskType.DOCGEN,        # → 使用 qwen-max / qwen-plus
)

# ── targeted_research 压缩（Fast = DOCGEN_LIGHT）──
compressed = await acompletion(
    messages=compress_messages,
    task_type=TaskType.DOCGEN_LIGHT,  # → 使用 qwen-turbo
)
```

### 2.5 降级容错链（通过 TaskType 切换实现）

```python
# shared/infra/llm_support/fallback.py — 新增文件

from app.shared.infra.llm_support.text import acompletion
from app.shared.infra.model_router import TaskType
from app.shared.infra.exceptions import LLMCallError

import structlog
logger = structlog.get_logger()

# TaskType 降级链定义
_FALLBACK_CHAINS: dict[TaskType, list[TaskType]] = {
    TaskType.REASONING:    [TaskType.REASONING, TaskType.DOCGEN, TaskType.DEFAULT],
    TaskType.DOCGEN:       [TaskType.DOCGEN, TaskType.DOCGEN_LIGHT, TaskType.DEFAULT],
    TaskType.DOCGEN_LIGHT: [TaskType.DOCGEN_LIGHT, TaskType.DEFAULT],
}

# 降级时的安全 Token Budget
_FALLBACK_TOKEN_LIMITS: dict[TaskType, int] = {
    TaskType.REASONING: 4000,
    TaskType.DOCGEN: 8000,
    TaskType.DOCGEN_LIGHT: 4000,
    TaskType.DEFAULT: 4000,
}


async def acompletion_with_fallback(
    messages: list[dict],
    *,
    task_type: TaskType,
    **kwargs,
) -> str:
    """带降级容错的 LLM 调用。

    REASONING 失败 → 重试(带 token_limit) → 降级 DOCGEN → 降级 DEFAULT
    DOCGEN 失败 → 重试 → 降级 DOCGEN_LIGHT → 降级 DEFAULT
    DOCGEN_LIGHT 失败 → 重试 → 降级 DEFAULT → 抛出异常
    """

    chain = _FALLBACK_CHAINS.get(task_type, [task_type])

    for i, fallback_type in enumerate(chain):
        try:
            call_kwargs = {**kwargs}

            # 降级时注入 token budget + 降级元数据
            if i > 0:
                call_kwargs["max_tokens"] = _FALLBACK_TOKEN_LIMITS.get(
                    fallback_type, 4000
                )

            return await acompletion(
                messages,
                task_type=fallback_type,
                **call_kwargs,
            )
        except Exception as exc:
            next_type = chain[i + 1].value if i + 1 < len(chain) else "EXHAUSTED"
            logger.warning(
                "llm_task_type_fallback",
                from_type=fallback_type.value,
                to_type=next_type,
                error=str(exc),
            )
            continue

    raise LLMCallError(reason="All task type fallbacks exhausted")
```

> [!NOTE]
> 降级链只在 DocGen 流程内部使用。Interact / Examine / Ingest 等其他流程不受影响，
> 它们继续使用 `acompletion(task_type=TaskType.CHAT)` 等现有方式。

### 2.6 LangSmith 适配

LangSmith metadata 中通过 `task_type` 字段天然支持按"模型层级"分析：

```python
# llm_support/observability.py 已有逻辑 — 无需额外改动
# 每次 LLM 调用自动记录 task_type，等效于记录了 tier 信息

# LangSmith Dashboard 查询示例：
# - metadata.task_type = "reasoning"    → Strategic 级调用
# - metadata.task_type = "docgen"       → Smart 级调用
# - metadata.task_type = "docgen_light" → Fast 级调用
```

降级事件通过 `llm_task_type_fallback` 日志追踪：
```python
# 在 LangSmith 中搜索降级事件
filter: metadata.from_type != metadata.task_type
```

### 2.7 与现有系统的兼容性

| 影响范围 | 说明 |
|:---|:---|
| `model_router.py` | **不改动**。`get_task_profile()` 签名和逻辑完全不变 |
| `llm_support/` | **不改动**。`acompletion()` 签名不变，只通过 `task_type` 参数走不同路由 |
| `config.py` | **不新增字段**。复用已有的 `model_overrides` + `llm_model_light` |
| Ingest / Interact / Examine / Profile | **零影响**。它们不使用 `acompletion_with_fallback()`，也不涉及新 TaskType |
| `tracing.py` | **不改动**。已有的 `task_type` metadata 天然支持 |

唯一新增的文件：`llm_support/fallback.py`（~60 行），纯新增不改旧代码。

---
