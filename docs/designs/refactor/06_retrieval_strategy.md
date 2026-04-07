## 六、检索策略与教育资源库

### 6.1 多层检索架构

教育场景的检索不同于通用 Deep Research——我们需要的不是"最新新闻"，而是"最权威的教学解释"。因此检索策略需要分层设计：

```
Layer 0: 用户上传资料（本地 RAG）     ← 最高优先级，零成本，最贴合用户需求
Layer 1: 本地教育资源库（预置语料）    ← 高质量教材/讲义/速成课素材
Layer 2: 教育垂直网站定向搜索          ← 知乎/CSDN/考研论坛/学科百科
Layer 3: 通用 Web 搜索兜底             ← Bing/DuckDuckGo
```

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
