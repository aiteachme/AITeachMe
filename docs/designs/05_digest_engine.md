# 05. Digest 引擎

## 1. 文档目标

Digest 负责把 ingest 已解析好的材料，统一构建为三类结果：

- 面向用户的知识文档
- 面向系统的知识图谱
- 面向教学组织的 curriculum / theme tree / prereq DAG

当前对外已经不再把这三条链路暴露成多个入口，而是统一收口到一个 build。

---

## 2. 当前对外接口

| 接口 | 作用 |
| --- | --- |
| `POST /knowledge/build` | 触发 unified digest build |
| `POST /knowledge/docs` | 读取当前已发布知识文档 |
| `POST /knowledge/overview` | 读取当前已发布 curriculum / theme tree / prereq DAG / 图谱聚合结果 |

接口约束：

- `/knowledge/build` 仍然是唯一构建入口。
- 不新增 digest 专用新 API。
- docs 和 overview 都只读 live 已发布结果，不读构建中间态。

---

## 3. 当前内部结构

Digest 现在的内部结构分成四层：

1. `shared prepare`
2. `doc lane`
3. `kg lane`
4. `curriculum lane`

但这些子流程不再对外独立暴露；真正的主入口是 unified build 顶层协调器。

### 3.1 顶层主干

当前统一主干是：

`shared prepare -> doc/kg 并行 -> consistency -> repair -> curriculum -> publish -> cleanup`

设计约束：

- shared prepare 只执行一次。
- doc / kg 使用同一批 canonical chunk identity。
- docs 先写入 staging，只有统一构建成功后才切 live。
- 如果 curriculum 没有成功发布 snapshot，则本次 unified build 视为失败。

---

## 4. Shared Prepare

### 4.1 输入

- `raw_file.markdown_path`
- `raw_file.asset_dir`

### 4.2 产出

- `SourcePacket`
- `SectionPacket`
- `ChunkIdentityMap`
- `FastTopicHints`
- `AssetRegistry`

### 4.3 关键语义

- `SourcePacket` 不再依赖 `asset_name_prefix` 持久字段。
- 图片资产的章节级关联真源是 markdown 内的图片引用路径。
- `AssetRegistry` 只做轻量增强：
  - 文件存在性校验
  - `page_number` / `asset_type` / `file_size` 补充
- shared prepare 不调 LLM，只做规则级处理和并发 I/O。

---

## 5. Doc Lane

### 5.1 输入

- `SharedInputs.section_packets`
- `digest_chunk_uid`
- markdown 中已经出现的 `image_refs`
- 可选的 `TopicAnchorSnapshot`

### 5.2 产出

- staging 目录中的 chapter markdown
- staging 目录中的 merged markdown
- chapter metadata

### 5.3 当前实现原则

- 章节写作和审校允许并发。
- 每章只引用命中的 `chunk_uids` 对应的图片，不再按整文件粗放塞图。
- doc lane 自己不再负责 live publish。
- doc lane 的 `finalize` 节点只做 staging，不做正式发布。

---

## 6. KG Lane

### 6.1 输入

- unified materialize 后的 canonical `DocumentChunk`
- `digest_chunk_uid`
- 可选的 `ChapterPriors`

### 6.2 产出

- `knowledge_node`
- `knowledge_revision`
- `knowledge_alias`
- `knowledge_edge`
- `edge_revision`
- `evidence_link`
- `TopicAnchorSnapshot`
- `ImpactSet`

### 6.3 当前实现原则

- extract 走异步并发，受全局 `llm_concurrency_limit` 限流。
- resolve 使用批量 embedding，不走单候选串行慢路径。
- finalize 使用 `ClusteredCandidate.representative` 和 `digest_chunk_uid/source_chunk_ids`。

---

## 7. Curriculum Lane

### 7.1 输入

- 当前图谱状态
- KG 的 `ImpactSet`

### 7.2 产出

- `teaching_unit*`
- `theme_tree*`
- `prereq_dag*`
- `curriculum_snapshot`

### 7.3 当前统一成功条件

以下条件同时满足，本次 `/knowledge/build` 才算成功：

- docs 已发布到 live
- 图谱主结果已完成
- `curriculum_snapshot` 已发布
- `/knowledge/overview` 能读到当前 theme tree / prereq DAG / curriculum

如果只生成了文档，但 snapshot 没发布，则 unified build 应视为失败，不允许切 live。

---

## 8. 发布语义

当前 digest 的发布语义如下：

- 构建开始时清理 staging
- doc lane 只写 `_build/`
- unified 在 curriculum 成功后统一执行 publish
- publish 内容包括：
  - `knowledge_markdown/chapter_*.md`
  - `knowledge_markdown/merged_knowledge_base.md`
  - `knowledge_markdown/manifest.json`
  - `knowledge_doc` published 记录

这条规则的目标是避免出现“文档已经更新，但 overview 还是旧的或为空”的半成品状态。

---

## 9. 当前并发模型

Digest 当前默认采用异步并发，而不是单线程串行执行：

- unified 顶层：`asyncio.gather(doc_lane, kg_lane)`
- doc lane：章节 draft / review 并发
- kg lane：chunk extract 并发
- 全局 LLM 调用：统一走 semaphore 限流

说明：

- 对 LLM / embedding 这类网络调用，主模型是 async + semaphore。
- 不引入额外线程池去并发 LLM 请求。
- 线程只用于必要的本地文件 I/O 包装。

---

## 10. 当前结论

Digest 的当前真相不再是“docgen、graph、curriculum 三套彼此独立的后台任务”，而是：

- 一个统一入口
- 一次 shared prepare
- 两条并行 lane
- 一个 curriculum 收口
- 一次统一 publish

理解和排障时，应优先以 unified build 主链为中心，而不是按旧的分裂流程理解。
