# 06. Digest 统一构建实现说明

## 1. 当前实现落点

统一构建当前已经落在以下目录：

```
backend/app/workflows/digest/
├── shared/      # shared prepare
├── docs/        # doc lane
├── kg/          # kg lane
├── curriculum/  # curriculum lane
└── unified/     # 顶层统一协调
```

说明：

- 当前真相路径是 `digest/unified/`，不是旧的 `digest/build/`。
- `/knowledge/build` 现在内部只走 unified build。

---

## 2. 已经实现的关键点

### 2.1 Shared Prepare

已实现：

- 并发读取 markdown
- rule-based normalize
- section split
- stable `digest_chunk_uid`
- `FastTopicHints`
- markdown-first `AssetRegistry`

当前约束：

- 不再读取不存在的 `RawFile.asset_name_prefix`
- `image_refs` 直接来自 markdown
- `asset_dir` 直接来自 `RawFile.asset_dir`

### 2.2 Doc Lane

已实现：

- 从 unified session 加载 shared inputs
- `outline_reduce` 会短暂等待 early `TopicAnchorSnapshot`
- 有 anchors 时，章节骨架优先按 topic / concept / method 语义锚点组织
- 没有 anchors 时，优先采用 LLM 全局大纲；关键词 theme 只保留为兜底
- 章节 draft / review 并发
- 按 `chunk_uids` 收集章节相关图片提示
- `finalize_assemble` 只写 staging
- 为后续 curriculum-aligned final book 保留 section / chunk / image 级元数据

当前语义：

- doc lane 不再直接 publish live docs
- 文档真正发布延后到 unified `publish_outputs`
- doc lane 的中间稿只负责生成教学语义材料；最终对外 docs 会在 curriculum 发布后重新组装

### 2.3 KG Lane

已实现：

- prepare 直接消费 unified canonical chunks
- extract 并发跑
- chapter priors 作为 soft hint 注入
- resolve 使用批量 embedding
- finalize 使用 `ClusteredCandidate.representative`
- 发布 `TopicAnchorSnapshot`

### 2.4 Curriculum

已实现：

- derive units
- derive theme tree
- derive prereq DAG
- publish curriculum snapshot

当前统一约束：

- 如果没有发布 snapshot，unified build 直接判失败

当前新增职责：

- curriculum/theme tree 会反向驱动最终 docs 重建
- 最终 docs 以 theme tree chapter + teaching unit 为结构骨架
- 输出目标是“老师整理后的知识讲义”，而不是 doc lane 初稿或 theme tree 节点镜像

### 2.5 Unified Publish

已实现：

- doc lane staging 输出写 `_build/`
- curriculum 完成后执行 `rebuild_docs`
- unified 在 curriculum 成功后统一 publish
- publish 同时更新：
  - `knowledge_markdowns/chapter_*.md`
  - `knowledge_markdowns/merged_knowledge_base.md`
  - `knowledge_markdowns/manifest.json`
  - `knowledge_doc`

---

## 3. 当前并发模型

统一构建当前默认走异步并发：

- unified 顶层：`asyncio.gather(doc_lane, kg_lane)`
- doc lane：章节级并发
- kg lane：chunk 级 extract 并发
- LLM / embedding：统一 semaphore 限流

注意：

- `rebuild_docs` 不参与顶层并行，它位于 curriculum 之后，负责把前面两条 lane 的成果收束成最终知识文档
- 因此最终 live docs 的结构语义，以 curriculum / theme tree / teaching units 为准

配置来源：

- `llm_concurrency_limit`
- `docgen_max_parallel_chapters`
- `docgen_io_parallelism`

---

## 4. 当前成功条件

一次 `/knowledge/build` 成功，必须同时满足：

- shared prepare 成功
- doc lane 成功
- kg lane 成功
- curriculum 发布了 snapshot
- staged docs 已成功 publish

如果只生成了 docs，但 curriculum / overview 还没 ready，则本次 build 视为失败。

---

## 5. 当前日志观察点

统一构建排障时，应优先看这些日志：

- `docgen_outline_planning_completed` 的 `outline_source`
- `shared_prepare_started`
- `shared_prepare_completed`
- `unified_parallel_lanes_started`
- `unified_parallel_lanes_completed`
- `kg_extract_started`
- `unified_curriculum_started`
- `unified_curriculum_completed`
- `unified_publish_started`
- `unified_publish_completed`

如果日志停在 docs 已 staging，但没有 `unified_publish_completed`，说明主链还没有真正切 live。

---

## 6. 当前仍需继续验证的点

这部分不是架构缺口，而是运行验证清单：

1. 单文件 PDF 的整轮 unified build 时延
2. KG lane 在真实样本上的 extract / resolve 并发收益
3. curriculum 在 `impact_set` 较大时的收口时间
4. `/knowledge/docs` 与 `/knowledge/overview` 的 live 切换时序

---

## 7. 结论

当前实现已经明确转向：

- 一个入口
- 一次 shared prepare
- 两条并行 lane
- 一个 curriculum 收口
- 一次 docs 重建
- 一次统一 publish

后续继续优化时，应继续沿着这条主干推进，不再回到”doc 和 graph 两套分裂后台任务”的旧设计。

---

## 8. 学科识别与上下文增强（新增）

### 8.1 SubjectProfile

在 shared prepare 阶段新增学科识别，产出 `SubjectProfile`：

- 从 DB 读取 `Subject.name` / `Subject.description`
- 从内容信号（关键词频率、公式密度、题目密度）推断学科领域和子领域
- 检测材料类型（教材 / 试卷 / 讲义 / 混合）
- 估算难度级别
- 提取核心主题列表
- 生成教学风格指导（`teaching_style_hint`）

实现文件：`shared/subject_recognizer.py`

### 8.2 上下文注入

`SubjectProfile.build_context_string()` 生成结构化学科描述，注入到：

| 调用点 | 新增参数 |
|--------|----------|
| `generate_global_outline()` | `subject_context` |
| `write_chapter()` | `subject_context` + `teaching_style_hint` |
| `review_chapter()` | `subject_context` |
| `extract_candidates()` | `subject_context`（通过 KG prompt 模板） |

### 8.3 效果预期

- 大纲规划：章节标题使用学科专业术语，顺序符合学科教学逻辑
- 章节撰写：内容深度匹配学科特点，公式/代码/实验等表达方式自适应
- 审阅检查：专业术语准确性纳入质检维度
- KG 抽取：实体命名和分类更贴合学科体系

---

## 9. 模型分级与重排序配置（新增）

### 9.1 模型分级

`config.py` 新增：

- `llm_model_light`：轻量任务（大纲规划、审阅、元数据提取）
- `llm_model_extract`：抽取任务（KG 实体/关系抽取）

`model_router.py` 自动按 TaskType 选择对应模型，未配置时回退到 `llm_model`。

### 9.2 RAG 重排序

`.env.example` 新增：

- `RAG_RERANK_MODEL`：重排序模型（如 gte-rerank）
- `RAG_RERANK_API_KEY` / `RAG_RERANK_BASE_URL`：独立配置
- `RAG_RERANK_TOP_K`：重排序后保留数量

`config.py` 已添加对应字段，后续 RAG 检索链可直接读取使用。
