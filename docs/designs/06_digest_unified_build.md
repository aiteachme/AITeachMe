# 06. Digest 统一构建设计

## 1. 设计目标

统一构建的目标不是把所有节点硬塞进一张超级图，而是把 digest 真正收口成一个主干：

- `/knowledge/build` 仍然是唯一入口
- shared prepare 只执行一次
- doc / kg 真并行
- docs / graph / curriculum 使用同一批 canonical chunk identity
- 只有 docs 和 overview 都 ready，才切 live

---

## 2. 当前主链

```
knowledge/build
  -> run_unified_digest_build()
  -> prepare_shared
  -> materialize canonical chunks
  -> asyncio.gather(doc_lane, kg_lane)
  -> consistency
  -> bounded_repair
  -> derive_curriculum
  -> publish_outputs
  -> cleanup
```

说明：

- `doc_lane` 和 `kg_lane` 都是 async 并发执行。
- `publish_outputs` 必须晚于 curriculum snapshot 发布。
- 失败时只回收 staging / session，不污染 live docs。

---

## 3. Shared Prepare

### 3.1 SourcePacket

```python
class SourcePacket(BaseModel):
    file_id: int
    filename: str
    filetype: str
    markdown_path: str
    asset_dir: str
    normalized_content: str
    char_count: int
    has_formulas: bool
    has_tables: bool
    has_images: bool
    image_refs: list[str]
```

关键点：

- 不再依赖 `RawFile.asset_name_prefix`。
- `asset_dir` 直接来自 `RawFile.asset_dir`，为空时回退到 subject 标准 assets 目录。
- `image_refs` 直接从 markdown 中提取。

### 3.2 SectionPacket

```python
class SectionPacket(BaseModel):
    digest_chunk_uid: str
    source_file_id: int
    source_filename: str
    chunk_index: int
    title: str
    header_path: str
    level: int
    normalized_content: str
    preview: str
    char_count: int
    formula_refs: list[str]
    question_block_count: int
    header_candidates: list[str]
    image_refs: list[str]
```

### 3.3 AssetRegistry

当前 `AssetRegistry` 是 markdown-first 设计：

- markdown 图片引用是章节级资产关联真源
- registry 只做补充元数据和轻量校验
- 不再以目录扫描和前缀过滤作为主逻辑

```python
class AssetItem(BaseModel):
    filename: str
    file_id: int
    page_number: int | None
    asset_type: str
    file_size: int
    ocr_available: bool
```

---

## 4. Canonical Materialization

shared prepare 之后，统一先把 canonical sections 物化为：

- `document`
- `document_chunk`
- `chunk_embeddings`

约束：

- `DocumentChunk.digest_chunk_uid` 是跨 lane 真正共享的材料 identity
- `DocumentChunk.build_session_id` 记录本次 unified build session
- KG prepare 不再回退到 legacy chunk materialization

---

## 5. Doc Lane

doc lane 的当前职责：

- 从 unified session 读取 `SharedInputs`
- 做必要的教学性清理
- 规划章节
- 并发生成章节草稿
- 并发审校章节
- 提取 metadata
- 把 chapter markdown 写到 staging

关键约束：

- 每章图片提示来自该章命中的 `chunk_uids -> image_refs`
- doc lane 只写 staging，不直接 publish
- graph 提供的 `TopicAnchorSnapshot` 只作为 soft review hint

---

## 6. KG Lane

kg lane 的当前职责：

- 从 unified materialized chunks 读取 canonical chunk ids
- 并发 extract
- cluster
- 批量 embedding + resolve nodes
- resolve edges
- impact analysis
- finalize graph
- 发布 `TopicAnchorSnapshot`

关键约束：

- extract 并发度受 `min(10, llm_concurrency_limit, chunk_count)` 限制
- resolve 必须批量 embedding，不再逐候选串行调 embedding
- finalize 使用 `ClusteredCandidate.representative`

---

## 7. Curriculum 收口

curriculum 是 unified build 的硬收口条件，不再是“可有可无的后续任务”。

统一要求：

- curriculum 必须发布 `curriculum_snapshot`
- 如果没有 snapshot，则 unified build 失败
- `/knowledge/overview` 的可读性是 build 成功条件的一部分

---

## 8. Publish 语义

当前发布语义明确分成两步：

### 8.1 Stage

doc lane 的 finalize 只负责：

- 写 `_build/chapter_*.md`
- 写 `_build/merged_knowledge_base.md`
- 产出 chapter metadata

### 8.2 Publish

unified `publish_outputs` 负责：

- 把 `_build` 中的 chapter / merged markdown 切到 live
- 写 `manifest.json`
- 重建 `knowledge_doc` published 记录

只有 curriculum 成功后，publish 才允许执行。

---

## 9. 并发设计

当前统一构建的并发模型如下：

- 顶层：`asyncio.gather(doc_lane, kg_lane)`
- doc lane：章节写作和审校并发
- kg lane：chunk extract 并发
- 全局：LLM / embedding 调用走统一 semaphore

这意味着总耗时目标是：

`shared_prepare + max(doc_lane, kg_lane) + curriculum + publish`

而不是：

`shared_prepare + doc_lane + kg_lane + curriculum`

---

## 10. 设计结论

统一构建的当前真实设计可以概括为四句话：

1. markdown 图片引用是资产关联真源
2. doc / kg 共享同一批 canonical chunks
3. docs 必须先 staging，再统一 publish
4. curriculum snapshot 是 build 成功的硬条件
