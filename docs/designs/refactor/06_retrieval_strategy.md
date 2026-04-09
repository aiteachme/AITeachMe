## 六、检索策略与教育资源库

### 6.1 多层检索架构

教育场景的检索不同于通用 Deep Research——我们需要的不是"最新新闻"，而是"最权威的教学解释"。因此检索策略需要分层设计：

```
Layer 0: 用户上传资料（本地 RAG）     ← 最高优先级，零成本，最贴合用户需求
Layer 1: 本地教育资源库（预置语料）    ← 高质量教材/讲义/速成课素材
Layer 2: 教育垂直网站定向搜索          ← 知乎/CSDN/考研论坛/学科百科
Layer 3: 通用 Web 搜索兜底             ← Bing/DuckDuckGo
```

### 6.1.1 GPT-Researcher 检索器复用结论（新增）

`gpt-researcher` 确实内置了较多 retriever，但**不能机械地“全量搬过来”**。原因很直接：

- 很多只是不同商业搜索 API 的薄包装，能力高度重叠
- 它们的返回格式并不统一，有的返回 `href/body`，有的直接返回 `raw_content`
- 多数实现是同步 `requests` 风格，直接搬入我们当前 `BaseRetriever` + LangSmith tracing 体系并不优雅
- AITeachMe 的目标是“教学文档质量”，不是“搜索引擎收藏夹数量”

因此我们的策略应是：**复用思路与少量高价值实现，不追求 1:1 数量对齐。**

#### 复用优先级矩阵

| 类型 | gpt-researcher 现有项 | 是否建议引入 AITeachMe | 结论 |
|:---|:---|:---|:---|
| 通用 Web 搜索 | `bing` / `duckduckgo` / `google` / `serper` / `serpapi` / `searchapi` / `searx` / `exa` / `tavily` / `bocha` | **部分引入** | 只保留 2-4 个核心入口，避免重复维护 |
| 学术检索 | `arxiv` / `semantic_scholar` | **强烈建议引入** | 对 AI、CS、理工科系统课最有价值 |
| 医学文献 | `pubmed_central` | **按学科开关引入** | 只在医学/生物方向启用 |
| 自定义私有检索 | `custom` | **强烈建议引入** | 很适合企业内训资料库 / 私有知识库 |
| MCP 工具型检索 | `mcp` | **择机重构引入** | 不应直接照搬，要适配我们现有 MCP / tool 体系 |

#### 具体判断

**1. 不需要完整复用所有通用 Web 检索器**

像 `google` / `serper` / `serpapi` / `searchapi` / `searx` / `tavily` / `exa`，本质上大多还是“给你若干网页结果”的通用搜索入口。

对 AITeachMe 而言：

- 已有 `local_rag` 是最高优先级
- 已有 `bing` / `duckduckgo` 已能覆盖基础通用搜索
- `bocha` 更适合补中文互联网

所以这里真正应该做的是：

- **补齐已有 `bocha` 真实现**
- 引入 **一个高质量商业 Web 检索器** 作为增强，不必 5 个都接
- 支持**多检索器配置列表**，而不是单个 `web_search_retriever`

推荐优先级：

1. `tavily`
2. `bocha`
3. `bing`
4. `duckduckgo`

原因：

- `tavily` 适合 research 类摘要检索，信息密度高
- `bocha` 更贴中文教育互联网
- `bing` 结果稳定
- `duckduckgo` 免费兜底

**2. 真正值得补的是学术检索器**

这部分是我们当前最缺、而 `gpt-researcher` 已经给出可参考实现的：

- `arxiv`
- `semantic_scholar`
- `pubmed_central`

它们对 AITeachMe 的价值不是“让文档更学术”，而是：

- 系统课遇到 AI / CS / 数学建模 / 医学 / 工程类主题时，能提供更可信的背景材料
- 用来支撑“延伸阅读”“进阶视角”“论文来源”比普通搜索结果强很多
- 可以作为 Planner 和 DocGen 的“高置信度补充源”

建议落地方式：

- `arxiv`：P1，优先服务 AI / CS / 理工类主题
- `semantic_scholar`：P1，补论文摘要和开放获取链接
- `pubmed_central`：P2，仅当 `subject_profile.discipline` 命中医学/生命科学时启用

**3. `custom` 比多数商业搜索 API 更值得复用**

`gpt-researcher` 的 `custom` retriever 核心价值不是代码本身，而是这个思路：

- 允许业务方把任意 HTTP/内部知识库包装成统一检索器
- 返回统一 `SearchResult`
- 不需要改主流程

这对 AITeachMe 很有价值，因为未来你们很可能会有：

- 企业内部培训资料检索
- 课程平台自建题库检索
- 私有教材索引 API

所以 `custom` 应该进入我们的正式设计，而不是以后临时写特判。

**4. `mcp` 不要直接复用原实现，要复用“工具选择”思路**

`gpt-researcher` 的 MCP retriever 本质上是在“把一组工具伪装成 retriever”。这个思路可以借，但实现方式不应照搬。

对 AITeachMe 更合适的做法是：

- 保持 retriever 负责“拿来源”
- 保持 tool/action 负责“执行特殊能力”
- 如果走 MCP，应在 Planner / ResearchConductor 中增加“工具选择层”，而不是把 MCP 强塞进 retriever 工厂

换句话说：

- `mcp retriever` 这个名字可以不复用
- “先挑工具，再执行工具，再把结果转成 research context” 这个模式应该复用

#### 推荐的 AITeachMe 检索器路线图

**P0：先补齐现有短板**

- `bocha` 从 placeholder 改为真实实现
- `get_retrievers_for_subject()` 支持配置列表，而不是“单主检索器 + duckduckgo fallback”
- 增加 retriever profile，例如：
  - `planner_fast`: `local_rag + bocha + duckduckgo`
  - `docgen_balanced`: `local_rag + tavily + bocha`
  - `docgen_academic`: `local_rag + tavily + arxiv + semantic_scholar`

**P1：补最有价值的 3 个**

- `tavily`
- `arxiv`
- `semantic_scholar`

**P2：做企业和垂直扩展**

- `custom`
- `pubmed_central`
- MCP 工具选择层（不是直接照搬 `mcp retriever`）

#### 最终结论

`gpt-researcher` 的 retriever 体系我们**没有必要完整复用**，但**绝对值得有选择地复用**。

正确姿势不是：

- “它有 16 个，我们也要补到 16 个”

而是：

- “把最有价值、最符合教育文档场景的那 5-7 个入口接进来”
- “把工厂和配置改成支持多检索器 profile”
- “把学术源和私有源能力补上”

对 AITeachMe 来说，真正高价值的不是“更多搜索引擎”，而是：

- 本地资料优先
- 中文教育互联网补充
- 学术来源增强
- 私有知识库接入能力
- 全链路 LangSmith 可观测

### 6.2 Layer 1：本地教育资源库设计

**目标**：预置一批高质量教育素材，作为 RAG 的"底仓"，即使用户没上传任何文件也能生成有质量的文档。

**数据来源与合规处理**：

| 来源类型 | 示例 | 合规策略 |
|:---|:---|:---|
| 公开教材 PDF | 高等数学同济版、线性代数、概率论 | 仅提取知识点摘要，不存储原文全文 |
| 公开课讲义 | MIT OCW、Coursera 公开课笔记 | CC 协议素材，标注来源 |
| 速成课素材 | 蜂考/学长笔记风格的整理 | **不直接存储原文**，而是用 AI 重新组织为我们自己的知识条目 |
| 学科百科 | 维基百科数学/物理词条 | CC-BY-SA 协议，标注来源 |
| 公式库 | LaTeX 公式集 | 数学公式本身无版权 |

**合规红线**：
- ❌ 不直接存储任何商业教材/速成课的原文
- ✅ 可以用 AI 将公开素材重新组织为"知识条目"（类似维基百科的做法）
- ✅ 每个知识条目必须标注原始来源 URL

**存储方案**：
```
data/edu_corpus/
├── math/
│   ├── calculus/           # 微积分
│   ├── linear_algebra/     # 线性代数
│   └── probability/        # 概率论
├── physics/
│   ├── mechanics/          # 力学
│   └── electromagnetism/   # 电磁学
├── cs/
│   ├── data_structures/    # 数据结构
│   └── algorithms/         # 算法
└── index.json              # 语料索引（学科→主题→chunk_ids）
```

每个知识条目存储为向量化的 chunk，可被 `LocalRAGRetriever` 直接检索。

### 6.2.1 Planner 阶段的轻量概念预检索

`edu_planner` 不能再只靠 LLM 裸生成章节计划，否则很容易出现：

- 用户资料明明强调的是 A 概念，Planner 却先写 B 概念
- 章节标题看起来合理，但缺乏事实锚点，后续检索词质量很差
- 遇到跨章节知识点时，Planner 无法稳定识别“哪些基础概念必须先补”

因此在 Planner 阶段单独增加一个 **轻量 grounding 步骤**，但它不是完整版 Deep Research：

```
load_context
  ↓
ground_concepts      # 新增：快速概念预检索
  ↓
draft_plan           # 再交给 LLM 生成研究任务与章节骨架
```

**目标**：只补“概念锚点”和“知识框架提示”，不给 Planner 引入高延迟抓取链路。

**输入来源**：

- `subject_profile.key_topics`
- `fast_hints.chapter_candidates`
- 用户最新 `user_goal`
- 上一版 `latest_plan.chapter_plan[].title`
- 当前 subject 的 `section_packets`

**查询构造原则**：

- 总查询数控制在 **3-4 条**
- 第一条固定是“主题 + 基础概念 + 知识框架”
- 剩余查询优先覆盖资料中已经出现的核心主题，例如：
  - `极限 定义 关键性质`
  - `导数 定义 关键性质`
  - `矩阵 应用场景 常见方法`
- Planner 阶段不做长链子查询扩散，不做网页抓取，不做长摘要压缩

**检索顺序**：

1. 先走 `LocalRAGRetriever`
2. 如果允许外部检索，再对前 1-2 个关键查询追加“百科 / 定义”变体走 Web 检索
3. 外部检索只取少量标题 + snippet，不进入 scraper

**输出给 Planner 的结构**：

- `concept_queries`: 本轮实际执行的概念查询
- `concept_briefing`: 给 Prompt 使用的“概念锚点摘要”
- `concept_topic_hints`: 从检索结果反推出的高频概念提示
- `concept_local_hit_count` / `concept_web_hit_count`: 用于前端状态展示与 LangSmith 追踪

**性能约束**：

- Planner grounding 目标耗时应控制在 **1-5 秒**
- 每条查询本地最多取 2 条结果
- 外部检索只覆盖前 2 条关键查询，每条最多 2 条结果
- 失败时直接降级为空 briefing，不能阻塞 `draft_plan`

**为什么这样设计**：

- 资料优先：先看用户上传内容，不先把 Planner 带偏到通用百科
- 延迟可控：避免在 Planner 阶段引入 scraper / summarize / rerank 重链路
- 对齐 Deep Research 体验：不是直接吐大纲，而是先做一个“很轻”的 research warm-up
- 对齐 LangSmith：`ground_concepts` 可以作为独立 node 追踪耗时、命中数和失败率

### 6.3 Layer 2：教育垂直网站定向搜索

在 `ResearchConductor` 的搜索阶段，对 `search_queries` 自动追加教育域限定词：

```python
# shared/infra/tools/builtin/query_processing.py

EDUCATION_SITE_FILTERS = {
    "zh": [
        "site:zhihu.com",           # 知乎（高质量中文解答）
        "site:csdn.net",            # CSDN（编程/工程类）
        "site:bilibili.com",        # B站（视频讲解的文字版）
        "site:zybuluo.com",         # 作业部落（数学笔记）
        "site:mathworld.wolfram.com",  # Wolfram MathWorld
    ],
    "university": [
        "site:icourse163.org",      # 中国大学MOOC
        "site:xuetangx.com",        # 学堂在线
        "site:open.163.com",        # 网易公开课
        "site:coursera.org",        # Coursera
        "site:ocw.mit.edu",         # MIT OCW
        "site:brilliant.org",       # Brilliant（数学/科学交互学习）
    ],
    "exam": [
        "site:kaoyan.com",          # 考研论坛
        "site:exam8.com",           # 考试吧
        "site:233.com",             # 233网校
        "真题 解析",                 # 通用考试关键词
    ],
    "knowledge": [
        "site:wikipedia.org",       # 维基百科
        "site:baike.baidu.com",     # 百度百科
        "site:mathworld.wolfram.com", # Wolfram MathWorld
    ],
}

def enrich_queries_for_education(
    queries: list[str],
    *,
    domain: str = "zh",
) -> list[str]:
    """为搜索查询追加教育域限定。

    每个原始 query 生成 2 个变体：
    1. 原始 query（不加限定，保证召回率）
    2. 原始 query + 随机一个 site filter（提高精准度）
    """
    enriched = []
    filters = EDUCATION_SITE_FILTERS.get(domain, [])
    for q in queries:
        enriched.append(q)  # 原始
        if filters:
            enriched.append(f"{q} {random.choice(filters)}")
    return enriched
```

### 6.4 检索结果质量评估

移植 gpt-researcher 的 `SourceCurator` 理念，但简化为规则 + LLM 混合评估：

```python
async def evaluate_source_quality(
    sources: list[SearchResult],
    *,
    query: str,
    max_results: int = 10,
) -> list[SearchResult]:
    """评估检索结果质量，过滤低质量来源。"""

    # 规则过滤（快速路径）
    filtered = [s for s in sources if _rule_filter(s)]

    # 如果结果足够多，跳过 LLM 评估
    if len(filtered) >= max_results:
        return filtered[:max_results]

    # LLM 评估（仅在结果不足时启用）
    if len(filtered) < max_results // 2:
        scored = await _llm_score_sources(filtered, query=query)
        scored.sort(key=lambda x: -x.score)
        return scored[:max_results]

    return filtered[:max_results]


def _rule_filter(source: SearchResult) -> bool:
    """规则过滤：去掉明显低质量来源。"""
    blacklist_domains = ["baidu.com/zhidao", "360doc.com", "docin.com"]
    return not any(d in source.url for d in blacklist_domains)
```

---
