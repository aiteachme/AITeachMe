# Ingest 透视引擎链路说明

最后更新：2026-04-17

`ingest/` 负责把用户上传的原始文件变成 Digest 可以消费的标准化 Markdown 与资产目录。它不做教学规划、不生成知识文档、不构建知识图谱，只保证“资料可读、可预览、可检索、可继续增强”。

## 一句话总览

Ingest 做的事就是：把上传的 PDF、Word、PPT、图片或文本先快速转成可预览 Markdown，再在后台尽量补强 OCR、图片和复杂版式质量。

## 步骤总览

| 顺序 | 步骤 | 具体做什么 | 目的 | 主要模块/工具 |
| --- | --- | --- | --- | --- |
| 0 | 上传与排队 | 保存原始文件，创建 `RawFile`，记录解析参数，并启动后台解析任务 | 把用户文件安全落盘，并把解析工作从 HTTP 请求里解耦出来 | `api/files.py`、`save_uploaded_file`、`run_parse_files_background` |
| 1 | 物化原始文件 | 从 ContentStore 把原始文件拿到本地临时目录，并读取 MinerU 等解析请求参数 | 让后续分类器和解析器可以用普通文件路径工作，同时避免 token 长期落盘 | `get_content_store`、`managed_session`、`get_env` |
| 2 | 文本快速通道 | 对 `.md`、`.txt`、代码和配置文件直接读 UTF-8 并写 Markdown | 文本文件不需要复杂解析，最快进入 `ready_for_digest` | `is_text_extension`、`categorize_text_extension`、`get_text_language_hint` |
| 3 | 文件分类 | 对 PDF、DOCX、PPTX、图片等判断文本密度、页数、语言、表格、公式和图片情况 | 先判断文件“像什么”，后面才能选合适解析策略 | `classify_file`、`ClassificationResult` |
| 4 | 制定解析计划 | 根据分类结果生成 `ParsePlan`，包括解析模式、parser chain、OCR 和资产参数 | 明确本次应该用哪些解析器、按什么顺序尝试、失败怎么 fallback | `build_parse_plan`、`ParsePlan`、`ParserRunOptions` |
| 5 | Phase 1 fast parse | 按 parser chain 快速解析，规范 Markdown 图片引用，抽取资产；MinerU 分支会走外部解析再 canonicalize | 尽快产出一版可预览、可被 Digest 消费的基础 Markdown | `fast_parse_file`、`parse_file_to_dir`、`canonicalize_markdown` |
| 6 | Phase 1 持久化 | 写 raw markdown、资产目录、`raw_file_asset` 和解析元数据 | 让前端能预览，让 Digest 能读取，让失败恢复有依据 | `cs.write_text`、`cs.upload_dir`、`replace_raw_file_assets`、`update_raw_file` |
| 7 | 后台增强 | 后台尝试 PDF 质量重解析和 Vision OCR，成功后覆盖 Markdown 与资产，失败则保留 Phase 1 结果 | 在不阻塞用户预览的前提下，提高复杂资料的可读性和可检索性 | `_run_deep_enhance_background`、`deep_enhance_file`、`parse_pdf_with_pymupdf4llm` |
| 8 | 增强恢复 | 服务启动后扫描 `fast_parsed` / `enhancing` 文件并重新派发增强任务 | 减少服务重启导致的后台增强任务丢失 | `recover_stalled_enhancements`、`background_task_registry` |

## 当前 canonical 结构

```text
ingest/
  __init__.py
  README.md
  fast_parse/
    graph.py
    state.py
    nodes/
    lib/
      enhance.py
      recovery.py
  common/
    parsing/
```

说明：

- `__init__.py` 只提供稳定导入面，不承载业务实现。
- `fast_parse/` 是 Phase 1 快速解析链路。
- `fast_parse/graph.py` 是单文件 parse workflow 的真实入口，并负责统一 graph/state/node 的运行收口。
- `fast_parse/lib/enhance.py` 承接 Phase 2 后台增强 worker。
- `fast_parse/lib/lifecycle.py` 承接 graph 外的失败兜底和 Phase 2 派发。
- `fast_parse/lib/recovery.py` 承接增强恢复。
- `common/parsing/` 放两条链路共享的分类、策略、解析器、Markdown 规范化与 OCR 实现。

当前真实运行主线以 `fast_parse/graph.py::run_parse_file_workflow()` 和 `fast_parse/lib/enhance.py::_run_deep_enhance_background()` 为准。Ingest 只有 `fast_parse` 一条 workflow graph；后台增强只是 parse 完成后的异步补强步骤，不再作为第二条 LangGraph lane。

## 容易误会的功能

- workflow export 不再放 `common/exports.py`。各 lane 的 `graph.py` 自己声明 `WORKFLOW_EXPORTS`，根 `ingest.__init__` 只做聚合，供 LangGraph Studio 和 `backend/scripts/generate_workflow_diagrams.py` 使用。
- Ingest 不再保留事件层。当前没有明确订阅方，状态推进、`digest_current_step` 和日志已经覆盖运行时观测需求。
- `common/parsing/provider_contracts.py` 只保留当前 `ParseDecision` 需要的 provider 能力与路由契约。未来 `ParsedBlock / PageMap / ParseReport` 仍在设计文档中，不提前放进代码主线。
- LangGraph 节点 id 保持英文 `snake_case`，LangSmith 展示名使用中文阶段名；不要把节点 id 改成中文。

## 对外入口

上层业务只应该调用模块稳定入口：

```python
from app.workflows.ingest import run_parse_file_workflow
```

如果只看图结构，可以看：

- `app.workflows.ingest.fast_parse.graph`

## 端到端链路

```text
前端上传文件
  -> api/files.py
  -> workflows/support/files/uploads.py
  -> 保存 raw_file 记录与原始文件
  -> background_task_registry.spawn(run_parse_files_background)
  -> run_parse_file_workflow
  -> Phase 1 fast parse
  -> support/files/parsing.py 按最终 state 必要时派发 Phase 2 deep enhance
  -> raw_file.ingest_status 进入 Digest 可消费态
```

## Phase 0：上传与排队

入口在 `workflows/support/files/uploads.py`。

1. `save_uploaded_file()` 读取上传内容，计算 SHA256，写入本地或对象存储。
2. 创建 `RawFile` 记录：
   - `status = pending`
   - `ingest_status = pending`
   - `file_path / markdown_path / asset_dir` 指向后续产物位置
   - 如果用户选择 MinerU，把解析请求参数临时写入 `parse_metadata_json`
3. `_start_parse_for_files()` 将文件推进到：
   - `status = processing`
   - `ingest_status = classifying`
   - `digest_current_step = ingest.parse.queued`
4. API 用 `background_task_registry.spawn(...)` 启动 `run_parse_files_background()`，批量解析时按 ingest 代码默认并发控制执行。

## Phase 1：Fast Parse 快速解析

真实入口是 `fast_parse/graph.py::run_parse_file_workflow()`。

### 1. 读取 RawFile 与物化原始文件

1. 从 DB 读取 `raw_file`。
2. 通过 `ContentStore.materialize(...)` 把原始文件物化到临时目录。
3. 检查文件是否存在，不存在则：
   - `status = failed`
   - `ingest_status = failed`
   - `digest_current_step = ingest.parse.failed`

### 2. 解析请求参数处理

如果 `parse_metadata_json` 里包含前端传来的 MinerU 参数：

1. 读取本次请求 token。
2. 如果请求里没有 token，则尝试从 `MINERU_API_TOKEN` 读取。
3. 立刻从 DB 里擦除 `api_token`，避免敏感信息长期落盘。
4. 后续解析结果只保留 `token_source` 这类安全诊断信息。

### 3. 文本快速通道

`.md`、`.txt`、`.py`、`.json`、`.csv` 等文本类文件不会进入分类和解析器链。

```text
文本文件
  -> read_text(encoding="utf-8", errors="replace")
  -> 代码/配置类按语言包成代码块
  -> 写 raw_markdown
  -> status = completed
  -> ingest_status = ready_for_digest
  -> 直接返回
```

这个分支完全不触发 Phase 2。

### 4. 常规通道：分类

非文本文件先走 `common/parsing/classifier.py::classify_file()`。

分类器是轻量、无 LLM 的特征判断：

- PDF：采样页文本密度、图像占比、公式密度、语言、表格特征。
- DOCX：扫描段落、标题、结构。
- PPTX：扫描 slide 文本量。
- 图片：直接标记为 image。
- xlsx/csv 等：走通用 MarkItDown 类策略。

分类结果会写回：

- `classification_json`
- `detected_language`
- `estimated_pages`
- `ingest_status = fast_parsing`
- `digest_current_step = ingest.fast_parse.running`

### 5. 常规通道：制定解析计划

`common/parsing/strategy.py::build_parse_plan()` 根据分类结果生成 `ParsePlan`：

- `mode`：解析模式，例如 `quality_pdf`、`fast_scanned_pdf`、`balanced_docx`。
- `parser_chain`：解析器尝试顺序。
- `decision_reason`：人类可读的决策原因。
- `options`：超时、图片提取上限、OCR 并发、语言模式等运行参数。

如果前端显式选择 MinerU，则直接生成：

```text
mode = external_mineru
parser_chain = ["mineru"]
```

### 6. 常规通道：执行解析

本地解析走 `common/parsing/orchestrator.py::fast_parse_file()`：

```text
parser_chain 按顺序尝试
  -> 当前 parser 成功则进入 canonicalize_markdown
  -> 当前 parser 超时/报错则尝试下一个 parser
  -> 全部失败则 Phase 1 失败
```

Markdown 规范化会做：

- 图片引用改写为 `../assets/<file_id>/...`
- base64 data URI 图片抽取成真实资产文件
- 追加未被正文引用但已提取的资产图片
- 统计 `rewritten_image_refs / extracted_data_images / appended_asset_images`

MinerU 分支会先把 MinerU 输出的 Markdown 和图片复制到当前规范资产目录，再走同一套 canonicalize 逻辑。当前 MinerU 默认不再触发 Phase 2。

### 7. Phase 1 持久化

解析成功后统一写入：

- `ContentStore.subject_scope(user_id=..., subject=...).raw_markdown_key(file_id)`
- `ContentStore.subject_scope(user_id=..., subject=...).asset_prefix(file_id)`
- `raw_file_asset` 表
- `raw_file.parsed_markdown`
- `raw_file.parser_used`
- `raw_file.parse_metadata_json`
- `raw_file.quality_score`
- `raw_file.image_count`

状态推进：

- `needs_enhance = true`：`ingest_status = fast_parsed`
- `needs_enhance = false`：`ingest_status = ready_for_digest`

Digest 当前允许消费以下状态：

- `fast_parsed`
- `enhancing`
- `ready_for_digest`
- `enhance_failed`

## Phase 2：后台增强

真实入口是 `fast_parse/lib/enhance.py::_run_deep_enhance_background()`。

Phase 2 由 `support/files/parsing.py` 在 Phase 1 成功后按最终 state 派发。API 运行时优先进入 `background_task_registry`；脚本或非 API 调用场景仍保留 `_background_tasks` 兜底引用，避免 task 被回收。

### 1. 加载增强上下文

1. 读取 `raw_file`。
2. 物化原始文件。
3. 读取 Phase 1 Markdown。
4. 从 ContentStore 物化 Phase 1 已提取资产到临时工作目录，确保后续 OCR 能看到真实图片。
5. 从 `classification_json` 恢复分类结果。
6. 重建 `ParsePlan`。
7. 设置 `ingest_status = enhancing`。

### 2. PDF 质量重解析

如果文件是 PDF 且不是 MinerU 产物，会尝试 `pymupdf4llm` 重解析。

采用条件是：新 Markdown 非空，并且长度至少达到旧 Markdown 的 50%。这样避免质量重解析失败时用短空文本覆盖 Phase 1 可用产物。

### 3. Vision OCR 增强

如果配置了“文档 OCR 模型”（`settings.models.ocr`）：

1. 扫描 Markdown 图片引用。
2. 对图片资产调用 LLM Vision OCR。
3. 用 OCR 结果替换或补充图片占位内容。
4. 对低文本密度 PDF 页做整页 fallback OCR。

如果没有配置文档 OCR 模型，则跳过 OCR，只保留质量重解析结果。

### 4. Phase 2 持久化

成功后：

- 覆盖 raw Markdown。
- 上传增强阶段工作目录中的资产到 `subject_scope.asset_prefix(file_id)`。
- 刷新 `image_count` 与资产元数据。
- 更新 `parse_metadata_json` 中的 OCR 统计。
- `ingest_status = ready_for_digest`
- `digest_current_step = ingest.enhance.completed`

失败后：

- 保留 Phase 1 Markdown。
- `ingest_status = enhance_failed`
- `digest_current_step = ingest.enhance.failed`

## 恢复链路

`fast_parse/lib/recovery.py::recover_stalled_enhancements()` 会扫描：

- `fast_parsed`
- `enhancing`

并在 FastAPI 启动生命周期中重新派发 Phase 2。API 运行时恢复任务会进入 `background_task_registry`，脚本调用时才回退到 `_background_tasks` 集合。

## 当前明显优化点

### 已处理

- `run_parse_file_workflow()` 已经切回 `fast_parse/graph.py`，真实运行路径与 LangGraph 图定义统一，不再维护一套图外手写主流程。
- 文本快通道、MinerU 分支、常规 parser chain 与最终持久化都收口到同一条 graph state 上；Phase 2 派发则回到 graph 外 lifecycle/support 边界。
- 上传触发的 Phase 2 和启动恢复任务都接入 `background_task_registry`，脚本调用保留 `_background_tasks` 兜底。
- Phase 2 会先物化 Phase 1 资产，增强后重新上传资产并同步 `image_count`，避免 Markdown 图片引用悬空。
- Phase 1 / finalize 现在也会清理本次解析的临时工作目录，避免临时文件持续堆积。

### 建议优先级 P0/P1

1. **把 Phase 2 从内存 task 迁移到持久化队列**
   现在启动后可以扫描恢复，但正在执行的上下文、失败次数、重试退避都不够完整。建议后续引入 DB job / Redis queue / Celery / Dramatiq 一类持久化任务层。

2. **增加基于 content_hash 的幂等跳过**
   已有 `content_hash`，但当前上传后仍会进入解析。可以在同 subject 下发现同 hash 产物时复用 Markdown 与资产，减少重复解析成本。

3. **把解析质量评估从启发式升级为可解释评分**
   当前 `quality_score` 是简单规则。后续可增加 Markdown 结构、图片覆盖、公式/表格保真度、OCR 低置信段落等维度。

## 一句话总结

Ingest 当前是“两阶段解析”：Phase 1 先给可用 Markdown，Phase 2 后台尽量把复杂 PDF 和图片资料补强。它的优化重点不是更会教学，而是更稳、更快、更可恢复地把资料变成 Digest 的标准输入。
