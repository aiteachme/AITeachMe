# 24. Ingest 与 DeepDoc 简版对比和收口思路

最后更新：2026-04-17

本文只回答当前最实际的问题：`backend/app/workflows/ingest` 为什么显得乱，`common` 有没有必要，以及后续要不要参考 `D:/Project0GIT/ragflow/deepdoc` 大改。

## 1. 先给结论

当前 Ingest 的产品方向没错：

```text
上传文件 -> 快速解析成 Markdown -> 必要时后台增强 -> Digest 可消费
```

它不应该在 MVP 阶段被重构成一个很重的文档理解平台。真正需要优先处理的是代码结构里已经出现的“两套真相”：

1. 旧结构里快速解析和后台增强都看起来像 canonical LangGraph。
2. 真实运行入口 `run_parse_file_workflow()` 却主要走 `fast_parse/lib/runtime.py` 里的手写流程。
3. `nodes/*.py` 多数只是转发到 `lib/*` 的兼容 wrapper。
4. `deep_enhance` 也同时存在 graph/node 实现和 `lib/background.py` 后台实现。

所以用户感觉“这里怎么写这么乱”是合理的。乱点不在业务复杂，而在入口、图、节点、runtime 的职责没有统一。

## 2. `common` 有没有必要

有必要，但只能保留一个很小的 `common/parsing`。

保留原因：

- `fast_parse` 和 `deep_enhance` 都要用分类、解析计划、parser registry、Markdown 规范化、资产 OCR。
- 这些确实是两条链路共享能力，符合 `workflows/STRUCTURE.md` 里“>=2 条链路真实复用才放 common”的规则。

但当前 `common/parsing` 里有两类东西不该继续膨胀：

- `providers.py` 这类未来式 provider registry，目前没有接入真实主流程，容易误导读代码的人。
- `provider_contracts.py` 不应继续混入未来 `ParsedBlock` / `QualitySignals`；这些应留在设计文档，等真正落地证据层时再进代码。

建议：`common` 保留，未来收口成“解析共享库”，不要把未落地的大平台抽象继续堆进去。

## 3. 和 DeepDoc 的简单对比

DeepDoc 的结构更像一个文档解析库：

```text
deepdoc/
  parser/
    pdf_parser.py
    docx_parser.py
    excel_parser.py
    ppt_parser.py
    markdown_parser.py
    json_parser.py
  vision/
    ocr.py
    layout_recognizer.py
    table_structure_recognizer.py
```

它的强项：

- PDF 解析更深，重点在 OCR、layout recognition、table structure recognition。
- 产物更接近带页面位置的文本块、表格、图片，而不只是 Markdown。
- parser 层职责清晰：每种格式一个 parser，不承担 AITeachMe 的业务状态推进。

它不适合直接照搬的地方：

- DeepDoc 是解析库，不负责 `RawFile` 状态、ContentStore、后台任务、Digest 准入。
- 它的 PDF 解析很重，直接塞进当前上传链路会让 MVP 复杂度和依赖成本明显上升。
- 它解决的是“文档结构理解”，不是“五大教学引擎”的业务编排。

对 AITeachMe 的正确参考方式：

```text
不要照搬 DeepDoc 的工程结构。
只学习它的 parser 输出思想：layout / table / figure / page position。
```

## 4. 当前重大问题排序

### P0：配置字段迁移遗漏

已修复：

- 上传大小从 `settings.max_upload_size_mb` 改为 `settings.files.max_upload_size_mb`。
- 解析并发从 `settings.ingest_parse_concurrency` 改为 `settings.ingest.parse_concurrency`。

这是会直接导致上传 500 的真实问题。

### P1：Ingest 入口不唯一

这是当前最值得重构的问题。

现在读 `graph.py` 会以为流程由 LangGraph 节点驱动，但实际主流程在 `fast_parse/lib/runtime.py` 手写执行。后续应该二选一：

- 方案 A：保留手写 runtime，把 `graph/nodes` 明确降级为 dev/export 可视化壳，不再维护第二套业务逻辑。
- 方案 B：让 `run_parse_file_workflow()` 真正调用 `run_state_graph(...)`，把手写 runtime 拆回节点。

考虑到 Ingest 当前流程不复杂，推荐先选方案 A，最小化改动。

### P1：后台增强不是持久化任务

当前 Phase 2 用 `asyncio.create_task()`。服务重启后有恢复扫描，但执行中的上下文、重试次数、退避策略不完整。

短期可以接受；如果后续解析大文件、批量文件、云部署，就应该改成 DB job 或队列。

### P1：临时目录清理不够统一

`tempfile.mkdtemp()` 创建的目录没有集中清理策略。解析多文件后会堆临时文件。

这不是架构大改，但属于明显工程债。

### P2：Provider 抽象半落地

MinerU 已经接进主流程，但 `providers.py` 里的 `ProviderRegistry / MinerUProvider / DoclingProvider` 还是占位，容易让人误以为系统已经支持 provider registry。

短期建议：

- 要么删掉未使用的 provider registry 占位。
- 要么移动到文档/实验目录，等真正接入时再回代码。

## 5. 推荐的简单目标结构

短期不要改成很复杂的 Ingest v2，先收口成这样：

```text
ingest/
  __init__.py
  README.md
  fast_parse/
    state.py
    graph.py                  # 只做 dev/export 壳，或后续真正接管 runtime
    lib/
      runtime.py              # 现阶段唯一真实 Phase 1 主流程
      enhance.py              # Phase 2 后台增强 worker
      recovery.py             # 增强恢复
  common/
    parsing/
      classifier.py
      decision.py
      strategy.py
      parsers.py
      orchestrator.py
      canonicalizer.py
      mineru_cloud.py
      pdf.py / docx.py / pptx.py / text.py / image.py
```

明确规则：

- `app.workflows.ingest.__init__` 提供唯一稳定导入面。
- `fast_parse/lib/runtime.py` 是 Phase 1 唯一真实实现，并派发后台增强。
- `fast_parse/lib/enhance.py` 是 Phase 2 后台增强唯一真实实现。
- 不单独保留 `deep_enhance/` lane，避免形成第二套 graph/state/nodes 主线。
- `common/parsing` 只放真实被 Phase 1 / Phase 2 复用的解析能力。

## 6. 后续小步修改顺序

1. 先修运行时 bug 和配置路径，不动大结构。
2. 给 `ingest/README.md` 补一句：当前真实运行主线以 `fast_parse/lib/runtime.py` 和 `fast_parse/lib/enhance.py` 为准，graph 主要用于 dev/export。
3. 清理未使用的 `providers.py` 占位抽象，或者标记为实验代码。
4. 统一临时目录生命周期，优先把 `mkdtemp()` 包成上下文或 finally 清理。
5. 如果之后要做 DeepDoc 能力，只新增一个明确 provider 或 parser adapter，不改整个业务链路。
6. 等真实需要节点级观测时，再把 runtime 拆回 LangGraph 节点，不要现在为了“架构完整”硬拆。

## 7. 一句话

Ingest 的流程本身应该保持简单。当前优先不是“做大”，而是“把入口收成一个、把没接入的抽象拿掉、把后台任务和临时文件做稳”。DeepDoc 值得学习的是解析质量和结构化输出，不是把 AITeachMe 的业务流程重写成 DeepDoc。
