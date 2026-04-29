# Ingest 透视引擎链路说明

最后更新：2026-04-17

`ingest/` 负责把用户上传的原始文件变成 Digest 可以消费的标准化 Markdown 与资产目录。它不做教学规划、不生成知识文档、不构建知识图谱，只保证“资料可读、可预览、可检索、可继续增强”。

## 一句话总览

Ingest 做的事就是：把当前开放上传的 PDF、DOCX、Markdown、文本先转成可预览 Markdown；复杂 PDF/OCR 资料优先交给 PaddleOCR 或 MinerU，本地兜底收敛到 MarkItDown。

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
| 7 | 后台增强 | 后台按需执行 Vision OCR 资产增强，成功后覆盖 Markdown 与资产，失败则保留 Phase 1 结果 | 在不阻塞用户预览的前提下，提高复杂资料的可读性和可检索性 | `_run_deep_enhance_background`、`deep_enhance_file` |
| 8 | 增强恢复 | 服务启动后扫描 `fast_parsed` / `enhancing` 文件并重新派发增强任务 | 减少服务重启导致的后台增强任务丢失 | `recover_stalled_enhancements`、`background_task_registry` |

## 当前 canonical 结构

```text
ingest/
  __init__.py
  README.md
  intake/
    catalog.py
    uploads.py
    parse_dispatch.py
    deletion.py
  fast_parse/
    graph.py
    state.py
    nodes/
    lib/
      enhance.py
      recovery.py
  parsing/
```

说明：

- `__init__.py` 只提供稳定导入面，不承载业务实现。
- `intake/` 承接上传、列表、删除和 parse 派发等 Phase 0 文件接入用例。
- `fast_parse/` 是 Phase 1 快速解析链路。
- `fast_parse/graph.py` 是单文件 parse workflow 的真实入口，并负责统一 graph/state/node 的运行收口。
- `fast_parse/lib/enhance.py` 承接 Phase 2 后台增强 worker。
- `fast_parse/lib/lifecycle.py` 承接 graph 外的失败兜底和 Phase 2 派发。
- `fast_parse/lib/recovery.py` 承接增强恢复。
- `parsing/` 放分类、策略、解析器、Markdown 规范化与 OCR 实现。

当前真实运行主线以 `fast_parse/graph.py::run_parse_file_workflow()` 和 `fast_parse/lib/enhance.py::_run_deep_enhance_background()` 为准。Ingest 只有 `fast_parse` 一条 workflow graph；后台增强只是 parse 完成后的异步补强步骤，不再作为第二条 LangGraph lane。

## 容易误会的功能

- workflow export 不再放 `common/exports.py`。各 lane 的 `graph.py` 自己声明 `WORKFLOW_EXPORTS`，根 `ingest.__init__` 只做聚合，供 LangGraph Studio 和 `backend/scripts/generate_workflow_diagrams.py` 使用。
- Ingest 不再保留事件层。当前没有明确订阅方，状态推进、`digest_current_step` 和日志已经覆盖运行时观测需求。
- `parsing/provider_contracts.py` 只保留当前 `ParseDecision` 需要的 provider 能力与路由契约。未来 `ParsedBlock / PageMap / ParseReport` 仍在设计文档中，不提前放进代码主线。
- LangGraph 节点 id 保持英文 `snake_case`，LangSmith 展示名使用中文阶段名；不要把节点 id 改成中文。

## 对外入口

解析图的稳定入口：

```python
from app.workflows.ingest import run_parse_file_workflow
```

上传、列表、删除和批量解析派发等 API-facing 文件用例从 `app.workflows.ingest.intake` 导入。

如果只看图结构，可以看：

- `app.workflows.ingest.fast_parse.graph`

## 端到端链路

```text
前端上传文件
  -> api/files.py
  -> workflows/ingest/intake/uploads.py
  -> 保存 raw_file 记录与原始文件
  -> background_task_registry.spawn(run_parse_files_background)
  -> run_parse_file_workflow
  -> Phase 1 fast parse
  -> ingest/intake/parse_dispatch.py 按最终 state 必要时派发 Phase 2 deep enhance
  -> raw_file.ingest_status 进入 Digest 可消费态
```

## Phase 0：上传与排队

入口在 `workflows/ingest/intake/uploads.py`。

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
2. 如果请求里没有 token，则通过 `get_env()` 读取运行时配置：本地模式下设置页保存到 DB 的值优先，其次才是 `.env` / 部署环境变量里的 `MINERU_API_TOKENS` 或 `MINERU_API_TOKEN`，支持英文逗号分隔多个 token 并随机选择一个。
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

非文本文件先走 `parsing/classifier.py::classify_file()`。

分类器是轻量、无 LLM 的特征判断：

- PDF：不再加载本地 PDF 引擎做页级采样，默认推荐 MarkItDown 本地兜底；复杂 OCR/Layout 场景交给 PaddleOCR 或 MinerU。
- DOCX：扫描段落、标题、结构。

分类结果会写回：

- `classification_json`
- `detected_language`
- `estimated_pages`
- `ingest_status = fast_parsing`
- `digest_current_step = ingest.fast_parse.running`

### 5. 常规通道：制定解析计划

`parsing/strategy.py::build_parse_plan()` 根据分类结果生成 `ParsePlan`：

- `mode`：解析模式，例如 `local_markitdown`、`balanced_docx`。
- `parser_chain`：解析器尝试顺序。
- `decision_reason`：人类可读的决策原因。
- `options`：超时、图片提取上限、OCR 并发、语言模式等运行参数。

如果前端显式选择 MinerU，则直接生成：

```text
mode = external_mineru
parser_chain = ["mineru"]
```

### 6. 常规通道：执行解析

本地解析走 `parsing/orchestrator.py::fast_parse_file()`：

```text
parser_chain 按顺序尝试
  -> 当前 parser 成功则进入 canonicalize_markdown
  -> 当前 parser 超时/报错则尝试下一个 parser
  -> 全部失败则 Phase 1 失败
```

Markdown 规范化会做：

- 图片引用改写为相对资产路径（例如同一文件目录下的 `assets/...`）
- base64 data URI 图片抽取成真实资产文件
- 追加未被正文引用但已提取的资产图片
- 统计 `rewritten_image_refs / extracted_data_images / appended_asset_images`

PaddleOCR / MinerU 分支会先把外部解析输出的 Markdown 和图片复制到当前规范资产目录，再走同一套 canonicalize 逻辑。外部解析默认不再触发 Phase 2。

### 7. Phase 1 持久化

解析成功后统一写入：

- `raw_file.markdown_path` 指向的 `markdown.md`
- `raw_file.asset_dir` 指向的 `assets/`
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

Phase 2 由 `ingest/intake/parse_dispatch.py` 在 Phase 1 成功后按最终 state 派发。API 运行时优先进入 `background_task_registry`；脚本或非 API 调用场景仍保留 `_background_tasks` 兜底引用，避免 task 被回收。

### 1. 加载增强上下文

1. 读取 `raw_file`。
2. 物化原始文件。
3. 读取 Phase 1 Markdown。
4. 从 ContentStore 物化 Phase 1 已提取资产到临时工作目录，确保后续 OCR 能看到真实图片。
5. 从 `classification_json` 恢复分类结果。
6. 重建 `ParsePlan`。
7. 设置 `ingest_status = enhancing`。

### 2. Vision OCR 增强

如果配置了“文档 OCR 模型”（`settings.models.ocr`）：

1. 扫描 Markdown 图片引用。
2. 对图片资产调用 LLM Vision OCR。
3. 用 OCR 结果替换或补充图片占位内容。

如果没有配置文档 OCR 模型，则跳过 OCR，只保留 Phase 1 Markdown。

### 3. Phase 2 持久化

成功后：

- 覆盖 raw Markdown。
- 上传增强阶段工作目录中的资产到 `raw_file.asset_dir`。
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
   已有 `content_hash`，但当前上传后仍会进入解析。可以在同 course 下发现同 hash 产物时复用 Markdown 与资产，减少重复解析成本。

3. **把解析质量评估从启发式升级为可解释评分**
   当前 `quality_score` 是简单规则。后续可增加 Markdown 结构、图片覆盖、公式/表格保真度、OCR 低置信段落等维度。

## 一句话总结

Ingest 当前是“两阶段解析”：Phase 1 先给可用 Markdown，Phase 2 后台尽量把复杂 PDF 和图片资料补强。它的优化重点不是更会教学，而是更稳、更快、更可恢复地把资料变成 Digest 的标准输入。
