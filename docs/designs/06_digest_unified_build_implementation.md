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
- 章节 draft / review 并发
- 按 `chunk_uids` 收集章节相关图片提示
- `finalize_assemble` 只写 staging

当前语义：

- doc lane 不再直接 publish live docs
- 文档真正发布延后到 unified `publish_outputs`

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

### 2.5 Unified Publish

已实现：

- doc lane staging 输出写 `_build/`
- unified 在 curriculum 成功后统一 publish
- publish 同时更新：
  - `knowledge_markdown/chapter_*.md`
  - `knowledge_markdown/merged_knowledge_base.md`
  - `knowledge_markdown/manifest.json`
  - `knowledge_doc`

---

## 3. 当前并发模型

统一构建当前默认走异步并发：

- unified 顶层：`asyncio.gather(doc_lane, kg_lane)`
- doc lane：章节级并发
- kg lane：chunk 级 extract 并发
- LLM / embedding：统一 semaphore 限流

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
- 一次统一 publish

后续继续优化时，应继续沿着这条主干推进，不再回到“doc 和 graph 两套分裂后台任务”的旧设计。
