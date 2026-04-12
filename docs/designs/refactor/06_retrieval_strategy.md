## 六、检索策略与教育资源库

> 目标：让检索真正服务“教育型文档生产”，而不是简单堆更多搜索引擎。
> 最后更新：2026-04-12

---

## 6.1 当前真实基线

当前仓库已经具备：

- `search/factory.py` 的 profile 化 retriever 工厂
- `local_rag + bing + duckduckgo + tavily + bocha + arxiv + semantic_scholar`
- `SourceCurator` 的规则过滤 + 词法/可信度评分
- `ContextManager` 的快慢路径压缩
- `DocGenChapterContextRuntime` 已把 `retrieval_profile` 实际传入 `get_retrievers_for_subject()`
- `targeted_research` 已输出 `requested_profile / applied_profile / research_rounds / coverage_score / gaps_remaining / source_class_breakdown`
- 单章 research 已升级为受控 micro-loop：`seed -> retrieve -> assess coverage -> enqueue gap queries -> stop by round cap / coverage / diminishing returns`

但当前最关键的真实差距是：

> 现在真正的差距已经不再是“profile 没打通”，而是 profile、gap detection 和 source class 还需要继续做更细的学科调权与缓存优化。

这意味着，后续优化重点不是“再接几个搜索 API”，而是继续提升 micro-loop 的调参质量、source class 的教育场景权重和缓存命中率。

---

## 6.2 参考项目里真正值得借的算法思想

### 来自 `gpt-researcher`

- 查询规划和检索执行分离
- research 先压缩，再写作
- 对不同 research 深度使用不同查询数和并发策略
- 小文档走快路径，大文档再走 embedding/compression

### 来自 `DeepTutor`

- `ModeStrategy` 把模式差异收敛成单一策略表
- `ResearchPipeline` 用动态 topic queue 管理并发研究任务
- 工具调用有 timeout / retry / progress event
- 输出质量有轻量 post-check，而不是完全相信生成结果
- **Pre-retrieval planning**（2026-04-11 补充）：DeepSolve planner 在规划前先执行一轮轻量检索：
  1. 生成多条多样化检索 query
  2. 并行检索
  3. LLM 聚合检索结果（限制字符数）
  4. 基于聚合结果再做规划
  这个模式可以显著提升 planner 的主题锚定质量，AITeachMe 的 `planner.ground_concepts` 已有类似思路，但可以进一步强化聚合步骤。

---

## 6.3 AITeachMe 的检索目标

教育场景下，检索和通用 deep research 不一样：

1. 最新不一定最重要，可信、可教、可解释更重要。
2. 用户上传资料通常比公网更贴题。
3. `sprint` 和 `systematic` 需要不同的检索深度和来源结构。
4. 需要为后续文档写作、练习生成、媒体规划提供不同类型的证据。

---

## 6.4 建议的检索层级

### Layer 0：用户上传资料

最高优先级：

- PDF / PPT / DOCX / Markdown
- ingest 结构化后的 section / chunk

### Layer 1：系统本地教育语料库

用于补齐用户没上传、但课程必须有的基础知识：

- 开放教材
- 公开课讲义
- 自建知识条目

### Layer 2：教育垂直 Web

用于补：

- 高校课程页
- 公开课平台
- 学科知识站
- 公开题型解析站

### Layer 3：学术来源

主要服务 `systematic`：

- arXiv
- Semantic Scholar
- 后续可按学科接 PubMed 等

### Layer 4：通用 Web 兜底

用于补广度和补召回：

- Bing
- DuckDuckGo
- Tavily
- Bocha

---

## 6.5 建议的 research request 类型

不要把所有查询都当成一种 research。
至少区分：

| 请求类型 | 目标 | 推荐来源 |
| --- | --- | --- |
| `planner_grounding` | 给 Planner 建立主题锚点 | local_rag + 本地语料 + 少量教育 Web |
| `concept_grounding` | 定义、概念边界、前置知识 | local_rag + 教育语料 + 高校课程页 |
| `exam_pattern_mining` | 高频题型、易错点、得分路径 | local_rag + 中文教育站点 + 通用 Web |
| `derivation_support` | 公式推导、适用条件、定理解释 | 本地资料 + 教材/课程页 + 学术源 |
| `worked_examples` | 典型例题和变式 | 本地资料 + 教育题解站点 |
| `media_hunting` | Mermaid / image / interactive 素材想法 | 高质量教育页和结构图站点 |

---

## 6.6 课程模式对应的检索 profile

### `planner_grounding`

- 目标：快，轻，给 Planner 定方向
- 默认来源：
  - `local_rag`
  - 本地语料
  - 少量教育 Web snippet

### `docgen_sprint`

- 目标：抓高频考点、题型、误区、速记点
- 默认来源：
  - `local_rag`
  - `bocha/tavily`
  - `bing`
  - `duckduckgo`

### `docgen_systematic`

- 目标：抓定义、结构、推导、联系、应用
- 默认来源：
  - `local_rag`
  - 本地语料
  - `tavily`
  - `arxiv`
  - `semantic_scholar`

### `media_hunting`

- 目标：找适合改写成图示、交互页或动画的结构素材
- 默认来源：
  - 高质量课程页
  - 可公开引用的结构图页面
  - 学科知识站

---

## 6.7 需要迁移的具体算法

### 算法 1：模式策略表

借 `DeepTutor` 的 `ModeStrategy` 思想，把 `sprint/systematic` 的检索策略集中到一个表，而不是散在多个 node 和 prompt 中。

每个策略至少定义：

- `sub_query_count`
- `max_research_rounds`
- `max_results_per_query`
- `preferred_source_classes`
- `fallback_source_classes`
- `min_section_length`
- `enable_academic`
- `enable_exam_sites`

### 算法 2：research 微队列，而不是一次性 query list

当前 `ChapterContextRuntime` 已经具备：

- seed query + sub query planning
- per-round retrieve / curate / compress
- coverage assessment
- gap query enqueue
- round cap / diminishing return stop 条件

当前实现仍然保持“单章内部轻量 queue”，而不是引入额外 graph 拓扑：

```text
seed_queries
→ retrieve
→ assess coverage
→ if gap: enqueue gap_queries
→ until queue empty or round limit reached
```

这不是把 `DeepTutor` 的整条队列系统搬过来，而是在单章 research runtime 中借它的动态任务思想，同时保持 LangGraph 顶层图不变。

### 算法 3：压缩快慢路径继续保留，但要加“写作可用性”校验

当前 `ContextManager` 已有：

- 小材料快路径
- embedding filter
- lexical fallback

目前已新增：

- `coverage_score`
- `gaps_remaining`
- `source_class_breakdown`
- `research_rounds`

后续仍建议补：

- `concept_density`
- `example_density`
- `formula_presence`

否则压缩后虽然“相关”，未必“可写”。

### 算法 4：来源排序要按教育场景调权

当前 `SourceCurator` 已有：

- 可信度评分
- query overlap
- local source 加权

建议继续增强：

- `source_class` 权重
- 课程模式权重
- 例题型请求优先题解/讲义
- 系统课请求优先高校/教材/学术

---

## 6.8 推荐的来源分类

后续检索与 LangSmith 统一使用：

- `local_user_material`
- `local_edu_corpus`
- `edu_web`
- `academic_web`
- `general_web`

这五类来源要同时用于：

- curator 排序
- trace metadata
- dashboard 统计
- 质量分析

---

## 6.9 教育垂直检索路径建议

### 高校与公开课

- `ocw.mit.edu`
- `edx.org`
- `coursera.org`
- `xuetangx.com`
- `icourse163.org`
- 高校课程主页和讲义页

### 学科知识站

- `mathworld.wolfram.com`
- `wikipedia.org`
- 公开百科资料
- 学科型知识博客和教学站

### 中文考试与题解站

- 公开考试解析站
- 高校公开试题/讲义
- 高质量中文题解社区

注意：

- 这些来源只是候选，不是默认信任
- 最终仍要经过 curator 过滤和来源分类

---

## 6.10 本地教育语料库策略

### 语料目标

不是盗版资料仓库，而是：

- 系统级知识底仓
- 带来源与授权的衍生知识条目
- 可被 RAG 和教学工作流稳定消费的中间语料

### 建议最小字段

- `subject`
- `topic`
- `source_url`
- `source_kind`
- `source_class`
- `license_tag`
- `rights_note`
- `derived_summary`
- `keywords`

### 合规红线

- 不把商业教材和机构资料原文长期入库
- 用户上传资料可以参与当前构建，但不默认沉淀为系统底仓
- 系统长期语料库只收授权明确或自建衍生条目

---

## 6.11 缓存与性能

至少缓存三类对象：

- `(query, profile, retriever)` 的检索结果
- `(url, reader_kind)` 的读取结果
- `(query, focus_terms, compression_budget)` 的压缩结果

原因：

- Planner、Grounding、Asset 很容易重复查询相近内容
- `systematic` 模式如果不缓存，时延会迅速失控

---

## 6.12 关键实现顺序

> 注意：这里的"阶段"是检索专项分期，不等同于 `08_migration_plan.md` 的 Phase 编号。

### 当前已落地

1. `profile` 已真实传入 `DocGenChapterContextRuntime` → `get_retrievers_for_subject()`
2. `requested_profile / applied_profile` 已统一输出到 trace metadata
3. trace 已补 `source_class_breakdown`
4. 章节 research 已增加 queue 化补检索

### 后续批次再做

- 更细粒度的学科特定 profile
- 本地教育语料库首批建设
- 交互与动画素材检索
- 检索缓存与 profile-specific 调权

---

## 6.13 一句话结论

对 AITeachMe 来说，检索优化的重点不是“再接几个 API”，而是：

- 继续调优 `retrieval_profile` 对不同来源类型的权重
- 让章节 research 的轻量 topic queue 更稳、更快、更少无效 round
- 让压缩结果不仅相关，而且可写、可教、可做题
