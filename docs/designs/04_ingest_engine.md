# 04. Ingest 引擎

## 1. 文档定位

本文档描述当前 ingest 的真实设计：

- 保留远程分支的两阶段加速方法
- 保留本地分支的数据库与目录落点
- 明确 ingest 什么时候能被 Digest 消费

---

## 2. Ingest 的职责边界

Ingest 只负责把原始资料转换成稳定的“材料层”：

- 原始文件落盘
- 分类与解析策略选择
- 产出标准化 Markdown
- 提取图片等资产
- 在后台做可选 OCR / 深度增强
- 回写 `raw_file`

Ingest 不直接产出知识图谱或课程结构。

---

## 3. 当前实现落点

| 层 | 当前模块 |
| --- | --- |
| 前端 | `frontend/src/pages/FilesPage.tsx` |
| API | `backend/app/api/files.py` |
| service | `backend/app/services/file_service.py` |
| workflow | `backend/app/workflows/ingest/*` |
| 路径 helper | `backend/app/utils/path_helpers.py` |
| 主要业务表 | `raw_file` |

---

## 4. 当前真实流程

### 4.1 Phase 0：上传与分发

`file_service` 在上传时完成：

1. 写入原始文件到 `raw_files/`
2. 创建 `raw_file`
3. 预先生成 `markdown_path` 与 `asset_dir`
4. 把 `digest_current_step` 标成 `ingest.parse.queued`
5. 触发后续解析 workflow

### 4.2 Phase 1：Fast Parse

Fast Parse 是前台可感知阶段，目标是尽快把文件转成可预览 Markdown。

当前主流程是：

`load_raw_file -> compute_fingerprint -> classify_file -> plan_parse -> parse_file -> finalize_success`

关键特征：

- 不在这个阶段做重型 LLM OCR
- 优先用传统解析器快速拿到可读结果
- 结果写回 `raw_markdowns/<file_id>.md`

#### 文本文件 Fast Path

纯文本 / Markdown / 代码文件会直接走快速通道：

- 读取文本
- 直接写 `raw_markdowns/<file_id>.md`
- 直接标记 `ready_for_digest`

这类文件不会再进入 Phase 2。

### 4.3 Phase 2：Deep Enhance

Deep Enhance 是后台阶段，目标是补强 Phase 1 的材料质量。

当前后台任务 `_run_deep_enhance_background()` 会做：

1. 对 PDF 做质量重解析
2. 如果配置了视觉模型，则对资产图像做 OCR 补强
3. 覆盖回同一个 `raw_markdowns/<file_id>.md`
4. 把状态推进到 `ready_for_digest`

如果 Phase 2 失败：

- Phase 1 产物仍然保留
- `raw_file.ingest_status = enhance_failed`
- 系统可继续展示材料，但 Digest 默认不应当把它当作完全就绪文件

---

## 5. 当前状态机

当前 `IngestStatus` 为：

- `pending`
- `classifying`
- `fast_parsing`
- `fast_parsed`
- `enhancing`
- `ready_for_digest`
- `enhance_failed`
- `retry_pending`
- `failed`

状态含义：

- `fast_parsed`：前端已经可以预览材料
- `ready_for_digest`：下游 digest 可以正式消费
- `enhance_failed`：Phase 1 可用，但后台增强失败

---

## 6. 当前正式文件产物

单个文件 ingest 完成后，运行时产物位于：

- `data/<subject>/raw_files/<raw_file_id>.<ext>`
- `data/<subject>/raw_markdowns/<raw_file_id>.md`
- `data/<subject>/assets/<raw_file_id>/*`

关键说明：

- 当前资产目录是“subject 级 `assets/` 根目录 + 单文件子目录”
- Markdown 中的资源引用按 `../assets/<file_id>/...` 组织
- Phase 1 和 Phase 2 写的是同一份 `raw_markdowns/<file_id>.md`

---

## 7. 解析策略

### 7.1 文本类

文本类文件优先用本地文本解析，直接就绪。

### 7.2 PDF / DOCX / PPTX

这类文件先走传统解析：

- `pymupdf_native`
- `pymupdf4llm`
- `pdfplumber`
- `markitdown`
- `mammoth`
- `python-pptx`

Fast Parse 结束后，再根据需要进入后台增强。

### 7.3 图片

图片类文件直接依赖视觉能力，不走传统文本解析链。

### 7.4 音频

当前支持音频转写，但有运行时约束：

- WAV / FLAC / AIFF 可直接尝试转写
- MP3 / M4A / OGG / AAC / WMA / OPUS 等压缩格式需要 `pydub + ffmpeg`

如果环境里没有 `ffmpeg`，压缩音频应明确报错，而不是伪装成“可用”。

---

## 8. Ingest 与 Digest 的桥接

Digest 消费的不是 `RawFile` 本身，而是：

`raw_file -> raw_markdowns / assets -> retrieval_chunk`

因此 ingest 对 digest 的核心契约是：

1. `raw_file` 状态必须正确
2. `raw_markdowns/<file_id>.md` 必须存在
3. 资产目录必须稳定
4. 只有 `ready_for_digest` 文件才进入主 digest 流程

---

## 9. 这次 merge 后的最终原则

1. 两阶段 ingest 方法层以远程分支方案为准。
2. `raw_file`、目录 helper、文件落点以本地重构为准。
3. 任何新的 ingest 优化，都不能再把数据库拉回旧的多表版本设计。
4. 任何文档说明，都必须以 `utils/path_helpers.py` 的真实目录命名为准。

---

## 10. 一句话结论

当前 ingest 的真实设计就是：

- Phase 0 上传与排队
- Phase 1 快速解析并尽快给前端可预览结果
- Phase 2 后台静默增强并决定是否可进入 Digest

方法层保留远程加速思路，数据层继续服从本地收敛后的 schema 和目录结构。
