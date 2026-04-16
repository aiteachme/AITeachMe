# 21. Ingest v2 全流程设计：从资料上传到可教学材料

最后更新：2026-04-16

本文重新设计 AITeachMe 的 Ingest 透视引擎。

它不再只是“把文件转 Markdown”，而是把任意学习资料转成后续四个引擎都能稳定消费的“可教学材料包”：

```text
原始文件
  -> 可预览 Markdown
  -> 结构化 ParsedBlock
  -> 可溯源 PageMap / bbox / assets
  -> 质量报告 ParseReport
  -> Digest / Interact / Examine / Profile 可复用证据层
```

本文参考了 RAGFlow / DeepDoc 的流程，但目标是做出更适合 AITeachMe 的方案。RAGFlow 的强项是“文档解析 + chunking”，AITeachMe 的目标更进一步：资料不仅要能检索，还要能讲解、出题、诊断和画像。

## 1. 总结结论

### 1.1 旧方案的问题

当前 Ingest 的两阶段方向是对的：

```text
Phase 1 fast parse -> 快速预览
Phase 2 deep enhance -> 后台增强
```

但现有流程还不够好：

1. Provider 选择不够清晰。MinerU 是 runtime 特例，不是真正的 provider。
2. `needs_enhance` 混合了质量重解析、OCR、VLM、图片增强等多个意图。
3. 输出以 Markdown 为中心，缺少统一的 block / bbox / asset / quality contract。
4. 本地解析、OCR、多模态之间不是 DAG，而是简单 fallback。
5. 慢模型没有足够严格的预算和候选区域缩小机制。
6. 文件格式支持主要跟 parser package 绑定，缺少转换层。
7. 解析质量没有仲裁机制，无法比较 MinerU、本地、OCR、VLM 哪个结果更好。

### 1.2 RAGFlow 值得学的地方

RAGFlow / DeepDoc 有几个很好的设计：

1. `layout_recognize` / `parse_method` 驱动 parser 选择。
2. DeepDOC 先做本地 OCR、layout、table structure recognition，再输出带位置的文本块。
3. MinerU、Docling、PaddleOCR 都会被转成类似 bbox item 的统一结构。
4. VLM 通常作为媒体增强，不是所有文档默认全量调用。
5. PDF 可以按页分片并行，表格和图片可以带上下文。

### 1.3 我们要比它更进一步

AITeachMe Ingest v2 推荐形态：

```text
RAGFlow-style parser/provider selection
  + MinerU explicit-first policy
  + ConversionBroker 支持更多格式
  + ParsedBlock 标准中间层
  + QualityArbiter 质量仲裁与合并
  + Targeted OCR/VLM 慢路径预算
  + Persistent Job 可恢复任务
  + 面向教学的 Evidence Package
```

一句话：

> RAGFlow 把文档变成可检索 chunk；AITeachMe 要把文档变成可教学、可出题、可溯源、可画像的学习材料。

## 2. 设计原则

### 2.1 用户显式选择优先

如果用户配置并选择了 MinerU，那么 MinerU 支持的文件类型应直接用 MinerU 解析。

不要出现这种流程：

```text
用户选择 MinerU
  -> 先本地粗解析
  -> 再视情况 MinerU
```

正确流程应该是：

```text
用户选择 MinerU
  -> MinerU 支持该类型：直接 MinerU
  -> MinerU 不支持但可安全转换：转换后 MinerU
  -> MinerU 不支持且不能转换：
       strict 模式失败
       fallback 模式转本地 parser
```

### 2.2 Auto 模式成本优先

如果用户没有显式选择高质量 provider，Auto 模式应该先走成本低、速度快、确定性强的路径。

例如：

- `.txt/.md/code` 本地 UTF-8 直通
- 简单文字 PDF 本地 fast parse
- 表格/扫描/公式 PDF 才优先 MinerU / OCR / DeepDoc
- 图片优先 OCR，VLM 兜底

### 2.3 本地 parser 不是低级兜底，而是慢模型加速器

本地 parser 的作用包括：

- 快速预览
- 抽取页码、文本密度、图片、表格候选
- 缩小 OCR / VLM 输入范围
- 给 quality arbitration 提供候选稿

因此即使最终用 OCR/VLM，也不应该默认整文调用模型。

### 2.4 所有 provider 输出先归一化

无论来自 MinerU、DeepDoc、Docling、PaddleOCR、本地 parser、VLM，统一先进入：

```text
ProviderResult
  -> ParsedBlock[]
  -> ParsedAsset[]
  -> PageMap
  -> QualitySignals
```

再渲染 Markdown。

不要让每个 provider 自己决定最终 Markdown 长什么样，否则 Digest / Interact / Examine 无法稳定复用。

### 2.5 慢路径必须有预算

OCR 和 VLM 都要有预算：

- 最多多少页
- 最多多少图片
- 最多多少 region
- 最长多少秒
- 最大 token / cost
- 连续失败几次后熔断

预算优先给：

1. 低文本密度页
2. 有表格、公式、图片的页
3. parser 输出 omitted placeholder 的页
4. 用户选中的文件或章节
5. Digest 当前计划会用到的页

## 3. Ingest v2 总流程

### 3.1 总体流水线

```text
Upload
  -> Stage 0: Intake
  -> Stage 1: Safety & File Identity
  -> Stage 2: Capability Discovery
  -> Stage 3: Lightweight Classification
  -> Stage 4: ParseDecision
  -> Stage 5: Conversion Plan
  -> Stage 6: Primary Parse
  -> Stage 7: Normalize Provider Result
  -> Stage 8: Quality Arbitration
  -> Stage 9: Targeted Enhance
  -> Stage 10: Render & Persist
  -> Stage 11: Ready For Digest
```

### 3.2 Stage 0: Intake

输入：

- `subject`
- `user_id`
- 上传文件
- 用户 parser 设置
- 是否 strict
- 是否允许慢增强
- 是否允许外部 provider

输出：

- `RawFile`
- 原始文件写入 `ContentStore`
- `ingest_parse_job`

状态：

```text
pending
```

### 3.3 Stage 1: Safety & File Identity

做这些事：

1. magic bytes 判断真实文件类型。
2. extension / MIME / magic 三者交叉校验。
3. 文件大小、页数、压缩包层数预检。
4. 判断是否加密、损坏、空文件。
5. 文本文件试读 UTF-8，非 UTF-8 做编码探测但最终统一写 UTF-8。
6. 压缩包只列目录，不立即递归解析全部内容。

输出：

```python
FileIdentity(
    extension=".pdf",
    mime="application/pdf",
    magic_family="pdf",
    size_bytes=...,
    is_encrypted=False,
    is_archive=False,
    is_probably_text=False,
)
```

状态：

```text
classifying
```

建议落点：

- 通用 magic sniff 可放 `shared.infra.filetypes`
- Ingest 专属 identity 模型放 `workflows/ingest/common/parsing`

### 3.4 Stage 2: Capability Discovery

每次解析前构建 provider 能力矩阵：

```python
ProviderCapability(
    name="mineru",
    available=True,
    supported_extensions={".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"},
    features={"layout", "ocr", "table", "formula", "markdown", "blocks"},
    cost_level="external",
    latency_level="slow",
    quality_level="high",
    max_file_mb=...,
    max_pages=...,
)
```

Provider 至少包括：

- `local_text`
- `local_code`
- `local_markdown`
- `local_pdf_fast`
- `local_pdf_quality`
- `local_office`
- `local_spreadsheet`
- `local_html`
- `local_epub`
- `local_email`
- `local_archive`
- `mineru`
- `deepdoc_service`
- `docling_service`
- `ocr_provider`
- `multimodal_provider`
- `asr_provider`
- `video_keyframe_provider`

建议落点：

- provider contract: `workflows/ingest/common/parsing/provider_contracts.py`
- provider registry: `workflows/ingest/common/parsing/provider_registry.py`
- 外部 provider 实现：`workflows/ingest/common/parsing/providers/`
- 通用 HTTP / execution / sandbox 能力继续用 `shared.infra`

### 3.5 Stage 3: Lightweight Classification

这一步必须快，不做慢模型调用。

PDF 采样：

- 页数
- 每页字符密度
- 图片占比
- drawing / formula 线索
- 表格线索
- 是否双栏
- 是否乱码字体
- 是否扫描件

Office 采样：

- 段落数
- 标题数
- 表格数
- 图片数
- slide 数
- 是否大量截图

图片采样：

- 尺寸
- 色彩
- 是否可能是文档截图
- EXIF 方向
- 模糊度

文本类采样：

- 编码
- 行数
- Markdown headings
- 代码语言
- 表格语法
- 图片引用

输出：

```python
MaterialProfile(
    file_family="pdf",
    estimated_pages=88,
    text_density="low",
    layout_complexity="high",
    has_tables=True,
    has_formulas=True,
    has_figures=True,
    is_scanned=True,
    maybe_garbled=False,
    recommended_quality="quality",
)
```

### 3.6 Stage 4: ParseDecision

这是 Ingest v2 的大脑。

```python
ParseDecision(
    primary_provider="mineru",
    primary_reason="用户显式选择 MinerU，且当前 MinerU capability 支持 .pdf。",
    conversion_plan=[],
    fallback_chain=["local_pdf_fast", "ocr_provider", "multimodal_provider"],
    enhance_plan=[],
    strict=False,
    can_preview_before_primary=False,
)
```

#### 决策规则：用户选择 MinerU

```text
if parser_provider == "mineru":
  if mineru.available and mineru.supports(extension):
    primary = mineru
  elif mineru.available and ConversionBroker.can_convert(extension, mineru.supported_extensions):
    primary = convert -> mineru
  elif strict:
    fail("MinerU 不支持该文件类型，且 strict 模式禁止回退")
  else:
    primary = best_local_provider
    enhance = best_slow_provider_if_needed
```

#### 决策规则：Auto

```text
if text-like and no external assets:
  primary = local_text
elif code/config:
  primary = local_code
elif markdown:
  primary = local_markdown
elif image:
  primary = mineru if high_quality_enabled and supports
         else ocr_provider
         else multimodal_provider
elif pdf:
  if complex/scanned/formula/table and mineru available:
    primary = mineru
  elif simple text:
    primary = local_pdf_fast
    enhance = local_pdf_quality
  else:
    primary = local_pdf_fast
    enhance = deepdoc/docling/ocr/vlm by budget
elif office:
  if mineru available and supports:
    primary = mineru when quality_mode != fast
  else:
    primary = local_office
    enhance = image/table regions only
elif spreadsheet:
  primary = local_spreadsheet
  enhance = chart/image OCR/VLM
else:
  primary = conversion_broker -> best provider
```

### 3.7 Stage 5: Conversion Plan

为了支持更多格式，需要专门的 `ConversionBroker`。

转换不是 parser，转换只负责把“不好解析的格式”变成“高质量 provider 能处理的格式”。

```text
doc -> docx / pdf / text
ppt -> pptx / pdf / images
pptx -> pdf / slide images / markdown
xls -> xlsx / csv / html
html -> markdown / text
epub -> html / markdown
heic -> jpg / png
audio -> wav
video -> audio + keyframes
archive -> extracted file tree
```

转换分级：

| 等级 | 含义 | 自动执行 |
| --- | --- | --- |
| safe | 基本不丢内容 | 是 |
| acceptable | 可能丢样式，但有利于解析 | quality 模式可执行 |
| risky | 可能改变阅读顺序或语义 | 需要用户确认或 strict=false |

建议落点：

- Ingest 决策层：`workflows/ingest/common/conversion`
- 具体命令执行：`shared.infra.execution`
- 临时文件与 ContentStore：`shared.infra.storage`

### 3.8 Stage 6: Primary Parse

Primary Parse 有三类。

#### A. Trusted Provider Lane

适用于：

- 用户显式选择 MinerU
- Auto 模式判断 MinerU/Docling/DeepDoc 明显更优
- 图片 OCR provider

流程：

```text
run provider
  -> provider raw output
  -> collect assets
  -> collect blocks
  -> collect provider metadata
```

特点：

- 可以不先产出 fast preview
- 进度要清楚展示：上传 provider、排队、解析、下载、规范化
- 失败后按 fallback_policy 回退

#### B. Local Fast Lane

适用于：

- 文本
- 代码
- Markdown
- 简单 PDF
- 本地可稳定解析的 Office / Spreadsheet

流程：

```text
local parser
  -> markdown draft
  -> assets
  -> coarse blocks
  -> fast_parsed
  -> enqueue enhance if needed
```

特点：

- 尽快给用户预览
- 后续增强不阻塞 Digest 的初步可用性

#### C. Recursive Lane

适用于：

- zip / tar / rar / 7z
- email attachments
- notebook embedded images
- Office embedded files

流程：

```text
extract manifest
  -> safety limits
  -> each child file creates child RawFile or child ParseUnit
  -> parent markdown renders child summaries and links
```

不要把压缩包内容直接拼成一个大 Markdown，否则来源、权限、失败恢复都会乱。

### 3.9 Stage 7: Normalize Provider Result

所有 provider 都输出统一包：

```python
ParsePackage(
    raw_file_id=...,
    provider="mineru",
    markdown_draft="...",
    blocks=[...],
    assets=[...],
    page_map=...,
    outlines=[...],
    quality_signals=...,
    metadata=...,
)
```

关键点：

- Markdown 是展示层，不是唯一事实来源。
- block 是证据层。
- asset 是媒体层。
- page_map 是溯源层。
- quality_signals 是仲裁层。

### 3.10 Stage 8: Quality Arbitration

RAGFlow 通常选择一个 parser 后直接 chunk。我们可以做得更好：允许多个候选稿竞争和合并。

候选稿：

```text
Candidate A: MinerU
Candidate B: Local PDF text
Candidate C: OCR pages
Candidate D: VLM figure descriptions
Candidate E: pdfplumber tables
```

质量指标：

- 页覆盖率
- 字符密度
- 标题数量
- 表格数量
- 公式数量
- 图片引用完整性
- 乱码比例
- OCR 平均置信度
- 重复页眉页脚比例
- 空白页比例
- block reading order 连续性

仲裁策略：

```text
if primary passes all gates:
  use primary
elif primary mostly good but missing tables:
  use primary + replace/append table blocks
elif primary text bad but OCR good:
  use OCR text for affected pages
elif local text good and provider media good:
  merge local text + provider media blocks
else:
  keep best available draft, mark enhance_failed with report
```

### 3.11 Stage 9: Targeted Enhance

增强不是“重跑一遍全部文件”，而是针对候选区域。

候选区域生成：

```text
low_text_pages
garbled_pages
image_assets
figure_regions
table_regions
formula_regions
omitted_placeholders
large_screenshot_regions
```

OCR 用于：

- 扫描页
- 图片中文字
- 乱码字体页
- 表格截图
- 公式截图的基础文本

VLM 用于：

- 图表解释
- 流程图
- 复杂插图
- 需要语义描述的图片
- OCR 无法理解的公式或示意图

不要让 VLM 做：

- 普通文本 PDF 全文提取
- 大量表格逐页识别
- 已能本地解析的代码/文本

### 3.12 Stage 10: Render & Persist

最终持久化内容：

```text
raw_markdowns/<file_id>.md
assets/<file_id>/*
parse_blocks/<file_id>.json
parse_report/<file_id>.json
page_map/<file_id>.json
raw_file_asset rows
raw_file.parse_metadata_json
raw_file.quality_score
```

Markdown renderer 规则：

- title block 渲染成标题。
- table block 渲染成 Markdown table 或 HTML table。
- figure block 渲染图片引用 + caption + VLM/OCR 描述。
- equation block 尽量渲染 LaTeX；失败则图片 + OCR 描述。
- 每个重要 block 保留隐藏 source marker，方便后续 citation。

示例：

```markdown
## 第二章 导数

<!-- source:file=12;block=b_0021;page=7;bbox=... -->
导数描述函数在某一点附近的瞬时变化率。

<!-- source:file=12;block=b_0030;page=9;type=figure -->
![图 2-1](../assets/12/fig_2_1.png)

图示说明：切线斜率随 x 变化而变化。
```

### 3.13 Stage 11: Ready For Digest

Digest 不再只读 Markdown，推荐读取：

```text
Markdown: 生成知识文档主输入
ParsedBlock: 保留结构、页码、证据类型
ParseReport: 判断资料质量和缺口
AssetManifest: 图表、公式、截图
```

这样 Digest 可以做：

- 只用高质量 blocks 做教材正文
- 对表格/公式/图生成专门教学片段
- 在证据不足处触发 research
- 给 Interact/Examine 留 citation anchor

## 4. 支持格式目标

### 4.1 第一梯队：必须稳定支持

| 类别 | 扩展名 | 主路径 |
| --- | --- | --- |
| PDF | `.pdf` | MinerU / LocalPDF / DeepDoc / Docling |
| Word | `.docx`, `.doc` | MinerU 或 LocalOffice，`.doc` 可转换 |
| PPT | `.pptx`, `.ppt` | MinerU 或 LocalSlides，必要时转 PDF |
| 表格 | `.xlsx`, `.xls`, `.csv`, `.tsv` | LocalSpreadsheet，MinerU 可选 |
| 文本 | `.txt`, `.md`, `.markdown`, `.mdx` | LocalText |
| 代码 | `.py`, `.js`, `.ts`, `.tsx`, `.java`, `.go`, `.rs`, `.cpp`, `.c`, `.h`, `.cs`, `.kt`, `.sql`, `.sh` | LocalCode |
| 图片 | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.tif`, `.tiff` | MinerU / OCR / VLM |
| HTML | `.html`, `.htm` | LocalHTML / MinerU 可选 |

### 4.2 第二梯队：应该支持

| 类别 | 扩展名 | 主路径 |
| --- | --- | --- |
| 结构化数据 | `.json`, `.jsonl`, `.yaml`, `.yml`, `.toml`, `.xml` | LocalStructured |
| 电子书 | `.epub`, `.mobi`, `.azw3` | LocalEpub 转 HTML/Markdown |
| 邮件 | `.eml`, `.msg` | LocalEmail + 附件递归 |
| Notebook | `.ipynb` | LocalNotebook 转 Markdown |
| OpenDocument | `.odt`, `.odp`, `.ods` | LibreOffice 转换后解析 |
| 富文本 | `.rtf` | 转 docx/text |
| 压缩包 | `.zip`, `.tar`, `.gz`, `.7z`, `.rar` | Archive manifest + 递归 parse |

### 4.3 第三梯队：增强支持

| 类别 | 扩展名 | 主路径 |
| --- | --- | --- |
| 音频 | `.mp3`, `.wav`, `.m4a`, `.flac`, `.aac`, `.ogg` | ASR |
| 视频 | `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi` | ASR + keyframes + VLM |
| 图片新格式 | `.heic`, `.avif` | 转 jpg/png 后 OCR/VLM |
| 扫描集合 | 多图上传 / zip images | 合并成 document package |

## 5. Provider 设计

### 5.1 Provider 分层

```text
DocumentParseProvider
  LocalTextProvider
  LocalMarkdownProvider
  LocalCodeProvider
  LocalPdfFastProvider
  LocalPdfQualityProvider
  LocalOfficeProvider
  LocalSpreadsheetProvider
  LocalHtmlProvider
  LocalEpubProvider
  LocalEmailProvider
  MinerUProvider
  DeepDocProvider
  DoclingProvider
  OCRProvider
  MultimodalProvider
  ASRProvider
  VideoProvider
```

### 5.2 Provider 能力

```python
class ProviderCapability(BaseModel):
    name: str
    available: bool
    supported_extensions: set[str]
    accepted_inputs: set[str]
    output_features: set[str]
    quality_level: Literal["low", "medium", "high"]
    latency_level: Literal["fast", "medium", "slow"]
    cost_level: Literal["free", "local", "external", "llm"]
    max_file_mb: int | None = None
    max_pages: int | None = None
```

### 5.3 推荐目录位置

```text
workflows/ingest/
  application/
    parse_files.py
    ingest_jobs.py
  common/
    parsing/
      provider_contracts.py
      provider_registry.py
      decision.py
      quality.py
      renderer.py
      canonicalizer.py
      providers/
        local_text.py
        local_pdf.py
        local_office.py
        local_spreadsheet.py
        mineru.py
        deepdoc.py
        docling.py
        ocr.py
        multimodal.py
    conversion/
      broker.py
      office.py
      media.py
      archive.py
    media/
      image_probe.py
      page_render.py
      candidate_regions.py
  fast_parse/
  deep_enhance/
```

可放 `shared.infra` 的能力：

- `shared.infra.execution`: 安全执行 LibreOffice、pandoc、ffmpeg、poppler 等外部命令
- `shared.infra.storage`: ContentStore、临时目录、对象存储
- `shared.infra.config`: provider 配置和开关
- `shared.infra.observability`: provider 调用 trace

不要放 `shared.infra` 的内容：

- provider 选择策略
- 文件解析业务流程
- Digest 准入规则
- 教学语义

## 6. 关键算法

### 6.1 ParseDecision 评分

Auto 模式可以用评分：

```text
score =
  expected_quality
  + user_preference_bonus
  + feature_match_bonus
  + reliability_bonus
  - latency_penalty
  - cost_penalty
  - conversion_risk_penalty
```

示例：

```text
扫描 PDF:
  MinerU: quality high, cost external, score 88
  LocalPDF: quality low, cost local, score 45
  OCR: quality medium, cost local/external, score 72
  VLM: quality medium, cost llm, score 50
  -> MinerU

纯文本 Markdown:
  LocalMarkdown: quality high, cost free, score 98
  MinerU: quality medium, cost external, score 40
  -> LocalMarkdown
```

### 6.2 Quality Gate

```text
pass if:
  markdown_chars >= min_expected_chars
  missing_page_ratio <= threshold
  garbled_ratio <= threshold
  image_refs_valid
  if has_tables: table_count > 0 or table_fallback_reason exists
  if has_formulas: equation_count > 0 or formula_images exist
```

失败后不要立刻整体失败，而是进入 targeted enhance。

### 6.3 合并策略

```text
for each page:
  choose best text source
  merge table blocks
  merge figure/equation descriptions
  preserve source provider metadata
  sort by reading_order/page/bbox
```

优先级：

```text
text:
  MinerU/DeepDoc good text
  local PDF good text
  OCR text
  VLM text

table:
  MinerU table
  DeepDoc TSR table
  Docling table
  pdfplumber table
  VLM table description

figure:
  original asset
  caption
  nearby text
  VLM description
```

## 7. 进度事件

前端不必展示所有内部状态，但 progress 应该表达真实流程：

```text
ingest.queued
ingest.inspecting
ingest.deciding_provider
ingest.converting
ingest.primary_parse.running
ingest.primary_parse.completed
ingest.normalizing
ingest.quality_checking
ingest.fast_preview.ready
ingest.enhance.queued
ingest.enhance.running
ingest.enhance.ocr
ingest.enhance.vlm
ingest.enhance.merging
ingest.ready_for_digest
ingest.failed
```

用户看到的是：

```text
正在检查文件
正在选择解析方式
正在使用 MinerU 解析
正在生成预览
正在补全图表和扫描页
资料已准备好
```

## 8. 与五大引擎的连接

### 8.1 Digest

Digest 读取：

- final Markdown
- ParsedBlock
- ParseReport
- AssetManifest

Digest 可以更聪明：

- 章节大纲优先使用 title/list/text blocks
- 图表教学使用 figure/table blocks
- 公式教学使用 equation blocks
- 质量不足的页触发 research supplement

### 8.2 Interact

Interact 使用：

- block citation
- page image crop
- table source
- figure source

效果：

```text
用户问“这张图是什么意思”
  -> 找到 figure block
  -> 展示原图 + OCR/VLM 描述 + 周边正文
```

### 8.3 Examine

Examine 使用：

- table blocks 生成读表题
- equation blocks 生成推导题
- figure blocks 生成图像理解题
- text blocks 生成概念题

### 8.4 Profile

Profile 可以记录：

- 用户在哪类 block 上错得多
- 文本概念 vs 表格分析 vs 公式推导 vs 图像理解
- 不只是知识点掌握度，还能有材料类型掌握度

## 9. 推荐取舍

### 9.1 应该删掉或重做的旧思路

建议逐步废弃这些想法：

1. 单一 `needs_enhance`。
2. provider 只是 runtime 特例。
3. provider 输出直接写 Markdown。
4. OCR/VLM 全页默认调用。
5. 只用 `quality_score` 一个浮点数表达质量。
6. Phase 2 只有内存 task。

### 9.2 应该保留的旧思路

应该保留：

1. Phase 1 快速预览。
2. Phase 2 后台增强。
3. `ContentStore` 统一产物。
4. `RawFile.ingest_status` 状态。
5. MinerU token 不长期落盘。
6. Digest 可消费 `fast_parsed / enhancing / ready_for_digest / enhance_failed` 的宽松策略。

## 10. 最终推荐流程

最终流程应该是：

```text
1. 用户上传文件
2. 系统保存原始文件和 RawFile
3. Ingest job 进行安全预检和文件识别
4. ProviderRegistry 发现可用能力
5. Classifier 生成 MaterialProfile
6. ParseDecision 决定主 provider、转换、fallback、增强预算
7. 如果用户选择 MinerU 且支持：
     直接 MinerU
8. 如果用户选择 MinerU 但不支持：
     能安全转换就转换后 MinerU
     不能转换就按 strict/fallback 策略处理
9. 如果 Auto：
     文本/代码/Markdown 本地直通
     简单 PDF 本地 fast + quality reparse
     复杂 PDF/Office/图片选择最佳 provider
10. ProviderResult 归一化成 ParsedBlock / ParsedAsset / PageMap
11. QualityArbiter 判断是否合格
12. 不合格则 targeted enhance：
     OCR 低文本页
     VLM 图表/公式/插图
     local parser 补表格/图片
13. 合并候选结果
14. 渲染 final Markdown
15. 持久化 Markdown、assets、blocks、report
16. 状态进入 ready_for_digest
```

这套流程比当前方案更强，因为它从“解析器链”升级成了“文档理解 DAG”。

这套流程也比 RAGFlow 更适合 AITeachMe，因为它不止服务 chunk，而是从一开始就保留了教学所需的结构、证据、质量和材料类型信息。

