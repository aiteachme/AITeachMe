# 04. Ingest 引擎（透视引擎）

## 1. 目标与职责

Ingest 负责把用户上传的原始资料转换成后续所有引擎都能稳定消费的"材料层"。

当前职责：

- 接收上传文件（文档 / 图片 / 未来：音视频）
- 做轻量分类和解析器路由
- 生成稳定 Markdown
- 提取图片 / 附件到共享 `assets/`
- 对提取图片做 OCR / vision 补强
- 把解析状态写回 `raw_file`
- 为下游 `retrieval_chunk / chunk_embeddings / knowledge_document` 做好准备

Ingest **不**负责直接产出知识图谱或知识文档，它只负责把材料打磨到可消费状态。

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

## 3. 核心问题：Phase 1 混入了 LLM 调用

### 3.1 历史根因

两阶段架构设计上是正确的（Phase 1 纯本地, Phase 2 LLM），但实现中存在一个关键 bug：

> [!CAUTION]
> `pymupdf_ocr_vision` 解析器被放在了 Phase 1 的解析链中（`strategy.py` 的 `_preferred_parser_order`），
> 但它内部调用了 `parse_image_bytes_with_llm_vision()` 做 LLM Vision OCR。
> **这导致 Phase 1 实际耗时 10-15 秒，完全违背了 "Phase 1 不调 LLM" 的设计原则。**

违规的调用链：
```
Phase 1 → fast_parse_file → parser_chain["pymupdf_ocr_vision"]
           → _run_page_ocr → parse_image_bytes_with_llm_vision  ← LLM 调用！
```

**修复**：从所有 Phase 1 解析链中移除 `pymupdf_ocr_vision`，扫描型 PDF 改用 `pymupdf_native` 做快速文本提取。LLM OCR 全部留给 Phase 2 的 `deep_enhance_file`。

### 3.2 业界参考：主流开源项目解析器选择策略对比

我们的三层决策链（扩展名路由 → 内容分类 → 策略路由）与业界主流项目高度一致。以下是 6 个代表性项目的详细对比：

#### Unstructured.io — `auto/fast/hi_res` 三策略路由

Unstructured.io 是 RAG 领域最成熟的文档解析框架，采用 **三策略分级路由**：

| 策略 | 方式 | 速度 | 精度 | 适用场景 |
|------|------|------|------|---------|
| `fast` | 纯规则 NLP 提取 | ⚡ 极快（~100x 快于模型） | 中等 | 纯文字 PDF/eBook |
| `hi_res` | 模型布局检测（detectron2） | 🐌 慢 | 高 | 复杂布局、表格、图表 |
| `auto`（默认） | **按页智能路由** | 中 | 高 | 混合内容文档 |
| `ocr_only` | OCR 引擎 | 慢 | 中 | 扫描件 |

**关键设计**：`auto` 策略对 PDF 做 **逐页路由** — 嵌入文字的页走 `fast`，有图片/表格的页走 `hi_res`。这类似我们的 Phase 1（fast 路径）+ Phase 2（hi_res 路径），但 Unstructured 在同一 pass 中完成。

**与我们的对标**：我们的 `classify_file`（Layer 2）类似 `auto` 的文档级路由，但粒度是整个文件而非逐页。未来可优化为逐页路由。

---

#### MinerU — 两阶段 Coarse-to-Fine 架构

MinerU（6.8k ⭐）采用 **粗到细的两阶段解析**：

| 阶段 | 操作 | 输入 | 输出 |
|------|------|------|------|
| Stage I: Layout Analysis | 低分辨率（1036×1036）全局布局检测 | 降采样页面图 | 文本块/图/表/公式位置 |
| Stage II: Content Recognition | 高分辨率精细识别 | 原始分辨率裁切区域 | OCR文字/LaTeX公式/HTML表格 |

**关键设计**：
- 预处理阶段先判定 PDF 是「文字型」还是「扫描型」，决定是否启用 OCR — **与我们的 `scanned_pdf` 分类完全一致**
- 使用 PDF-Extract-Kit 的 5 个专用模型（布局/公式检测/表格识别/公式识别/OCR），按页面内容**动态选择**启用哪些模型
- 支持 `*-auto-engine` 后端，根据运行环境自动选择推理加速引擎

**与我们的对标**：我们的 Phase 1 ≈ Stage I（快速结构化），Phase 2 ≈ Stage II（精细模型识别）。MinerU 的模型更重（需 GPU），我们用传统解析器 + LLM API 替代，更适合轻量部署。

---

#### Docling (IBM) — 模块化 Converter + ML 布局检测

Docling（11k ⭐）的核心理念是 **"不放弃结构信息"**：

```
InputDoc → [DocLayNet 布局检测] → [TableFormer 表格重建] → DoclingDocument → Markdown/JSON
```

**关键设计**：
- 用 `DocLayNet`（CV 模型） 做布局检测，识别标题/段落/表格/图片/公式
- 用 `TableFormer` 做表格结构重建
- 统一输出 `DoclingDocument` 中间格式，再导出为 Markdown/JSON/HTML
- **不做运行时的解析器选择路由** — 所有文档走同一个 ML pipeline
- 尽量避免 OCR（用 CV 模型替代），减少处理时间

**与我们的对标**：Docling 不做解析器选择，统一走 ML pipeline。我们更灵活 — 有多个解析器可选，且 Phase 1 完全不依赖 ML 模型，更快。

---

#### LangChain — 显式 Loader 注册表

LangChain 是最简单的方案 — **按文件类型显式指定 Loader**：

```python
# LangChain 的方式：用户显式选择
loader = PyPDFLoader("file.pdf")      # 或 PyMuPDFLoader 或 UnstructuredPDFLoader
docs = loader.load()
```

- 没有自动路由机制，由开发者在代码中指定使用哪个 Loader
- `DirectoryLoader` 可通过 `glob` 过滤文件类型，但仍需指定每种类型的 Loader
- `DedocFileLoader` / `DedocAPIFileLoader` 有自动文件类型检测，但不做内容级选择

**与我们的对标**：LangChain 的 PARSER_REGISTRY 类似我们的 Layer 1（扩展名路由），但 **缺少 Layer 2 和 Layer 3**。我们的自动内容分类 + 策略路由远比 LangChain 智能。

---

#### RAGFlow — 用户可选 + DeepDoc 重型视觉解析

RAGFlow（32k ⭐）提供 **用户手动选择解析模式**：

| 模式 | 方式 | 适用场景 |
|------|------|---------|
| `Naive` | 跳过 OCR/TSR/DLR，纯文字提取 | 纯文本 PDF |
| `DeepDoc`（默认） | OCR + 表格结构识别 + 布局识别 | 复杂文档 |
| `MinerU` | 外部接入 MinerU 服务 | 需要高精度 |
| `Docling` | 外部接入 Docling | 实验性 |

**关键设计**：
- **不做自动路由** — 由用户在 UI 上选择解析模式，解析策略与数据集绑定
- 支持 parent-child chunking（父子分块）平衡精度和上下文
- DeepDoc 内部对相邻同布局文本框做合并，保持分块完整性

**与我们的对标**：RAGFlow 把选择权给用户。我们的 `classify_file` 自动完成这个选择，用户无需关心。但未来可以暴露一个"高级模式"让用户手动覆盖。

---

#### 对比总结

| 维度 | LangChain | Unstructured | MinerU | Docling | RAGFlow | **AiTeachMe** |
|------|-----------|-------------|--------|---------|---------|-----------|
| **路由层级** | 1层（扩展名） | 2层（扩展名+页内容） | 2层（文档分类+页分类） | 0层（统一ML） | 0层（用户手选） | **3层（扩展名+文档分类+策略路由）** |
| **自动选择** | ❌ 显式指定 | ✅ auto策略 | ✅ 预处理分类 | N/A 统一pipeline | ❌ 用户手选 | **✅ 全自动三层路由** |
| **Phase 1 速度** | 取决于选择 | fast策略极快 | 较慢（需GPU模型） | 较慢（需ML模型） | Naive极快 | **< 2秒（纯本地）** |
| **解析器数量** | 每类1-3个可选 | 4种策略 | 5个专用模型 | 2个CV模型 | 4种模式 | **6个本地+4个待接入** |
| **兜底机制** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | **✅ parser_chain 自动降级** |
| **外部服务接入** | ❌ | SaaS API | 自建Docker | Python SDK | 可选MinerU/Docling | **Provider 架构预留** |

**核心结论**：我们的三层路由 + 自动降级是所有对比项目中**最灵活的方案**。多数项目要么需要用户手动选择（LangChain、RAGFlow），要么统一走重型 ML pipeline（Docling、MinerU）。我们在不依赖 GPU 和 ML 模型的前提下，通过轻量采样分类实现了自动路由。

### 3.3 优化策略

**核心思路：前台快速出结果，后台慢慢做深度增强。**

| 阶段 | 名称 | 前台可见 | 是否调 LLM | 预期耗时 |
|------|------|---------|-----------|---------| 
| Phase 0 | **即时分发** | 文件立即出现在列表 | ❌ | **< 50ms** |
| Phase 1 | **快速解析**（Fast Parse） | ✅ 完成即展示 | ❌ 绝不调 LLM | **< 2 秒** |
| Phase 2 | **深度增强**（Deep Enhance） | 后台静默 | ✅ 调 LLM Vision OCR | 15-90 秒 |

- Phase 0：上传后文件立即出现在列表（前端秒响应），后台启动 Phase 1
- Phase 1：纯传统方法快速出 Markdown，前端展示解析结果
- Phase 2：后台异步 LLM 增强，完成后静默更新，标记 `READY_FOR_DIGEST`

### 3.4 综合改进：取各家之长的最优管线

> [!IMPORTANT]
> 本节是整个 ingest 模块重构的**核心设计依据**。每项改进标注了参考来源和预期效果。

#### 改进 1：Phase 0 即时分发层（← RAGFlow + UX 最佳实践）

**问题**：当前上传后要等 Phase 1 跑完才在 UI 看到文件，即使 2 秒也显得"卡"。

**改进**：文件落盘后**立即**在前端列表展示（"分类中"），后台异步启动 Phase 1。

```
上传 → 落盘(< 50ms) → API 返回 FileRecord → 前端显示 "分类中..."
                        └── BackgroundTasks 启动 Phase 1
```

**实现**：`POST /files/upload` 在落盘后立即返回，不等解析。解析通过 `BackgroundTasks` 异步触发。
**效果**：上传响应从 2 秒降到 **< 200ms**。

---

#### 改进 2：文本文件免分类快速通道（← RAGFlow Naive + LangChain 直通）

**问题**：`.md`/`.txt`/`.py` 等 60+ 种文本文件也走 classify → plan → parse 完整链路，浪费。

**改进**：Phase 1 入口增加快速通道 — 文本类直接读内容，跳过 classify/plan：

```python
async def run_fast_parse(raw_file):
    if is_text_extension(raw_file.file_ext):
        markdown = await read_file_content(raw_file.storage_key)
        await finalize_fast_parse(raw_file, markdown)
        return  # < 100ms，跳过 classify/plan
    # 常规通道...
```

**效果**：文本文件 Phase 1 从 ~1 秒降到 **< 100ms**。

---

#### 改进 3：PDF per-page 内容路由（← Unstructured `auto` 策略）

**问题**：整个 PDF 统一使用一个解析器，但 50 页 PDF 可能前 40 页纯文字、后 10 页扫描件。

**改进**：Phase 2 做 per-page 路由 — 只对低密度页做 OCR，高密度页跳过：

```python
for page in pages:
    if len(page.get_text().strip()) > min_text_chars:
        continue  # 文字够，跳过
    if page.has_images() or page.has_drawings():
        await ocr_page_with_llm(page)  # 需要 OCR
```

**已在 `_build_pdf_ocr_pages` 中部分实现。**
**效果**：30 页 PDF 只 OCR 3-5 页，Phase 2 从 60 秒降到 **15-20 秒**。

---

#### 改进 4：统一 FastParseResult 输出格式（← Docling DoclingDocument）

**问题**：解析器直接返回字符串，丢失页码、图表位置等结构信息。

**改进**：统一输出格式，携带结构提示供 Phase 2 和 Digest 使用：

```python
class FastParseResult(BaseModel):
    markdown: str
    parser_used: str
    page_count: int = 0
    extracted_images: list[str] = []
    structure_hints: StructureHints | None = None

class StructureHints(BaseModel):
    low_density_pages: list[int] = []   # Phase 2 优先 OCR
    has_table_pages: list[int] = []
    has_formula_pages: list[int] = []
    detected_language: str | None = None
```

**效果**：Phase 2 精确知道哪些页需 OCR，Digest 可利用结构做智能分块。

---

#### 改进 5：解析器可用性运行时检测（← MinerU auto-engine）

**问题**：缺少某个包时运行时才报错。

**改进**：启动时自动检测可用解析器，parser_chain 自动过滤不可用的。缺包不会 crash，自动降级。启动日志明确输出可用解析器。

---

#### 改进 6：OCR 预算控制（← MinerU coarse-to-fine）

**问题**：Phase 2 对所有图片做 OCR，但装饰图（logo/分隔符/小图标）浪费调用。

**改进**：按图片尺寸和宽高比过滤 — 太小（<100px）、太窄（宽高比>10）的跳过。
**效果**：OCR 图片数减少 ~50%。

---

#### 改进 7：前端多阶段进度（← "Make invisible work visible"）

| ingest_status | 前端显示 | 用户可操作 |
|--------------|---------|-----------|
| `classifying` | 分类中… 🔄 | ❌ |
| `fast_parsing` | 解析中… 🔄 | ❌ |
| `fast_parsed` | 已解析 ✅ | ✅ 可查看、对话 |
| `enhancing` | 优化中…（角标） | ✅ 可查看、对话 |
| `ready_for_digest` | 就绪 ✅ | ✅ 可构建知识 |
| `enhance_failed` | 已解析⚠️ | ✅ 可查看 + 重试 |

---

#### 改进 8：Provider 热插拔（← RAGFlow 多解析器支持）

默认零外部依赖开箱即用。配置 `MINERU_ENDPOINT` 后自动启用高精度解析，外部服务挂了自动降级到本地。详见 §10.4。

---

#### 完整优化后的 Pipeline 流水线图

```
用户上传文件
    │
    ▼ (< 50ms)
┌────────────────────────────────────────────────────────────────┐
│  Phase 0: 即时分发                                             │
│  落盘 → 写 raw_file → API 返回 → 前端显示"分类中..."          │
│  BackgroundTasks 启动 Phase 1                                 │
└────────────────────────────────────────────────────────────────┘
    │
    ▼ (快速通道 < 100ms / 常规通道 < 2s)
┌────────────────────────────────────────────────────────────────┐
│  Phase 1: 快速解析（绝不调 LLM）                               │
│                                                                │
│  [快速通道] .md/.txt/.py → read_file → finalize (< 100ms)     │
│  [图片通道] .png/.jpg → 跳过 → 直接 Phase 2                   │
│  [常规通道] .pdf/.docx/.pptx：                                 │
│    classify(to_thread) → plan(三层路由) → parse(chain+兜底)    │
│    → canonicalize → finalize                                   │
│    → status=COMPLETED, markdown_ready=true ✅                  │
│    → 后台触发 Phase 2                                          │
└────────────────────────────────────────────────────────────────┘
    │ asyncio.create_task
    ▼ (15-90 秒)
┌────────────────────────────────────────────────────────────────┐
│  Phase 2: 深度增强（调 LLM，per-page 路由）                    │
│                                                                │
│  [Provider 路由] MinerU可用→MinerU / 否则→本地LLM OCR          │
│  [本地 OCR] per-page路由 → OCR预算控制 → asset+page OCR        │
│  → 覆写 markdown → ingest_status=READY_FOR_DIGEST              │
└────────────────────────────────────────────────────────────────┘
```

#### 改进来源与效果汇总

| # | 改进 | 来源 | 效果 |
|---|------|------|------|
| 1 | Phase 0 即时分发 | RAGFlow + UX | 上传响应 < 200ms |
| 2 | 文本快速通道 | RAGFlow Naive + LangChain | 文本 < 100ms |
| 3 | per-page 路由 | Unstructured auto | Phase 2 时间减半 |
| 4 | 统一 FastParseResult | Docling | Phase 2 精准 OCR |
| 5 | 运行时检测 | MinerU auto-engine | 防 crash + 降级 |
| 6 | OCR 预算控制 | MinerU coarse-to-fine | OCR 减少 50% |
| 7 | 多阶段进度 | UX 最佳实践 | 零等待感 |
| 8 | Provider 热插拔 | RAGFlow + MinerU | 可选高精度 |


---


## 4. 两阶段 Pipeline 详细设计

### 4.1 完整 Pipeline 流水线图

```
用户上传文件
    │
    ▼
┌────────────────────────────────────────────────────────┐
│  Phase 1: Fast Parse（前台可见，不调 LLM）               │
│                                                        │
│  load_raw_file                                         │
│       ↓                                                │
│  compute_fingerprint                                   │
│       ↓                                                │
│  classify_file   ← 文件分类器（纯规则，无 LLM）         │
│       ↓                                                │
│  plan_parse      ← 选择解析器 + 生成 ParsePlan          │
│       ↓                                                │
│  fast_parse_file ← 传统解析 + 规范化 + 图片提取          │
│       ↓                                                │
│  finalize_fast_parse                                   │
│       │                                                │
│       ├──→ raw_file.ingest_status = FAST_PARSED        │
│       ├──→ 发布 IngestFileFastParsedEvent               │
│       └──→ 前端展示 Markdown + 图片预览                  │
└────────────────────────────────────────────────────────┘
         │
         │ asyncio.create_task (后台自动触发，用户无感知)
         ▼
┌────────────────────────────────────────────────────────┐
│  Phase 2: Deep Enhance（后台异步，调 LLM Vision）        │
│                                                        │
│  load_enhance_context                                  │
│       ↓                                                │
│  deep_enhance_file                                     │
│       ├── enhance_markdown_with_asset_ocr              │
│       │      └── 对 assets/ 下图片调 LLM Vision OCR     │
│       └── enhance_pdf_markdown_with_page_fallback      │
│              └── 对低密度页面做整页 Vision OCR            │
│       ↓                                                │
│  finalize_deep_enhance                                 │
│       │                                                │
│       ├──→ 覆写 raw_markdown/<file_id>.md              │
│       ├──→ raw_file.ingest_status = READY_FOR_DIGEST   │
│       └──→ 发布 IngestFileReadyForDigestEvent           │
└────────────────────────────────────────────────────────┘
         │
         │ 前置条件满足 (所有文件 READY_FOR_DIGEST)
         ▼
┌────────────────────────────────────────────────────────┐
│  Digest 引擎开始消费                                    │
└────────────────────────────────────────────────────────┘
```

### 4.2 Phase 1：快速解析（Fast Parse）

**目标**：不调任何 LLM，用纯传统方法在 **< 2 秒**内出 Markdown。

> [!IMPORTANT]
> Phase 1 的解析链中**绝不允许包含任何调用 LLM 的解析器**（如 `pymupdf_ocr_vision`、`llm_vision`）。
> 所有 LLM 调用全部归入 Phase 2。

**LangGraph 节点流**：

```
load_raw_file → compute_fingerprint → classify_file → plan_parse → fast_parse_file → finalize_fast_parse
```

**`fast_parse_file` 节点内部流程**：

```
1. 根据 parser_chain 选择传统解析器（禁止 LLM 解析器！）
   - PDF:  pymupdf_native / pymupdf4llm / markitdown / unpdf（未来）
   - DOCX: docx_native / markitdown
   - PPTX: python_pptx_native / markitdown
   - 图片: 跳过 Phase 1，直接全量走 Phase 2（图片必须 LLM）
   - 文本/Markdown: text_native（直接完成，无需 Phase 2）
   - 音频: 跳过 Phase 1（需要 ASR，参见 §10 扩展性设计）

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

| 包 | 用途 | 是否调 LLM | 状态 |
|---|------|-----------|------|
| `pymupdf` (fitz) | PDF 原生文字提取 + 图片提取 + drawing 渲染 | ❌ | 已接入 |
| `pymupdf4llm` | PDF → Markdown（保留表格/公式结构） | ❌ | 已接入 |
| `markitdown` | 通用文档 → Markdown 转换 | ❌ | 已接入 |
| `python-docx` | DOCX 原生解析 | ❌ | 已接入 |
| `python-pptx` | PPTX 原生解析 | ❌ | 已接入 |
| `unpdf` | Rust 驱动高速 PDF→Markdown，支持 CJK 并行提取 | ❌ | **待接入** |

> [!NOTE]
> `unpdf` 是 Rust 底层的 PDF 解析库（pip install unpdf），支持 PDF 1.0-2.0、CJK 文本、
> 并行页面解析，速度远快于 pymupdf4llm。建议作为 PDF Phase 1 的首选解析器引入，
> pymupdf_native 作为兜底。

### 4.3 解析器自动选择策略（Parser Selection）

系统使用 **三层决策链** 自动为每个文件选择最优解析器，用户无需手动指定：

```
文件进入
  │
  ▼
┌─────────────────────────────────────┐
│  Layer 1: 扩展名路由（零开销）       │
│  formats.py → 确定文件大类           │
│  .pdf → PDF路径                     │
│  .docx → DOCX路径                   │
│  .py/.md/.txt → 文本直通            │
│  .png/.jpg → 图片路径（需LLM）       │
│  .xlsx/.epub等 → markitdown通用      │
└─────────────────────────────────────┘
  │ 仅 PDF/DOCX/PPTX 需要 Layer 2
  ▼
┌─────────────────────────────────────┐
│  Layer 2: 内容采样分类（<200ms）     │
│  classifier.py → 采样前10页          │
│  分析: 文字密度/图片比/drawing比      │
│  输出: file_category + 建议解析器     │
└─────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────┐
│  Layer 3: 策略路由（零开销）         │
│  strategy.py → 生成有序解析器链      │
│  考虑: 分类结果 + 文件大小 + LLM可用 │
│  输出: parser_chain（逐个尝试）       │
└─────────────────────────────────────┘
```

#### Layer 1: 扩展名 → 文件大类

| 文件大类 | 扩展名 | 处理方式 |
|----------|--------|---------|
| **文本类** | `.md` `.txt` `.py` `.json` `.yaml` `.csv` `.html` 等 60+ 种 | 直接 `text_native` 解析，Phase 1 即完成，无需 Phase 2 |
| **PDF** | `.pdf` | 需要 Layer 2 内容分类 → 选择 pymupdf_native / pymupdf4llm / markitdown |
| **Word** | `.docx` | 需要 Layer 2 → 选择 docx_native / markitdown |
| **PPT** | `.ppt` `.pptx` | 需要 Layer 2 → 选择 python_pptx_native / markitdown |
| **图片** | `.png` `.jpg` `.jpeg` `.webp` `.gif` `.bmp` `.tif` | 跳过 Phase 1，Phase 2 用 `llm_vision` |
| **通用文档** | `.doc` `.xlsx` `.xls` `.epub` `.rtf` `.odt` `.msg` 等 | 统一用 `markitdown_generic` |

#### Layer 2: PDF 内容采样分类

对 PDF 文件，`classify_file` 用 PyMuPDF 快速采样前 10 页（耗时 < 200ms），计算以下指标：

| 指标 | 计算方法 | 用途 |
|------|---------|------|
| `avg_density` | 每页平均字符数 | 区分扫描件 vs 文字型 |
| `image_ratio` | 字少（<50字）且有大图的页面占比 | 识别图片密集型 |
| `drawing_ratio` | 有 meaningful drawing 的页面占比 | 识别公式/图表密集型 |
| `formula_ratio` | drawing≥3 且 字<500 的页面占比 | 识别数学试卷类 |
| `has_tables` | 正则检测表格模式 | 表格优化 |
| `has_formulas` | 正则检测公式 or drawing_ratio>0.3 | 公式优化 |

基于指标得出分类：

| 分类 | 判定条件 | 典型场景 |
|------|---------|---------|
| `scanned_pdf` | avg_density < 30 | 扫描件、纯图片PDF |
| `formula_heavy_pdf` | formula_ratio > 0.5 且 avg_density < 300 | 数学试卷、物理题 |
| `complex_pdf` | image_ratio > 0.5 或 (drawing_ratio > 0.6 且 avg_density > 200) | 图表密集型课件 |
| `text_pdf` | 其他（默认） | 普通文字型PDF |

#### Layer 3: 分类 → 有序解析器链

基于分类结果 + 文件大小 + 页数，决定 parser chain 顺序（**第一个成功即返回，后续作为兜底**）：

**PDF 解析器选择矩阵：**

| 条件 | 第1选择 | 第2选择 | 第3选择 | 理由 |
|------|---------|---------|---------|------|
| `scanned_pdf` | pymupdf_native | markitdown | pymupdf4llm | native 最快提取可提取的文字，LLM OCR 留给 Phase 2 |
| `formula_heavy_pdf` | pymupdf_native | pymupdf4llm | markitdown | native 能提取 drawing 作为图片，Phase 2 做 OCR |
| 大文件(≥20MB or ≥120页) | pymupdf_native | pymupdf4llm | markitdown | native 内存效率最高 |
| 有表格/公式 | pymupdf4llm | pymupdf_native | markitdown | pymupdf4llm 保留表格结构最佳 |
| `text_pdf`(默认) | pymupdf4llm | markitdown | pymupdf_native | pymupdf4llm 质量最高 |

**其他格式解析器选择：**

| 格式 | 条件 | 解析器链 |
|------|------|---------|
| DOCX 大文件(≥10MB or ≥60页) | `docx_native → markitdown` | native 内存更省 |
| DOCX 普通 | `markitdown → docx_native` | markitdown 格式更好 |
| PPTX 大文件(≥15MB or ≥80幻灯片) | `python_pptx_native → markitdown` | native 更省内存 |
| PPTX 普通 | `markitdown → python_pptx_native` | markitdown 格式更好 |

#### 兜底机制

`fast_parse_file` 按 parser_chain 逐个尝试，每个解析器有 `timeout_s`（默认 60s）超时保护。如果第一个超时或报错，自动尝试下一个。全部失败才标记为 `FAILED`。

```python
for parser_name in plan.parser_chain:
    try:
        result = await asyncio.wait_for(parser(...), timeout=plan.options.timeout_s)
        return result  # 第一个成功即返回
    except (TimeoutError, Exception):
        continue        # 尝试下一个
raise last_error         # 全部失败
```

**`finalize_fast_parse` 节点行为**：

- `raw_file.status = completed`
- `raw_file.ingest_status = FAST_PARSED`（新状态）
- `raw_file.markdown_path` 指向快速版 Markdown
- 发布 `IngestFileFastParsedEvent`
- **前端收到此事件或轮询到此状态后，即可展示解析结果**
- **此时后台自动触发 Phase 2**

### 4.3 Phase 2：深度增强（Deep Enhance）

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

### 4.4 Phase 2 的生命周期管理

Phase 2 以 `asyncio.create_task` 启动，需要处理以下生命周期场景：

| 场景 | 处理方式 |
|------|---------|
| Phase 2 正常完成 | 更新状态为 `READY_FOR_DIGEST` |
| Phase 2 LLM 调用失败 | 状态改为 `ENHANCE_FAILED`，Phase 1 结果仍可用 |
| 用户关闭页面 | Phase 2 随 FastAPI 进程存活继续运行，不受前端影响 |
| 服务重启 / 进程被杀 | 启动时扫描 `FAST_PARSED` 和 `ENHANCING` 状态的文件，重新 dispatch Phase 2 |
| 用户手动重试 | 提供 API 允许对 `ENHANCE_FAILED` 的文件重新触发 Phase 2 |

**服务重启恢复机制**（在 `app/startup.py` 或等效位置）：

```python
# 伪代码
async def recover_stalled_enhancements():
    """服务启动时恢复中断的 Phase 2 任务。"""
    stalled_files = get_files_by_ingest_status(
        [IngestStatus.FAST_PARSED, IngestStatus.ENHANCING]
    )
    for raw_file in stalled_files:
        asyncio.create_task(run_deep_enhance(raw_file))
        logger.info("recovered_stalled_enhancement", file_id=raw_file.id)
```

> **设计决策**：Phase 2 随服务进程存活，不受前端连接状态影响。如果服务被杀，启动时自动恢复。这比依赖外部消息队列（Celery / Redis Queue）更轻量，适合当前单机部署场景。未来如果需要水平扩展，可以替换为消息队列驱动。

---

## 5. IngestStatus 状态机

### 5.1 状态流变更

```
旧状态流:
  PENDING → CLASSIFYING → PARSING → VALIDATING → READY_FOR_DIGEST
                                                  ↘ FAILED

新状态流:
  PENDING → CLASSIFYING → FAST_PARSING → FAST_PARSED → ENHANCING → READY_FOR_DIGEST
                                         ↗ (前端可展示)              ↘ ENHANCE_FAILED
                                                       ↘ FAILED
```

### 5.2 状态说明

| 状态 | 含义 | 前端可展示 | Digest 可消费 |
|------|------|-----------|-------------|
| `PENDING` | 文件已上传，等待解析 | ❌ | ❌ |
| `CLASSIFYING` | 正在分类文件类型 | ❌ | ❌ |
| `FAST_PARSING` | Phase 1 快速解析中 | ❌ | ❌ |
| `FAST_PARSED` | Phase 1 完成，后台正在启动 Phase 2 | ✅ | ❌ |
| `ENHANCING` | Phase 2 LLM 深度增强中 | ✅ | ❌ |
| `READY_FOR_DIGEST` | Phase 2 完成 | ✅ | ✅ |
| `ENHANCE_FAILED` | Phase 2 失败（Phase 1 结果仍可用） | ✅ | ⚠️ 降级可用 |
| `FAILED` | Phase 1 失败（整体失败） | ❌ | ❌ |

> **关键设计**：`ENHANCE_FAILED` 不等于整体失败。即使 Phase 2 失败，Phase 1 的 Markdown 仍然可用，用户仍然可以阅读、对话。但 Digest 引擎应标记该文件为"OCR 未完成"，后续可重试。

### 5.3 枚举变更

```python
# backend/app/models/enums.py

class IngestStatus(str, Enum):
    """Ingest 流水线状态。"""

    PENDING = "pending"
    CLASSIFYING = "classifying"
    FAST_PARSING = "fast_parsing"      # 新增
    FAST_PARSED = "fast_parsed"        # 新增（替代旧 PARSING）
    ENHANCING = "enhancing"            # 新增
    READY_FOR_DIGEST = "ready_for_digest"
    ENHANCE_FAILED = "enhance_failed"  # 新增
    RETRY_PENDING = "retry_pending"
    FAILED = "failed"
    
    # 删除旧状态: PARSING, VALIDATING
```

---

## 6. 事件体系

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

## 7. Ingest → Digest 阻塞关系

### 7.1 阻塞规则

Digest 引擎 **必须等待 Ingest 的 Phase 2 完成**后才能开始消费文件。具体来说：

- Digest 在启动 `prepare_chunk_ids_for_files` 时，应检查每个 `raw_file.ingest_status`
- 只有 `ingest_status == READY_FOR_DIGEST` 的文件才能进入 Digest 管线
- `FAST_PARSED` 或 `ENHANCING` 状态的文件应被跳过或等待

### 7.2 实现方式

在 `digest/kg/support.py::prepare_chunk_ids_for_files` 的入口增加前置检查：

```python
for raw_file in target_files:
    if raw_file.ingest_status != IngestStatus.READY_FOR_DIGEST:
        if raw_file.ingest_status == IngestStatus.ENHANCE_FAILED:
            logger.warning("file_enhance_failed_using_fast_parse", file_id=raw_file.id)
            # 允许降级使用 Phase 1 结果，但标记 quality_flag
        else:
            raise IngestNotReadyError(raw_file.id, raw_file.ingest_status)
```

### 7.3 用户可见的交互流程

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

## 8. 文件存储与产物

### 8.1 本地产物

单个原始文件解析完成后，会得到：

- `data/<subject>/raw_files/<raw_file_id>.<ext>`
- `data/<subject>/raw_markdowns/<raw_file_id>.md`
- `data/<subject>/assets/<asset_name_prefix>__*.png|jpg|...`

重要约定：

1. `raw_markdowns/` 取代旧 `markdown/`
2. `assets/` 是整个 subject 共享的扁平目录，不再使用 `assets/<file_id>/`
3. Phase 1 和 Phase 2 写的都是同一个 `raw_markdown/<file_id>.md`，Phase 2 是对 Phase 1 产物的增强覆写

### 8.2 共享 `assets/` 目录策略

一个 subject 只有一个 `assets/`，每个原始文件用 `asset_name_prefix` 作为命名前缀：

```
linear_algebra__file_123abc__p2_img1_9fcd2a1b8e.png
```

好处：

- 保持所有 Markdown 都是一级目录
- `raw_markdowns/` 和 `knowledge_markdowns/` 共用同一套相对路径
- 删除单个文件时按前缀清理，不会误删

### 8.3 Markdown 与图片引用规则

Ingest 统一把 Markdown 里的图片引用规范成：

```
../assets/<flattened_asset_name>
```

同时适用于 `raw_markdowns/*.md` 和 `knowledge_markdowns/*.md`。

---

## 9. OCR / Vision 补强策略（Phase 2 专属）

### 9.1 为什么必须补这一步

仅靠传统解析器，经常会得到这类内容：

```
picture [176 x 30] intentionally omitted
```

这对公式题、试卷扫描件、图表型资料几乎不可用。

### 9.2 当前实现

在 Phase 2 的 `deep_enhance_file` 中做两类增强：

1. **Asset 级 OCR** — 针对提取出来的图片做 vision OCR，再回填到 Markdown
2. **页面级 OCR 兜底**（仅 PDF） — 对低文字密度页渲染成 PNG 再做整页 vision OCR

Asset OCR 的效果包括：

- 把 `intentionally omitted` 之类占位符替换成真实图片引用 + OCR 文本
- 在没有占位符时，按需追加 `Extracted Image OCR` 补充段落

### 9.3 参考思路

这套方案和 MinerU 的"Markdown + sidecar images"、Unstructured.io 的"Hi-Res + VLM Enrichments"方向一致：

- 正文是 Markdown
- 图片作为旁路资产单独落盘
- Markdown 只保留稳定引用
- VLM 增强作为后置异步步骤

不同点在于我们按 subject 共享 `assets/`，用 `asset_name_prefix` 做确定性隔离。

### 9.4 OCR 优化配置

#### PDF 分类器策略

| 分类 | 条件 | 特殊配置 |
|------|------|---------|
| `scanned_pdf` | `avg_density < 30` | 启用整页 OCR，`ocr_page_limit=18` |
| `formula_heavy_pdf` | `formula_ratio > 0.5 && avg_density < 300` | `asset_image_limit=32`, `asset_vision_ocr_limit=24` |
| `complex_pdf` | `image_ratio > 0.5 || (drawing_ratio > 0.6 && avg_density > 200)` | `asset_image_limit=24` |
| `text_pdf` | 默认 | 标准配置 |

#### OCR 模型配置

- 支持独立配置 `OCR_MODEL`、`OCR_API_KEY`、`OCR_BASE_URL`
- 未配置时自动回退到 LLM 配置
- 使用 `litellm.acompletion` 调用

---

## 10. 扩展性设计：音视频、外部解析服务及未来格式

### 10.1 Handler 注册模式

借鉴 Docling 的模块化 Pipeline 思想，引入 **IngestHandler 注册机制**，每种输入类型对应一个 handler：

```python
# 伪代码：handler 注册表
INGEST_HANDLERS: dict[str, IngestHandler] = {
    ".pdf":  DocumentHandler(),     # Phase 1 传统解析 + Phase 2 OCR 补强
    ".docx": DocumentHandler(),
    ".pptx": DocumentHandler(),
    ".png":  ImageHandler(),        # Phase 1 跳过 → Phase 2 LLM Vision
    ".jpg":  ImageHandler(),
    ".mp3":  AudioHandler(),        # Phase 1 跳过 → Phase 2 ASR 转写（未来）
    ".wav":  AudioHandler(),
    ".mp4":  VideoHandler(),        # Phase 1 跳过 → Phase 2 提取音轨 + ASR（未来）
    ".md":   TextHandler(),         # Phase 1 直接完成，无 Phase 2
    ".txt":  TextHandler(),
}
```

每个 handler 实现两个方法：

```python
class IngestHandler(Protocol):
    async def fast_parse(self, file_path: Path, asset_dir: Path, plan: ParsePlan) -> FastParseResult:
        """Phase 1: 快速解析，不调 LLM。返回 None 表示跳过 Phase 1。"""
        ...

    async def deep_enhance(self, context: EnhanceContext) -> DeepEnhanceResult:
        """Phase 2: 深度增强，可调 LLM / ASR / 其他外部服务。返回 None 表示无需 Phase 2。"""
        ...
```

### 10.2 音频支持方案（未来）

用户上传录音文件时的处理流程：

```
用户上传 lecture.mp3
  ↓
Phase 1: AudioHandler.fast_parse()
  ├── 提取音频元信息（时长、采样率、声道等）
  ├── 生成占位 Markdown："## 音频文件：lecture.mp3\n> 时长 45:12，正在转写中..."
  └── 前端立即展示占位内容
  ↓
Phase 2: AudioHandler.deep_enhance()
  ├── 调用 ASR 模型（Whisper / FunASR / SenseVoice 等）
  ├── 转写结果 → 格式化 Markdown（带时间戳段落）
  └── 覆写 raw_markdown/<file_id>.md
```

> **设计决策**：音频上传后，Phase 1 立即"完成"并在前端显示占位内容（文件名、时长等元信息），用户不会卡在"上传中"。Phase 2 在后台做 ASR 转写，完成后自动更新 Markdown。如果用户关闭页面，Phase 2 随服务存活继续运行。如果服务重启，§4.4 的恢复机制会自动重新 dispatch。

### 10.3 未来扩展路径

| 格式       | Phase 1 行为 | Phase 2 行为 | 预期时间 |
| ---------- | ------------- | ------------- | -------- |
| PDF/DOCX/PPTX | 传统解析出 Markdown  | LLM Vision OCR | 当前 |
| 图片       | 跳过（或提取 EXIF 元信息） | LLM Vision OCR | 当前 |
| 音频       | 提取元信息 + 占位 Markdown | ASR 转写 | 近期 |
| 视频       | 提取音轨 + 关键帧截图     | 音轨 ASR + 关键帧 OCR | 远期 |
| 网页 URL   | 抓取 HTML → readability 提取 | LLM 摘要/清洗 | 远期 |

### 10.4 外部文档解析服务适配层（Provider 架构）

> [!IMPORTANT]
> 系统需预留对 MinerU、Docling 等外部文档解析服务的接入能力。这些服务通常提供更精确的
> 布局分析、公式识别和表格提取，可以作为 Phase 1 或 Phase 2 的可选后端。

#### 设计目标

- 当前 Phase 1/Phase 2 使用本地解析器（pymupdf、markitdown 等），**默认零外部依赖**
- 用户可选配外部解析服务（MinerU Docker / API、Docling 等），系统自动路由
- 外部服务不可用时自动降级到本地解析器，不影响可用性

#### Provider 接口定义

```python
class DocumentParseProvider(Protocol):
    """外部文档解析服务的统一适配接口。"""

    name: str               # 如 "mineru", "docling", "local"
    supports_async: bool    # 是否支持异步解析

    async def parse(
        self,
        file_path: Path,
        asset_dir: Path,
        options: ProviderParseOptions,
    ) -> ProviderParseResult:
        """调用外部服务解析文档，返回 Markdown + 提取的资产。"""
        ...

    async def health_check(self) -> bool:
        """检查外部服务是否可用。"""
        ...


class ProviderParseOptions(BaseModel):
    timeout_s: int = 60
    output_format: str = "markdown"   # markdown | json
    enable_ocr: bool = True
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "auto"


class ProviderParseResult(BaseModel):
    markdown: str
    assets: list[Path] = []           # 提取的图片/附件
    metadata: dict = {}               # 解析元信息
    provider_name: str
    elapsed_s: float
```

#### 路由策略

```python
# 伪代码：provider 路由
async def select_parse_provider(extension: str, file_size: int) -> DocumentParseProvider:
    settings = get_settings()

    # 优先使用外部服务（如果配置了且健康）
    if settings.mineru_endpoint:
        provider = MinerUProvider(settings.mineru_endpoint)
        if await provider.health_check():
            return provider

    if settings.docling_endpoint:
        provider = DoclingProvider(settings.docling_endpoint)
        if await provider.health_check():
            return provider

    # 默认回退到本地解析器
    return LocalParserProvider()
```

#### 已知可接入的外部服务

| 服务 | 接入方式 | 优势 | 状态 |
|------|---------|------|------|
| **MinerU** | Docker 部署 / 官方 API (`mineru.net`) | 精确布局分析、公式识别、表格提取、多语言 | **待接入** |
| **Docling (IBM)** | Python SDK (`pip install docling`) | 模块化 Processor、DoclingDocument 统一输出 | 待评估 |
| **Marker** | Python SDK (`pip install marker-pdf`) | 学术 PDF 优化、公式保留 | 待评估 |
| **unpdf** | Python SDK (`pip install unpdf`) | Rust 性能、CJK 支持、Phase 1 专用 | **待接入** |

#### 配置方式

```env
# .env 中的外部服务配置
MINERU_ENDPOINT=http://localhost:8765    # MinerU Docker 服务地址
MINERU_API_KEY=                          # MinerU 官方 API Key（可选）
DOCLING_ENDPOINT=                        # Docling 服务地址（可选）
PARSE_PROVIDER_PRIORITY=mineru,local     # 解析器优先级，逗号分隔
```

---

## 11. LangGraph 节点详细设计

### 11.1 Phase 1 节点

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

从当前 `orchestrator.py::parse_file` 中提取传统解析部分（调 parser → `canonicalize_markdown`），去掉 `enhance_markdown_with_asset_ocr` 和 `enhance_pdf_markdown_with_page_fallback`。

写文件：`raw_markdown/<file_id>.md`、`assets/<prefix>__*.png|jpg|...`

#### `build_finalize_fast_parse_node`（**新，替代原 `finalize_success`**）

写表 `raw_file`：`status=completed`、`ingest_status=FAST_PARSED`、`markdown_path`、`asset_dir` 等。
发布 `IngestFileFastParsedEvent`。
**自动触发 Phase 2**。

### 11.2 Phase 2 节点

#### `build_load_enhance_context_node`（**新**）

读取 Phase 1 的产物路径和 parse_plan，准备增强上下文。

#### `build_deep_enhance_file_node`（**新**）

执行 `enhance_markdown_with_asset_ocr` + `enhance_pdf_markdown_with_page_fallback`。
覆写 `raw_markdown/<file_id>.md`。

#### `build_finalize_deep_enhance_node`（**新**）

写表 `raw_file`：`ingest_status=READY_FOR_DIGEST`、更新 `parse_metadata`（含 OCR 统计）。
发布 `IngestFileReadyForDigestEvent`。

---

## 12. 后端代码变更清单

### 12.1 需要修改的文件

| 文件 | 变更内容 |
|------|---------|
| `models/enums.py` | IngestStatus 新增 `FAST_PARSING` / `FAST_PARSED` / `ENHANCING` / `ENHANCE_FAILED`，删除旧 `PARSING` / `VALIDATING` |
| `workflows/ingest/graph.py` | 拆成 Phase 1 graph（fast parse）+ Phase 2 graph（deep enhance），两个独立的 StateGraph |
| `workflows/ingest/runtime.py` | 拆成 `run_fast_parse_workflow` 和 `run_deep_enhance_workflow`，Phase 1 完成后 `asyncio.create_task` Phase 2 |
| `workflows/ingest/state.py` | 新增 `IngestEnhanceState`（Phase 2 专用 state） |
| `workflows/ingest/events.py` | 新增 `IngestFileFastParsedEvent`、`IngestFileEnhanceStartedEvent`、`IngestFileEnhanceFailedEvent` |
| `workflows/ingest/nodes/parse.py` | 拆出 `fast_parse_file` 节点（去掉 OCR 增强调用） |
| `workflows/ingest/nodes/finalize.py` | 拆出 `finalize_fast_parse` + `finalize_deep_enhance` |
| `workflows/ingest/parsing/orchestrator.py` | 拆出 `fast_parse_file()` 和 `deep_enhance_file()` 两个函数 |
| `workflows/digest/kg/support.py` | `prepare_chunk_ids_for_files` 入口增加 ingest_status 前置检查 |
| `api/files.py` 或 `services/file_service.py` | 新增 "重试 Phase 2" 的 API 端点 |

### 12.2 需要新增的文件

| 文件 | 内容 |
|------|-----|
| `workflows/ingest/nodes/enhance.py` | Phase 2 的 `build_load_enhance_context_node`、`build_deep_enhance_file_node`、`build_finalize_deep_enhance_node` |
| `workflows/ingest/recovery.py` | 服务启动时恢复中断的 Phase 2 任务 |

---

## 13. 前端 UI 变更要点

### 13.1 需要删除的内容

- 当前 UploadPage 上展示 ingest 解析效果的调试 UI（后续删除）

### 13.2 需要调整的交互

- Phase 1 完成后，前端应展示 Markdown 预览（作为解析结果）
- 如果 Phase 2 仍在进行中，可以在文件卡片上显示一个小标识（如 "深度解析中..."）
- Phase 2 完成后标识消失，文件卡片显示完整状态
- 整体 UI 风格需要与当前系统画风、动效保持一致

### 13.3 前端轮询策略

```
1. 上传后轮询 raw_file 状态（每 2s 一次）
2. 收到 FAST_PARSED → 停止轮询，拉取 Markdown 并展示
3. 后台继续低频轮询 Phase 2 状态（每 5s 一次）
4. 收到 READY_FOR_DIGEST → 更新文件卡片状态，可用于 Digest
5. 收到 ENHANCE_FAILED → 显示提示 + 重试按钮
```

---

## 14. 速度预期

| 场景 | Phase 1 预期耗时 | Phase 2 预期耗时 | 用户感知等待 |
|------|----------------|----------------|------------|
| 10 页普通 PDF（文字为主） | **< 1 秒** | 5-15 秒 | **< 1 秒** |
| 30 页 PDF（含 20 张图） | **1-2 秒** | 30-60 秒 | **1-2 秒** |
| 数学试卷 PDF（公式密集） | **1-3 秒** | 40-90 秒 | **1-3 秒** |
| 50 页 DOCX | **< 2 秒** | 10-30 秒 | **< 2 秒** |
| 100 页 PPTX | **2-5 秒** | 15-40 秒 | **2-5 秒** |
| 纯文本 / Markdown | **< 0.5 秒** | 无 Phase 2 | **< 0.5 秒** |
| 单张图片 | 无 Phase 1 | 3-8 秒 | **3-8 秒**（必须等 LLM） |
| 音频 45 分钟（未来） | **< 0.5 秒**（元信息） | 60-180 秒（ASR） | **< 0.5 秒** |

> [!NOTE]
> Phase 1 目标从原来的 2-8 秒降低到 **< 2 秒**。关键手段：
> (1) Phase 1 绝不调 LLM；(2) 优先使用 `pymupdf_native`（最快的本地解析器）；
> (3) 未来引入 `unpdf`（Rust 驱动）进一步压缩到亚秒级；
> (4) `classify_file` 用 `asyncio.to_thread` 离线执行。

**核心改进**：用户感知的等待时间从原先的 Phase 1 + Phase 2 总和，降低到仅 Phase 1 的时间。

---

## 15. 后续优化方向

### 15.1 Phase 1 加速

1. **引入 unpdf 解析器** — Rust 底层 PDF→Markdown，支持 CJK 和并行页面提取，预期比 pymupdf 快 3-5x
2. **跳过 classify_file 对简单文件** — 纯文本/Markdown 文件无需分类，直接进入 `text_native` 解析
3. **流式化 canonicalize_markdown** — 边解析边规范化，减少中间字符串拷贝

### 15.2 Phase 2 增强

4. **智能 OCR 预算分配** — 根据图片复杂度动态调整 OCR 优先级，优先 OCR 包含公式的图片
5. **OCR 结果缓存** — 对相同图片的 OCR 结果做缓存，避免重复调用
6. **批量 OCR** — 支持批量发送图片到 OCR API，提升并发效率
7. **OCR 质量评估** — 自动评估 OCR 结果质量，对低质量结果标记或重试
8. **多模型融合** — 对关键图片使用多个模型 OCR，融合结果提升准确率

### 15.3 架构升级

9. **接入 MinerU 解析服务** — 通过 §10.4 的 Provider 架构，将 MinerU 作为可选的高精度解析后端，替代或增强本地解析
10. **Phase 2 重试机制** — `ENHANCE_FAILED` 状态的文件支持手动/自动重试，前端提供重试按钮
11. **分布式任务队列** — 未来如需水平扩展，将 Phase 2 从 `asyncio.create_task` 迁移到 Celery / Redis Queue
12. **增量增强** — Phase 2 完成后如果有新模型可用，支持对已有文件做增量 re-enhance
13. **接入 Marker/Docling** — 通过 Provider 架构接入更多学术 PDF 优化解析器

---

## 16. 总结

Ingest 引擎的核心价值是把资料稳稳转换成统一材料层。新的两阶段架构通过分离"快速传统解析"和"慢速 LLM 增强"，将用户感知的等待时间从几十秒降低到几秒，同时不牺牲最终的解析质量。

关键约定：

- **Phase 1（Fast Parse）**：传统解析，不调 LLM，2-8 秒完成，前端立即展示
- **Phase 2（Deep Enhance）**：LLM Vision OCR，后台异步，完成后才允许 Digest 消费
- `FAST_PARSED` 状态即可展示，`READY_FOR_DIGEST` 才可 Digest 消费
- 两阶段写同一份 `raw_markdown/<file_id>.md`，Phase 2 是增强覆写
- Phase 2 失败不影响 Phase 1 的展示结果
- Phase 2 随服务进程存活，服务重启自动恢复
- 架构可扩展至音频（ASR）、视频、网页等输入类型
