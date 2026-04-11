## 附录 A：目标数据结构

> 说明：以下结构分为“当前代码已存在的核心字段”和“本轮建议新增的字段”。

### A.1 `BuildContract`（目标）

```python
class BuildContract(BaseModel):
    course_type: Literal["sprint", "systematic"]
    learning_goal: str
    tone: Literal["casual", "professional", "encouraging", "concise"]
    target_word_count: int
    formula_depth: Literal["light", "standard", "full_derivation"]
    example_density: Literal["low", "medium", "high"]
    retrieval_profile: str
    media_preferences: dict[str, bool]
    chapter_contracts: list["ChapterContract"]
```

### A.2 `ChapterContract`（目标）

```python
class ChapterContract(BaseModel):
    chapter_index: int
    title: str
    objective: str
    required_elements: list[str]
    search_queries: list[str]
    writing_instructions: str
    media_hints: dict[str, list[str]]
    source_file_ids: list[int]
```

### A.3 `ChapterMaterial`（当前已有基础，建议扩展）

```python
class ChapterMaterial(TypedDict):
    chapter_index: int
    dense_context: str
    sources: list[str]
    source_details: list[dict[str, object]]
    local_hits: int
    web_hits: int
    query_count: int
    fallback_used: bool
    requested_profile: str              # 新增
    applied_profile: str                # 新增
    research_rounds: int                # 新增
    gaps_remaining: list[str]           # 新增
    confidence_level: str               # 新增
```

### A.4 `ChapterDraft`（目标）

```python
class ChapterDraft(BaseModel):
    chapter_index: int
    title: str
    markdown: str
    word_count: int
    required_elements_coverage: dict[str, bool]
    question_hooks: list[str]
    asset_hints: dict[str, list[str]]
    quality_flags: list[str]
```

### A.5 `AssetPlan`（目标）

```python
class AssetPlan(BaseModel):
    chapter_index: int
    mermaid: list[str] = []
    image: list[str] = []
    interactive_html: list[str] = []
    animation: list[str] = []
    formula_cards: list[str] = []
    summary_cards: list[str] = []
```

---

## 附录 B：当前关键实现位置

| 能力 | 当前文件 |
| --- | --- |
| course type / retrieval profile helper | `backend/app/workflows/digest/shared/contracts.py` |
| docgen writer prompt | `backend/app/workflows/digest/prompts/docgen_prompts.py` |
| chapter context runtime | `backend/app/workflows/digest/docgen/runtime/chapter_context.py` |
| context compression | `backend/app/shared/infra/search/context_compression.py` |
| source curation | `backend/app/shared/infra/search/source_curation.py` |
| teaching scaffold | `backend/app/teaching/documents/report_generation.py` |
| teaching content blocks | `backend/app/teaching/documents/content_blocks.py` |
| docgen load/research/write nodes | `backend/app/workflows/digest/docgen/nodes/*.py` |
| LLM fallback / tier | `backend/app/shared/infra/llm_support/fallback.py` |
| LLM routing | `backend/app/shared/infra/llm_support/routing.py` |

---

## 附录 C：最值得迁移的参考算法

### 来自 `gpt-researcher`

| 参考点 | 借法 |
| --- | --- |
| `skills/deep_research.py` | 借“补检索”的思路，不照搬递归实现 |
| `skills/researcher.py` | 借 query planning 与多 retriever 调度思路 |
| `context/compression.py` | 借快慢路径压缩思路 |
| `DetailedReport` | 借子话题展开与章节差异化研究思路 |

### 来自 `DeepTutor`

| 参考点 | 借法 |
| --- | --- |
| `agents/research/mode_strategy.py` | 借模式策略表，把 `sprint/systematic` 收敛成可执行参数集 |
| `agents/research/research_pipeline.py` | 借动态 topic queue 与 progress event 思路 |
| `agents/guide/guide_manager.py` | 借课程产物的”设计 -> 页面 -> 追问 -> 总结”形态 |
| `agents/math_animator/pipeline.py` | 借富媒体 sidecar 的分析/设计/生成/重试/总结链 |

### 来自 `DeepTutor`（2026-04-11 深度分析补充）

| 参考点 | 借法 |
| --- | --- |
| `agents/solve/agents/planner_agent.py` | 借 pre-retrieval planning：先生成多条 query → 并行检索 → LLM 聚合 → 再规划。强化 `planner.ground_concepts` |
| `agents/guide/agents/interactive_agent.py` | 借知识点级交互 HTML 生成（KaTeX 支持 + fallback 模板）。用于 `runtime/assets.py` 的 interactive 占位符展开 |
| `agents/question/agents/followup_agent.py` | 借结构化 follow-up 上下文（correctness + explanation + knowledge context）。用于 examine 引擎的追问设计 |
| `services/session/context_builder.py` | 借对话历史压缩到 token budget 的策略。用于 interact 引擎的长对话管理 |
| `agents/chat/agentic_pipeline.py` | 借 thinking → acting → observing → responding 的 agent 循环。参考但不照搬 |
| `knowledge/manager.py` | 借 KB 状态管理（ready/processing/error + needs_reindex）。当前 `docgen_store` 已有类似机制 |

---

## 附录 D：建议新增的算法参数

> 这些是建议新增或显式化的配置项，不代表当前仓库已经全部实现。

```env
DOCGEN_SPRINT_TARGET_WORDS=6000
DOCGEN_SYSTEMATIC_TARGET_WORDS=12000
DOCGEN_SPRINT_MAX_RESEARCH_ROUNDS=1
DOCGEN_SYSTEMATIC_MAX_RESEARCH_ROUNDS=2
DOCGEN_SPRINT_SUB_QUERY_COUNT=3
DOCGEN_SYSTEMATIC_SUB_QUERY_COUNT=5
DOCGEN_ENABLE_ASSET_SIDECAR=true
DOCGEN_ENABLE_INTERACTIVE_HTML=false
DOCGEN_ENABLE_ANIMATION=false
```

---

## 附录 E：最小质量检查表

- `BuildContract` 是否完成校验
- `retrieval_profile` 是否真正影响 retriever 组合
- `ChapterMaterial` 是否含 coverage / gaps / confidence
- `ChapterDraft` 是否含 question hooks / asset hints
- `sprint / systematic` 是否体现出明显产物差异
- LangSmith 是否能看到 rounds / assets / fallback
