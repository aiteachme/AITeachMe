## 十、LangSmith 全链路可观测性设计

### 10.1 设计原则

**每个模块从第一天就接入 LangSmith，不留"后补"的债。**

当前项目已有的 LangSmith 基础设施非常扎实（`tracing.py` 的 `llm_trace_scope` + `langsmith_tracing_scope` + `LLMCallTracker` + `wrap_digest_node`），重构的目标是**扩展而非替换**。

### 10.2 新增追踪维度

| 维度 | 字段名 | 来源 | 用途 |
|:---|:---|:---|:---|
| LLM 分级 | `llm_tier` | `acompletion_with_fallback()` 的 tier 参数 | 按 Strategic/Smart/Fast 分析成本和延迟 |
| 降级事件 | `llm_fallback_from` / `llm_fallback_to` | 降级容错链触发时 | 监控模型稳定性 |
| Skill 名称 | `skill_name` | `BaseSkill.run()` | 按 Skill 分析调用频率和耗时 |
| Retriever 名称 | `retriever_name` | `BaseRetriever.traced_search()` | 按检索器分析命中率 |
| 文档模式 | `digest_mode` | DocGenState 的 `digest_mode` | 区分速成课/系统课的性能差异 |
| 章节索引 | `chapter_index` | fan-out 节点的 state | 定位慢章节 |

### 10.3 metadata 注入点

```python
# 所有 LLM 调用自动注入的 metadata（扩展 build_langsmith_metadata）

{
    # 现有字段（不变）
    "app_version": "0.2.0",
    "subject": "偏导数",
    "build_session_id": "abc123",
    "workflow": "digest.docgen",
    "lane": "docs",
    "node": "edu_planner",

    # 新增字段
    "llm_tier": "strategic",           # 新增
    "digest_mode": "sprint",           # 新增
    "chapter_index": 1,                # 新增（fan-out 节点）
    "skill_name": "ResearchConductor", # 新增（Skill 内部调用时）
    "retriever_name": "bing",          # 新增（检索器调用时）
}
```

### 10.4 tags 扩展

```python
# 所有 LLM 调用自动注入的 tags（扩展 build_langsmith_tags）

[
    "digest.docgen",          # workflow
    "docs",                   # lane
    "edu_planner",            # node
    "tier:strategic",         # 新增：LLM 分级
    "mode:sprint",            # 新增：文档模式
]
```

### 10.5 自定义 LangSmith Dashboard 建议

重构完成后，建议在 LangSmith 中创建以下自定义视图：

| Dashboard 名称 | 筛选条件 | 关注指标 |
|:---|:---|:---|
| **Tier 成本分析** | `metadata.llm_tier` 分组 | 各 tier 的 token 消耗、平均延迟、调用次数 |
| **降级事件监控** | `metadata.llm_fallback_from` 非空 | 降级频率、降级原因、降级后延迟 |
| **DocGen 端到端** | `workflow=digest.docgen` | 总耗时、各节点耗时占比、章节数 |
| **检索器命中率** | `metadata.retriever_name` 分组 | 各检索器的结果数、延迟、被采用率 |
| **速成 vs 系统** | `metadata.digest_mode` 分组 | 两种模式的耗时、token、章节数对比 |
| **章节耗时分布** | `metadata.chapter_index` 分组 | 按章节看 `targeted_research` + `pedagogy_craft` 耗时 |
| **富媒体成功率** | `node=enrich_document` | image/mermaid 生成的成功/失败比 |
| **检索降级频率** | `metadata.retriever_name=local_rag` | local_rag 不足时降级到 web 的频率 |

### 10.6 各节点追踪规范补全

以下 4 个节点在原设计中未定义 metadata，现补全：

| 节点 | 新增 metadata 字段 | 说明 |
|:---|:---|:---|
| `load_context` | `chunk_count`, `file_count`, `has_subject_profile` | 监控输入规模 |
| `collect_materials` | `total_sources`, `local_rag_hits`, `web_hits`, `compression_ratio` | 检索效果统计 |
| `collect_drafts` | `total_chapters`, `total_word_count`, `placeholder_count` | 写作产出统计 |
| `finalize_assemble` | `doc_ids`, `final_word_count`, `storage_ms` | 入库结果 |

---
