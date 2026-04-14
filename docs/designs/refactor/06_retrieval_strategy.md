## 检索策略 — 待完成部分

> 最后更新：2026-04-14
>
> 已落地：profile 化 retriever 工厂、micro-loop research、runtime cache、source_class_breakdown trace。
> 本文档只保留尚未完成的方向。

---

## 1. 学科化 retrieval profile（待实现）

当前 profile 粒度偏通用，后续需要：

- 按学科定义 source class 权重（如数学偏学术源，考研偏题解站）
- 按学科调整 `sub_query_count`、`max_research_rounds`、`preferred_source_classes`
- 让 `SourceCurator` 的教育场景权重可按学科配置

---

## 2. 持久化缓存策略（待实现）

当前只有进程内内存缓存，后续需要：

- 确定缓存放置层（文件 / SQLite / Redis）
- subject-aware / user-aware 隔离策略
- profile-specific TTL 与淘汰策略
- 命中率与收益分析

---

## 3. 压缩结果增强（待实现）

当前压缩后只保证"相关"，后续建议补：

- `concept_density`：概念覆盖密度
- `example_density`：例题覆盖密度
- `formula_presence`：公式存在性

确保压缩结果不仅相关，而且"可写、可教、可做题"。

---

## 4. 本地教育语料库（待启动）

目标：系统级知识底仓，不是盗版资料仓库。

最小字段：`subject`、`topic`、`source_url`、`source_kind`、`source_class`、`license_tag`、`derived_summary`、`keywords`

合规红线：
- 不把商业教材原文长期入库
- 用户上传资料不默认沉淀为系统底仓
- 只收授权明确或自建衍生条目

待拍板：第一批学科和语料生产/审核流程。

---

## 5. 检索层级参考

| Layer | 来源 | 说明 |
| --- | --- | --- |
| 0 | 用户上传资料 | 最高优先级 |
| 1 | 系统本地教育语料库 | 补齐基础知识（待建设） |
| 2 | 教育垂直 Web | 高校课程页、公开课平台 |
| 3 | 学术来源 | arXiv、Semantic Scholar |
| 4 | 通用 Web 兜底 | Bing、DuckDuckGo、Tavily |
