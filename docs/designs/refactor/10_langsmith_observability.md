## 十、LangSmith 全链路可观测性设计

> **最后更新**：2026-04-08 — 反映实际实现状态，追踪维度已通过 SkillContext.trace_metadata() 落地

### 10.1 设计原则（不变）

**每个模块从第一天就接入 LangSmith，不留"后补"的债。**

当前项目已有的 LangSmith 基础设施非常扎实（`tracing.py` 的 `llm_trace_scope` + `langsmith_tracing_scope` + `LLMCallTracker` + `wrap_workflow_node`），重构的目标是**扩展而非替换**。

### 10.2 追踪维度 — ✅ 已通过 SkillContext.trace_metadata() 落地

| 维度 | 字段名 | 注入方式 | 状态 |
|:---|:---|:---|:---|
| LLM 分级 | `llm_tier` | `acompletion_with_fallback()` 的 tier 参数 | ✅ fallback.py 已实现 |
| 降级事件 | `llm_fallback_from` / `llm_fallback_to` | 降级容错链触发时自动记录 | ✅ fallback.py 已实现 |
| Skill 名称 | `skill_name` | `SkillContext.trace_metadata(skill_name=self.name)` | ✅ ResearchConductor 等 Skill 内部已注入 |
| Retriever 名称 | `retriever_name` | `BaseRetriever` 基类内置 tracing | ✅ 每个 retriever 自动记录 |
| 文档模式 | `digest_mode` | `SkillContext.digest_mode` → `trace_metadata()` 自动注入 | ✅ |
| 章节索引 | `chapter_index` | `SkillContext.chapter_index` → `trace_metadata()` 自动注入 | ✅ |
| Planner 会话 | `planner_session_id` | `SkillContext.planner_session_id` → `trace_metadata()` 自动注入 | ✅ |
| 确认方案 | `confirmed_plan_id` | `SkillContext.confirmed_plan_id` → `trace_metadata()` 自动注入 | ✅ |
| 研究阶段 | `research_stage` | ResearchConductor 内部各步骤标记（plan_sub_queries / curate_sources / build_context / purify_context） | ✅ |

**实际注入机制**：

```python
# SkillContext.trace_metadata() 自动构建追踪元数据
# Skill 内部 LLM 调用示例：
result = await self.context.resolve_llm_caller()(
    messages,
    task_type=TaskType.DOCGEN,
    tier="smart",
    extra_metadata=self.context.trace_metadata(
        skill_name=self.name,
        research_stage="purify_context",
    ),
)
# → LangSmith metadata 自动包含：
# {planner_session_id, confirmed_plan_id, digest_mode, chapter_index, skill_name, research_stage}
```

### 10.3 metadata 注入点（已实现）

```python
# 实际 LLM 调用中的 metadata 示例

{
    # 现有字段（不变）
    "subject": "偏导数",
    "build_session_id": "abc123",
    "workflow": "digest.docgen",
    "lane": "docs",
    "node": "targeted_research",

    # 已实现的新增字段
    "planner_session_id": "ps_xxx",        # ✅
    "confirmed_plan_id": "cp_xxx",         # ✅
    "digest_mode": "sprint",               # ✅
    "chapter_index": 1,                    # ✅
    "skill_name": "ResearchConductor",     # ✅
    "research_stage": "curate_sources",    # ✅
    "retriever_name": "bing",              # ✅（BaseRetriever 内置）
}
```

### 10.4 SkillResult metadata 提取（✅ 已实现）

`extract_skill_result_metadata()` 函数从 SkillResult 中提取关键追踪字段：

```python
# 自动提取的字段（用于日志和 LangSmith outputs）
{
    "candidate_count": 15,          # 检索候选数
    "filtered_count": 8,            # 过滤后数量
    "curated_source_count": 5,      # 质量评估后数量
    "local_source_count": 2,        # 本地源数量
    "web_source_count": 3,          # 外网源数量
    "unique_domain_count": 4,       # 唯一域名数
    "fallback_used": False,         # 是否触发降级
    "purify_used": True,            # 是否使用 LLM 提纯
    "compression_mode": "semantic",  # 压缩模式
    "retriever_names": ["bing", "local_rag"],  # 使用的检索器
    "retriever_call_count": 6,      # 检索器调用总次数
}
```

### 10.5 自定义 LangSmith Dashboard 建议（⬜ 待建立）

以下 Dashboard 建议在 Phase 5（质量调优）阶段建立：

| Dashboard 名称 | 筛选条件 | 关注指标 |
|:---|:---|:---|
| **Tier 成本分析** | `metadata.llm_tier` 分组 | 各 tier 的 token 消耗、平均延迟、调用次数 |
| **降级事件监控** | `metadata.llm_fallback_from` 非空 | 降级频率、降级原因、降级后延迟 |
| **DocGen 端到端** | `workflow=digest.docgen` | 总耗时、各节点耗时占比、章节数 |
| **检索器命中率** | `metadata.retriever_name` 分组 | 各检索器的结果数、延迟、被采用率 |
| **速成 vs 系统** | `metadata.digest_mode` 分组 | 两种模式的耗时、token、章节数对比 |
| **章节耗时分布** | `metadata.chapter_index` 分组 | 按章节看 `targeted_research` + `pedagogy_craft` 耗时 |
| **富媒体成功率** | `node=enrich_document` | image/mermaid 生成的成功/失败比 |
| **研究阶段分析** | `metadata.research_stage` 分组 | ResearchConductor 各阶段耗时占比（plan_sub_queries / curate / compress / purify） |

### 10.6 各节点追踪规范（✅ 已实现）

| 节点 | 已实现的 metadata 字段 | 说明 |
|:---|:---|:---|
| `load_context` | `chapter_count`, `has_shared_inputs`, `has_confirmed_plan` | 输入规模和状态 |
| `targeted_research` | `chapter_index`, `query_count`, `candidate_count`, `curated_source_count`, `local_hits`, `web_hits`, `purify_used`, `retriever_stats` | 完整的研究过程追踪 |
| `collect_materials` | `total_chapters`, `total_materials` | 汇聚统计 |
| `pedagogy_craft` | `chapter_index`, `word_count`, `placeholder_count`, `source_count` | 写作产出统计 |
| `collect_drafts` | `total_chapters`, `total_word_count` | 草稿汇聚统计 |
| `enrich_document` | `mermaid_count`, `image_count`, `latex_normalized` | 富媒体处理统计 |
| `inject_examine` | `question_count`, `practice_chapter_added` | 出题统计 |
| `finalize_assemble` | `doc_ids`, `built_paths`, `standalone_published` | 入库结果 |

---
