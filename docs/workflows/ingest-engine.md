# 04. Ingest 透视引擎

最后更新：2026-04-19

Ingest 负责把用户上传的原始资料变成 Digest 可以消费的标准化 Markdown 与资产目录。

Ingest 不做教学规划、不生成知识文档、不构建知识图谱、不出题。

## 1. 当前职责

```text
RawFile
  -> raw_markdowns/<file_id>.md
  -> assets/<file_id>/*
  -> RawFile / RawFileAsset 元数据
  -> ready_for_digest
```

核心目标：

- 快速产出可预览 Markdown。
- 尽量保留图片、表格、公式、扫描件文字。
- 保证 Digest 后续能读到稳定材料。

## 2. 真实入口

上传入口：

- `backend/app/api/files.py`
- `backend/app/workflows/ingest/intake/uploads.py`

解析入口：

- `app.workflows.ingest.run_parse_file_workflow`
- `backend/app/workflows/ingest/fast_parse/graph.py`

后台增强：

- `backend/app/workflows/ingest/fast_parse/lib/enhance.py`
- `backend/app/workflows/ingest/fast_parse/lib/lifecycle.py`
- `backend/app/workflows/ingest/fast_parse/lib/recovery.py`

## 3. 当前目录结构

```text
workflows/ingest/
  __init__.py
  README.md
  intake/
    catalog.py
    uploads.py
    parse_dispatch.py
    deletion.py
  fast_parse/
    README.md
    graph.py
    state.py
    nodes/
    lib/
      runtime_helpers.py
      enhance.py
      recovery.py
  parsing/
```

当前只有 `fast_parse` 一条真实 workflow graph。

后台增强是 Phase 1 后派发的异步补强步骤，不是第二条 LangGraph lane。

## 4. 两阶段链路

### Phase 0：上传与排队

1. 保存原始文件到 ContentStore。
2. 创建 `RawFile`。
3. 保存本次上传请求显式传入的解析参数；未显式传入时走后端代码默认行为。
4. 使用 `background_task_registry.spawn(...)` 派发解析任务。

### Phase 1：Fast Parse

1. 物化原始文件到临时目录。
2. 读取并清理解析请求里的敏感 token。
3. 文本文件直接 UTF-8 快速通道。
4. 非文本文件执行分类。
5. 根据分类结果生成 parse plan。
6. 按 parser chain 尝试解析。
7. 规范化 Markdown 图片引用。
8. 上传 raw markdown 和 assets。
9. 更新 `RawFile` 状态。

### Phase 2：Background Enhance

1. 读取 Phase 1 Markdown 和资产。
2. 对复杂 PDF 尝试质量重解析。
3. 如果配置 OCR/vision 模型，则对图片和低文本页做 OCR。
4. 成功则覆盖 Markdown / assets。
5. 失败则保留 Phase 1 结果，并标记 `enhance_failed`。

### 恢复

服务启动后会扫描：

- `fast_parsed`
- `enhancing`

并重新派发增强任务。

## 5. MinerU 规则

- 上传请求仍可显式指定 MinerU 参数，并传 `mineru_api_token`。
- 如果请求没有 token，则通过 `get_env()` 读取运行时配置：本地模式下设置页 DB 覆盖值优先，其次才是 `.env` / 部署环境变量中的 `MINERU_API_TOKENS` 或 `MINERU_API_TOKEN`，支持英文逗号分隔多个 token 并随机选择一个。
- token 不长期落 DB。
- MinerU 输出会进入同一套 Markdown/asset canonicalize 逻辑。
- PPTX 默认按 MinerU 优先：配置了 MinerU Token 时先走 MinerU；MinerU 不可用、报错或 15 秒内未完成时回退到本地 MarkItDown。

## 5.1 默认解析模式

`parser_provider` 现在不再属于项目级 settings。

- 默认行为：不显式指定 `parser_provider` 时，大多数格式进入后端代码默认的本地自动 parser chain；PPTX 会在 MinerU 已配置时优先尝试 MinerU，再回退本地 MarkItDown。
- 显式请求 `markitdown`：若当前扩展或依赖不支持，会 fallback 回本地解析。
- 显式请求 `mineru`：若 token 缺失或扩展不支持，会 fallback 回本地解析。

也就是说，解析模式现在是“请求显式指定”或“代码默认”，不再由设置页维护一套全局默认解析器偏好。

## 6. Digest 准入状态

Digest 当前允许消费：

- `fast_parsed`
- `enhancing`
- `ready_for_digest`
- `enhance_failed`

这样用户不必等待 Phase 2 才能进入构建。

## 7. 当前约束

- Ingest 不感知 Planner / DocGen / Examine / Profile。
- Ingest 不通过事件层通知下游；下游读取状态字段和 ContentStore 产物。
- `parsing/` 只放解析共享实现，不提前做大而全 provider 框架。

## 8. 后续事项

优先级从高到低：

1. Phase 2 迁移到持久化任务队列。
2. 基于 `content_hash` 做幂等复用。
3. Phase 1 临时目录清理统一化。
4. 质量评分从启发式升级为可解释评分。
5. 如需 DeepDoc / Docling 能力，只新增明确 parser adapter，不重写业务链路。

## 9. 一句话

Ingest 的正确方向是：

```text
先快、可预览、可恢复；再慢慢增强复杂资料质量。
```
