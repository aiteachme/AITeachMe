# KG Doc Sync 运行复盘：run-019de41a

来源文件：`E:\ChromeDownload\run-019de41a-9e5f-7f80-8fa0-ef5e87d94349.json`

这份导出包含 KG Doc Sync 根 run 的输入、输出、每个主要节点的 metrics，以及最终写入图谱的节点和边计数。它对应 DocGen 发布后自动触发的知识图谱同步。

## 1. 本次输入

| 字段 | 值 |
| --- | --- |
| `workflow` | `digest.kg_doc_sync` |
| `lane` | `kg_doc_sync` |
| `build_session_id` | `2eb0bfc880f745c1a0f2954d96a62a35` |
| `build_group_id` | `bb3fee466481460daf4f598a6fd04dbc` |
| `build_revision_no` | `1` |
| `doc_version_no` | `1` |
| `knowledge_doc_source` | `docgen_state` |
| `chapter_count` | 7 |
| `prefetched_sections` | 9 |

输入 Markdown 来自 DocGen 发布后的 7 章知识文档，开头是：

```text
# 人工智能概述与智能体基础
```

结构化上下文里带有 7 个章节和对应 `KnowledgeDoc` ID：

| 章 | `KnowledgeDoc` ID | 标题 |
| --- | --- | --- |
| 1 | 5 | 人工智能概述与智能体基础 |
| 2 | 6 | 问题求解与搜索策略：状态空间、盲目搜索与启发式搜索 |
| 3 | 7 | 基于知识的Agent与逻辑推理 |
| 4 | 8 | 不确定性与概率推理：贝叶斯规则与贝叶斯网络 |
| 5 | 9 | 机器学习基础与有监督学习：回归、分类及模型评估 |
| 6 | 10 | 无监督学习与人工神经网络：聚类、感知器及BP神经网络 |
| 7 | 11 | 深度学习与强化学习：CNN与Q-learning |

## 2. 本次流程实际发生了什么

```text
prepare
  读取发布 Markdown 和 docgen manifest。
  统计 markdown_chars=42766、markdown_lines=2126、heading_count=176。
  识别 chapter_context_count=7，has_docgen_manifest=true。
  |
  v
init_run
  创建 KnowledgeGraphSyncRun。
  本次 sync_run_id=2，build_revision_no=1，耗时约 10ms。
  |
  v
persist_seed_units
  尝试消费 DocGen sidecar prefetch。
  本次 prefetch_section_count=9，但复用数为 0，全部被判为 stale。
  因 non_llm_seed_skipped=true，不用本地标题/关键词造点。
  |
  v
extract
  将 7 章拆成 16 个抽取任务。
  其中 chapter_task_count=4，subsection_task_count=12，chapter_split_count=3。
  16 个任务全部走 LLM，全部成功。
  输出 123 个知识单元和 116 条 LLM 原始关系。
  耗时约 92.7 秒。
  |
  v
persist_units
  先把抽取出的 123 个 unit 写入或更新。
  created_unit_count=121，updated_unit_count=2。
  |
  v
stitch_relations
  在 LLM 原始关系之外补结构和正文显式引用关系。
  补入 stitched_edge_count=60，其中 section_local_stitch=40，mention_stitch=20。
  缝合后总边数为 181。
  |
  v
persist
  写入 123 个 active unit、181 条 active edge、304 条 source ref。
  本轮没有 deprecated unit/edge。
  |
  v
finalize
  完成 sync run，elapsed_ms=94634。
```

## 3. 输出规模

根输出：

| 指标 | 值 |
| --- | --- |
| `units` | 123 |
| `edges` | 181 |
| `section_count` | 16 |
| `successful_section_count` | 16 |
| `failed_section_count` | 0 |
| `llm_section_count` | 16 |
| `llm_error_count` | 0 |
| `source_ref_count` | 304 |
| `elapsed_ms` | 94634 |

节点类型分布：

| 类型 | 数量 |
| --- | --- |
| `concept` | 39 |
| `method` | 23 |
| `formula` | 18 |
| `remark` | 18 |
| `definition` | 14 |
| `example` | 7 |
| `theorem` | 3 |
| `proof_step` | 1 |

关系类型分布：

| 类型 | 数量 |
| --- | --- |
| `derivation` | 71 |
| `application` | 58 |
| `prerequisite` | 31 |
| `contrast` | 14 |
| `example_of` | 5 |
| `similar` | 2 |

关系来源分布：

| 来源 | 数量 |
| --- | --- |
| `llm_relation` | 96 |
| `section_local_stitch` | 40 |
| `mention_stitch` | 20 |
| `cross_section_semantic` | 15 |
| `structural_heading` | 10 |

图结构指标：

| 指标 | 值 |
| --- | --- |
| `graph_active_unit_count` | 123 |
| `graph_active_edge_count` | 181 |
| `graph_component_count` | 8 |
| `graph_largest_component_unit_count` | 68 |
| `graph_avg_degree` | 2.9431 |
| `graph_isolated_unit_count / pct` | `0 / 0` |
| `stable_anchor_count` | 123 |

整体看，KG 链路的吞吐和连通性都不错：没有失败分片，没有孤立节点，平均度也不是很低。

## 4. Prefetch 实际没有复用

DocGen enhance 后启动过 9 个 kg prefetch sidecar，但正式同步时：

| 指标 | 值 |
| --- | --- |
| `prefetch_section_count` | 9 |
| `prefetch_reused_section_count` | 0 |
| `prefetch_catchup_section_count` | 16 |
| `prefetch_stale_section_count` | 9 |
| `prefetch_failed_section_count` | 0 |

解释：发布后的最终 Markdown 和预抽取时的 section key/content hash 不一致，所以 9 个 prefetch 全部过期，正式同步补跑了 16 个 catchup section。这个行为是安全的：旧 prefetch 没有落库，也没有污染图谱，只是没有节省时间。

## 5. 数据写入

本轮实际写入：

| 表或对象 | 本次变化 |
| --- | --- |
| `KnowledgeGraphSyncRun` | 创建并完成 `sync_run_id=2`，写入 metrics |
| `KnowledgeUnit` | 121 个新增、2 个更新，最终 active 123 个 |
| `KnowledgeEdge` | 新增 181 条边，最终 active 181 条 |
| `KnowledgeGraphSourceRef` | 写入 304 条 source ref |
| graph lane runtime | 写入 revision、unit/edge changes、section metrics、prefetch metrics、连通性 metrics |

最终 report 中 `created_unit_ids={}`、`updated_unit_ids={124...}` 看起来像“全是更新”，但节点 metrics 已显示 `persist_units` 先创建 121 个、更新 2 个；final report 在第二阶段统一 upsert 时把 active units 统计成更新。这是报表聚合口径差异，不代表没有创建节点。

## 6. 本次复盘发现的关键 bug

本次导出的部分 `llm_relation` 边存在语义端点错配。例如某些边的 `description` 明显属于第 1 章“行为主义/人工智能视角”，但 `source_anchor` 却指向第 3 章或第 5 章的其它概念。

根因不是 LangSmith 展示问题，而是实现里存在一个典型合并 bug：

```text
每个 section 的 LLM candidate_id 都是局部编号，比如 n1 / n2。
fan-in 时直接 candidate_id_to_anchor.update(...)
后面的 section 会覆盖前面 section 的 n1 / n2。
早期 pending_edges 再统一解析 endpoint 时，就可能被解析到后面章节的节点。
```

本轮已同步修复：合并 `SectionExtractionPayload` 前会给每个 payload 的 candidate id 加 section namespace，并同步改写 pending_edges 里的 source/target candidate id。这样每个切片的 `n1` 只在本切片内有效，不会跨切片串线。

新增回归测试覆盖了这个场景：两个 payload 都使用 `n1 -> n2`，合并后必须分别解析到自己的 `ku_alpha -> ku_beta` 和 `ku_gamma -> ku_delta`。

## 7. 结论

KG 主流程本身跑完了：16 个 LLM 分片全成功，123 个节点、181 条边、304 条 source ref 都写入完成，图上没有孤立节点。

但这次复盘发现的 candidate id 串线是重大质量问题，因为它会让边的端点跨章节错配。代码已修，后续需要重新跑一次 KG 同步，才能把已经写入的错误 `llm_relation` 边刷新掉。
