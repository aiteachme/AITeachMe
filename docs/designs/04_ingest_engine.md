# 04. Ingest 引擎

## 1. 目标与职责

Ingest 负责把原始资料转换成后续所有引擎都能稳定消费的"材料层"。

当前它的职责是：

- 接收上传文件
- 做轻量分类和解析器路由
- 生成稳定 Markdown
- 提取图片 / 附件到共享 `assets/`
- 对提取图片做 OCR / vision 补强
- 把解析状态写回 `raw_file`
- 为下游 `document / document_chunk / chunk_embeddings` 做好准备

Ingest 不负责直接产出知识图谱或知识文档，它只负责把材料打磨到可消费状态。

---

## 2. 当前实现落点

| 层          | 当前主模块                               |
| ----------- | ---------------------------------------- |
| 前端页面    | `frontend/src/pages/UploadPage.tsx`      |
| API         | `backend/app/api/files.py`               |
| service     | `backend/app/services/file_service.py`   |
| workflow    | `backend/app/workflows/ingest/*`         |
| 路径 helper | `backend/app/services/upload_support.py` |
| 核心表      | `raw_file`                               |

---

## 3. 核心问题：当前管线太慢

### 3.1 现状分析

当前 ingest 管线是一条**完整同步链路**：

```
load_raw_file → compute_fingerprint → classify_file → plan_parse → parse_file → finalize_success
```

其中 `parse_file` 内部会依次执行：

1. **传统解析**（pymupdf4llm / pymupdf_native / markitdown）→ 生成原始 Markdown
2. **Markdown 规范化**（`canonicalize_markdown`）→ 统一图片引用、清理格式
3. **LLM Vision OCR 补强**（`enhance_markdown_with_asset_ocr`）→ 对提取的图片逐张调 LLM 视觉模型
4. **PDF 页面级 OCR 兜底**（`enhance_pdf_markdown_with_page_fallback`）→ 对低文字密度页面再做整页 OCR

步骤 3 和 4 是调用 LLM 多模态 API 的，**每张图片一次网络往返**，这是整个管线最慢的环节。一个 30 页的 PDF 如果有 20 张图片，OCR 阶段可能需要 30-60 秒甚至更久，用户在前端会一直看到 "解析中" 的状态。

### 3.2 优化思路

**核心策略：前台快速出结果，后台慢慢做深度增强。**

将 ingest 拆成两个阶段：

| 阶段 | 名称 | 前台可见 | 是否调 LLM | 预期耗时 |
|------|------|---------|-----------|---------|
| Phase 1 | **快速解析**（Fast Parse） | ✅ 完成即展示 | ❌ 不调 LLM | 2-8 秒 |
| Phase 2 | **深度增强**（Deep Enhance） | 后台静默 | ✅ 调 LLM Vision OCR | 20-90 秒 |

- 用户上传后，Phase 1 用纯传统方法快速出 Markdown，前端立即展示解析结果
- Phase 2 在后台异步执行 LLM 视觉增强，完成后静默更新 Markdown
- Phase 2 完成后才标记 `READY_FOR_DIGEST`，作为 Digest 引擎的前置条件

---

## 4. 两阶段 Pipeline 详细设计

### 4.1 Phase 1：快速解析（Fast Parse）

**目标**：不调任何 LLM，用纯传统方法在几秒内出 Markdown。

**LangGraph 节点流**：

```
load_raw_file → compute_fingerprint → classify_file → plan_parse → fast_parse_file → finalize_fast_parse
```

**`fast_parse_file` 节点内部流程**：

```
1. 根据 parser_chain 选择传统解析器
   - PDF:  pymupdf4llm / pymupdf_native / markitdown
   - DOCX: docx_native / markitdown
   - PPTX: python_pptx_native / markitdown
   - 图片: 跳过 Phase 1，直接全量走 Phase 2（图片必须 LLM）
   - 文本: text_native（直接完成，无需 Phase 2）

2. 执行传统解析 → 得到原始 Markdown

3. 执行 canonicalize_markdown 规范化
   - 统一图片引用为 ../assets/<name>
   - 提取内嵌图片到 assets/

4. 图片提取（无 OCR）
   - supplement_pdf_images → 提取 embedded images + drawings 到 assets/
   - 不调 LLM，不做 OCR，仅保存图片文件

5. 写入 raw_markdown/<file_id>.md（快速版本）
```

**使用的包**：

| 包 | 用途 | 是否调 LLM |
|---|------|-----------|
| `pymupdf` (fitz) | PDF 原生文字提取 + 图片提取 + drawing 渲染 | ❌ |
| `pymupdf4llm` | PDF → Markdown（保留表格/公式结构） | ❌ |
| `markitdown` | 通用文档 → Markdown 转换 | ❌ |
| `python-docx` | DOCX 原生解析 | ❌ |
| `python-pptx` | PPTX 原生解析 | ❌ |

**`finalize_fast_parse` 节点行为**：

- `raw_file.status = completed`
- `raw_file.ingest_status = FAST_PARSED`（新状态）
- `raw_file.markdown_path` 指向快速版 Markdown
- 发布 `IngestFileFastParsedEvent`
- **前端收到此事件或轮询到此状态后，即可展示解析结果**
- **此时后台自动触发 Phase 2**

### 4.2 Phase 2：深度增强（Deep Enhance）

**目标**：后台异步调 LLM，对 Phase 1 的产物做 OCR 增强。

**触发方式**：Phase 1 的 `finalize_fast_parse` 节点成功后，后台自动 dispatch Phase 2 任务（`asyncio.create_task`）。

**LangGraph 节点流**：

```
load_enhance_context → deep_enhance_file → finalize_deep_enhance
```

**`deep_enhance_file` 节点内部流程**：

```
1. 读取 Phase 1 产出的 raw_markdown/<file_id>.md

2. enhance_markdown_with_asset_ocr（已有逻辑）
   - 对 assets/ 下的图片逐张调 LLM Vision OCR
   - 替换占位符或追加 OCR appendix
   - 使用 semaphore 控制并发

3. enhance_pdf_markdown_with_page_fallback（已有逻辑，仅 PDF）
   - 对低文字密度页面做整页 Vision OCR
   - 补充格式化公式（LaTeX）

4. 覆写 raw_markdown/<file_id>.md（增强版本）
```

**使用的包**：

| 包 | 用途 | 是否调 LLM |
|---|------|-----------|
| `litellm` | 统一调用 LLM Vision API（qwen-vl-max 等） | ✅ |
| `pymupdf` (fitz) | 渲染低密度 PDF 页面为 PNG 供 OCR | ❌ |

**`finalize_deep_enhance` 节点行为**：

- `raw_file.ingest_status = READY_FOR_DIGEST`
- 发布 `IngestFileReadyForDigestEvent`（已有事件）
- **至此 Digest 引擎才被允许消费该文件**

### 4.3 IngestStatus 状态机变更

```
旧状态流:
  PENDING → CLASSIFYING → PARSING → VALIDATING → READY_FOR_DIGEST
                                                 ↘ FAILED

新状态流:
  PENDING → CLASSIFYING → PARSING → FAST_PARSED → ENHANCING → READY_FOR_DIGEST
                                   ↗ (前端可展示)              ↘ ENHANCE_FAILED
                                                 ↘ FAILED

状态说明:
  PENDING          文件已上传，等待解析
  CLASSIFYING      正在分类文件类型
  PARSING          Phase 1 快速解析中
  FAST_PARSED      Phase 1 完成，前端可展示，后台正在启动 Phase 2
  ENHANCING        Phase 2 LLM 深度增强中
  READY_FOR_DIGEST Phase 2 完成，可进入 Digest
  ENHANCE_FAILED   Phase 2 失败（Phase 1 结果仍可用，不影响展示）
  FAILED           Phase 1 失败（整体失败）
```

> **关键设计**：`ENHANCE_FAILED` 不等于整体失败。即使 Phase 2 失败，Phase 1 的 Markdown 仍然可用，用户仍然可以阅读、对话。但 Digest 引擎应标记该文件为"OCR 未完成"，后续可重试。

### 4.4 事件体系变更

| 事件 | 触发时机 | 新增/已有 |
|------|---------|---------|
| `IngestParseRequestedEvent` | 用户触发解析 | 已有 |
| `IngestFileClassifiedEvent` | 分类完成 | 已有 |
| `IngestFileFastParsedEvent` | Phase 1 完成 | **新增** |
| `IngestFileEnhanceStartedEvent` | Phase 2 开始 | **新增** |
| `IngestFileParsedEvent` | Phase 2 中 OCR 完成 | 已有（语义保留） |
| `IngestFileReadyForDigestEvent` | Phase 2 完成 | 已有 |
| `IngestFileEnhanceFailedEvent` | Phase 2 失败 | **新增** |
| `IngestFileParseFailedEvent` | Phase 1 失败 | 已有 |

---

## 5. Ingest → Digest 阻塞关系

### 5.1 阻塞规则

Digest 引擎**必须等待 Ingest 的 Phase 2 完成**后才能开始消费文件。具体来说：

- Digest 在启动 `prepare_chunk_ids_for_files` 时，应检查每个 `raw_file.ingest_status`
- 只有 `ingest_status == READY_FOR_DIGEST` 的文件才能进入 Digest 管线
- `FAST_PARSED` 或 `ENHANCING` 状态的文件应被跳过或等待

### 5.2 实现方式

在 `digest/kg/support.py::prepare_chunk_ids_for_files` 的入口增加前置检查：

```python
# 伪代码
for raw_file in target_files:
    if raw_file.ingest_status != IngestStatus.READY_FOR_DIGEST:
        if raw_file.ingest_status == IngestStatus.ENHANCE_FAILED:
            logger.warning("file_enhance_failed_using_fast_parse", file_id=raw_file.id)
            # 允许降级使用 Phase 1 结果，但标记 quality_flag
        else:
            raise IngestNotReadyError(raw_file.id, raw_file.ingest_status)
```

### 5.3 用户可见的交互流程

```
用户上传文件
  ↓
前端显示 "解析中..."（Phase 1: 2-8 秒）
  ↓
Phase 1 完成 → 前端立即展示 Markdown + 图片预览
  ↓ 同时
后台启动 Phase 2（用户无感知）
  ↓
Phase 2 完成 → 文件可进入 Digest 流程
  ↓
用户点击 "构建知识图谱" → 系统检查所有文件是否 READY_FOR_DIGEST
  ↓ 如果有文件还在 ENHANCING
前端提示 "部分文件正在深度解析中，请稍等..." 或允许用户选择跳过增强
```

---

## 6. 当前本地正式产物

单个原始文件解析完成后，会得到：

- `data/<subject>/raw/<raw_file_id>.<ext>`
- `data/<subject>/raw_markdown/<raw_file_id>.md`
- `data/<subject>/assets/<asset_name_prefix>__*.png|jpg|...`

这里最重要的变化是：

1. `raw_markdown/` 取代旧 `markdown/`
2. `assets/` 现在是整个 subject 共享的扁平目录，不再使用 `assets/<file_id>/`
3. Phase 1 和 Phase 2 写的都是同一个 `raw_markdown/<file_id>.md`，Phase 2 是对 Phase 1 产物的增强覆写

---

## 7. 共享 `assets/` 的目录策略

当前实现采用：

- 一个 subject 只有一个 `assets/`
- 每个原始文件用 `asset_name_prefix` 作为命名前缀

示例：

`linear_algebra__file_123abc__p2_img1_9fcd2a1b8e.png`

这样做的目的是：

- 保持所有 Markdown 都是一级目录
- 让 `raw_markdown/` 和 `knowledge_markdown/` 都能用同一套相对路径
- 删除单个文件时可以按前缀清理本文件图片，而不会误删整科目 assets

---

## 8. Markdown 与图片引用规则

Ingest 统一把 Markdown 里的图片引用规范成：

`../assets/<flattened_asset_name>`

这条规则同时适用于：

- `raw_markdown/*.md`
- `knowledge_markdown/*.md`

当前所有 Markdown 文件都必须保持一级目录，避免多层目录导致图片相对路径混乱。

---

## 9. OCR / Vision 补强策略（Phase 2 专属）

### 9.1 为什么必须补这一步

仅靠传统解析器，经常会得到这类内容：

`picture [176 x 30] intentionally omitted`

这对公式题、试卷扫描件、图表型资料几乎不可用。

### 9.2 当前实现

在 Phase 2 的 `deep_enhance_file` 中做两类增强：

1. **Asset 级 OCR**
   针对提取出来的图片做 vision OCR，再回填到 Markdown。
2. **页面级 OCR 兜底**（仅 PDF）
   适用于扫描 PDF 页，对低文字密度页渲染成 PNG 再做整页 vision OCR。

asset OCR 的效果包括：

- 把 `intentionally omitted` 之类占位符替换成真实图片引用 + OCR 文本
- 把图片 OCR 内容补进 Markdown
- 在没有占位符时，按需追加 `Extracted Image OCR` 补充段落

### 9.3 设计思路

这套思路和 MinerU 的"Markdown + sidecar images"方向是一致的：

- 正文是 Markdown
- 图片作为旁路资产单独落盘
- Markdown 只保留稳定引用

不同点在于：

- MinerU 常按一次输出目录组织 sidecar 图片
- 我们当前按 subject 共享 `assets/`，再用 `asset_name_prefix` 做确定性隔离

### 9.4 OCR 优化记录

#### PDF 分类器优化

- 新增 `formula_heavy_pdf` 分类，专门识别数学试卷类文档
- 增加公式密集页检测：`drawing_count >= 3 && char_count < 500`
- 计算 `formula_ratio`（公式密集页占比）

#### LLM Vision OCR Prompt 优化

- 中文 prompt 更详细、更专业
- 明确要求：行内公式 `$...$`、独立公式 `$$...$$`、标准 LaTeX 语法
- 检测图片太小（< 100 bytes）和拒绝响应模式

#### 解析策略调优

针对 `formula_heavy_pdf` 的专门策略：

```python
options.asset_image_limit = 32          # 大幅提升图片提取上限
options.asset_vision_ocr_limit = 24     # 强化 OCR 预算
options.skip_image_supplement = False   # 不跳过图片补充
options.enable_page_vision_ocr = False  # 不做整页 OCR
options.timeout_s = 150                 # 延长超时时间
```

#### OCR 模型配置

- 支持单独配置 `OCR_MODEL`、`OCR_API_KEY`、`OCR_BASE_URL`
- 未配置时自动回退到 LLM 配置
- 直接使用 `litellm.acompletion` 调用

---

## 10. LangGraph 节点与表写入（新架构）

### 10.1 Phase 1 节点

#### `build_load_raw_file_node`（不变）

读取 `raw_file` 记录，派生路径。

#### `build_compute_fingerprint_node`（不变）

计算 SHA256 和文件大小。

#### `build_classify_file_node`（不变）

写表 `raw_file`：`estimated_pages`、`detected_language`、`classification_result`、`ingest_status`。

#### `build_plan_parse_node`（不变）

根据分类结果规划解析策略。

#### `build_fast_parse_file_node`（**新，替代原 `parse_file`**）

只执行传统解析 + 规范化 + 图片提取。**不调 LLM**。

写文件：`raw_markdown/<file_id>.md`、`assets/<prefix>__*.png|jpg|...`

#### `build_finalize_fast_parse_node`（**新，替代原 `finalize_success`**）

写表 `raw_file`：`status=completed`、`ingest_status=FAST_PARSED`、`markdown_path`、`asset_dir` 等。
发布 `IngestFileFastParsedEvent`。
**自动触发 Phase 2**。

### 10.2 Phase 2 节点

#### `build_load_enhance_context_node`（**新**）

读取 Phase 1 的产物路径和 parse_plan，准备增强上下文。

#### `build_deep_enhance_file_node`（**新**）

执行 `enhance_markdown_with_asset_ocr` + `enhance_pdf_markdown_with_page_fallback`。
覆写 `raw_markdown/<file_id>.md`。

#### `build_finalize_deep_enhance_node`（**新**）

写表 `raw_file`：`ingest_status=READY_FOR_DIGEST`、更新 `parse_metadata`（含 OCR 统计）。
发布 `IngestFileReadyForDigestEvent`。

---

## 11. 速度预期

| 场景 | Phase 1 预期耗时 | Phase 2 预期耗时 | 用户感知等待 |
|------|----------------|----------------|------------|
| 10 页普通 PDF（文字为主） | 1-3 秒 | 5-15 秒 | **1-3 秒** |
| 30 页 PDF（含 20 张图） | 3-6 秒 | 30-60 秒 | **3-6 秒** |
| 数学试卷 PDF（公式密集） | 3-8 秒 | 40-90 秒 | **3-8 秒** |
| 50 页 DOCX | 2-5 秒 | 10-30 秒 | **2-5 秒** |
| 100 页 PPTX | 5-10 秒 | 15-40 秒 | **5-10 秒** |
| 纯文本 / Markdown | <1 秒 | 无 Phase 2 | **<1 秒** |
| 单张图片 | 无 Phase 1 | 3-8 秒 | **3-8 秒**（必须等 LLM） |

**核心改进**：用户感知的等待时间从原先的 Phase 1 + Phase 2 总和，降低到仅 Phase 1 的时间。

---

## 12. 前端 UI 变更要点

### 12.1 需要删除的内容

- 当前 UploadPage 上展示 ingest 解析效果的调试 UI（后续删除）

### 12.2 需要调整的交互

- Phase 1 完成后，前端应展示 Markdown 预览（作为解析结果）
- 如果 Phase 2 仍在进行中，可以在文件卡片上显示一个小标识（如"深度解析中..."）
- Phase 2 完成后标识消失，文件卡片显示完整状态
- 整体 UI 风格需要与当前系统画风、动效保持一致

---

## 13. 与 Digest 的桥接关系

Ingest 的 Phase 2 结束后，下游并不是直接消费 `raw_file` 本身，而是消费：

`raw_file.markdown_path -> document -> document_chunk -> chunk_embeddings`

这个桥接发生在：

`backend/app/workflows/digest/kg/support.py::prepare_chunk_ids_for_files`

所以当前的正式材料层应理解为：

`RawFile -> raw_markdown / assets -> Document / DocumentChunk`

Digest 引擎在消费之前必须确认 `ingest_status == READY_FOR_DIGEST`（或降级接受 `ENHANCE_FAILED`）。

---

## 14. 后续优化方向

1. **智能 OCR 预算分配**
   - 根据图片复杂度动态调整 OCR 优先级
   - 优先 OCR 包含公式的图片

2. **OCR 结果缓存**
   - 对相同图片的 OCR 结果做缓存
   - 避免重复调用

3. **批量 OCR**
   - 支持批量发送图片到 OCR API
   - 提升并发效率

4. **OCR 质量评估**
   - 自动评估 OCR 结果质量
   - 对低质量结果重试或标记

5. **多模型融合**
   - 对关键图片使用多个模型 OCR
   - 融合结果提升准确率

6. **Phase 2 重试机制**
   - `ENHANCE_FAILED` 状态的文件支持手动/自动重试
   - 前端提供重试按钮

---

## 15. 总结

Ingest 引擎的核心价值是把资料稳稳转换成统一材料层。新的两阶段架构通过分离"快速传统解析"和"慢速 LLM 增强"，将用户感知的等待时间从几十秒降低到几秒，同时不牺牲最终的解析质量。

关键约定：

- Phase 1（Fast Parse）：传统解析，不调 LLM，2-8 秒完成，前端立即展示
- Phase 2（Deep Enhance）：LLM Vision OCR，后台异步，完成后才允许 Digest 消费
- `FAST_PARSED` 状态即可展示，`READY_FOR_DIGEST` 才可消费
- 两阶段写同一份 `raw_markdown/<file_id>.md`，Phase 2 是增强覆写
- Phase 2 失败不影响 Phase 1 的展示结果
