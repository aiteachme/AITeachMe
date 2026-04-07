## 附录 A：关键数据结构定义

### A.1 ChapterPlan（edu_planner 输出）

```python
class ChapterPlan(TypedDict):
    chapter_index: int
    title: str
    required_elements: list[str]      # 该章节必须包含的内容类型
    search_queries: list[str]         # 供 targeted_research 使用的搜索词
    writing_instructions: str         # 给 pedagogy_craft 的写作指令
    media_hints: MediaHints           # 富媒体提示
    estimated_words: int              # 预估字数（系统课用于控制总字数）

class MediaHints(TypedDict):
    images: list[str]                 # 需要生成的图片描述
    mermaid: list[str]                # 需要生成的思维导图描述
    interactive: list[str]            # 需要生成的交互 HTML 描述（V2）
```

### A.2 ChapterMaterial（targeted_research 输出）

```python
class ChapterMaterial(TypedDict):
    chapter_index: int
    dense_context: str                # 高浓度精华文本
    sources: list[str]                # 引用来源 URL
    local_rag_hits: int               # 本地 RAG 命中数
    web_search_hits: int              # 外网搜索命中数
```

### A.3 ChapterDraft（pedagogy_craft 输出）

```python
class ChapterDraft(TypedDict):
    chapter_index: int
    title: str
    markdown_content: str             # 带占位符的 Markdown
    image_placeholders: list[str]     # [IMAGE: ...] 占位符列表
    mermaid_placeholders: list[str]   # [MERMAID: ...] 占位符列表
    word_count: int                   # 实际字数
```

### A.4 ScrapedPage（web_scraping 输出）

```python
@dataclass(slots=True)
class ScrapedPage:
    url: str
    content: str
    success: bool
    error: str | None = None
    content_type: str = "html"        # "html" | "pdf"
    title: str = ""
```

---

## 附录 B：Prompt 模板索引

| Prompt 名称 | 用途 | 模型层级 | 所在文件 |
|:---|:---|:---|:---|
| `sprint_planner` | 速成课大纲规划 | Strategic | `prompts/sprint_prompts.py` |
| `systematic_planner` | 系统课大纲规划 | Strategic | `prompts/systematic_prompts.py` |
| `generate_sub_queries` | 子查询生成 | Strategic | `tools/builtin/query_processing.py` |
| `purify_material` | 素材提纯 | Fast | `nodes/targeted_research_node.py` |
| `sprint_writer` | 速成课章节写作 | Smart | `prompts/sprint_prompts.py` |
| `systematic_writer` | 系统课章节写作 | Smart | `prompts/systematic_prompts.py` |
| `generate_mermaid` | Mermaid 思维导图生成 | Fast | `skills/mermaid_generator.py` |
| `plan_image_concepts` | 图片规划 | Fast | `skills/image_generator.py` |
| `inject_exam_questions` | 趁热打铁出题 | Smart | `nodes/inject_examine_node.py` |

---

## 附录 C：环境变量完整清单（新增部分）

```env
# ══════════════════════════════════════════════
# 三级模型分层（可选，不配则 fallback 到 LLM_MODEL）
# ══════════════════════════════════════════════
STRATEGIC_LLM=qwq-32b
SMART_LLM=qwen-max
FAST_LLM=qwen-turbo
STRATEGIC_TOKEN_LIMIT=4000
SMART_TOKEN_LIMIT=8000
FAST_TOKEN_LIMIT=3000

# ══════════════════════════════════════════════
# 检索器配置
# ══════════════════════════════════════════════
WEB_SEARCH_RETRIEVER=bing
BING_API_KEY=
BOCHA_API_KEY=
LOCAL_RAG_PRIORITY=true
LOCAL_RAG_MIN_RESULTS=3

# ══════════════════════════════════════════════
# 文生图配置（可选）
# ══════════════════════════════════════════════
IMAGE_GENERATION_ENABLED=false
IMAGE_GENERATION_MODEL=wanxiang-v2
IMAGE_GENERATION_MAX_IMAGES=3

# ══════════════════════════════════════════════
# DocGen 模式默认值
# ══════════════════════════════════════════════
DOCGEN_DEFAULT_MODE=sprint
DOCGEN_DEFAULT_TONE=casual
DOCGEN_SYSTEMATIC_MIN_WORDS=10000
DOCGEN_SPRINT_MAX_CHAPTERS=4
DOCGEN_SYSTEMATIC_MAX_CHAPTERS=10
```
