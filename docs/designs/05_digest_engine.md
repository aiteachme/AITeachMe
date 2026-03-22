# 05. Digest 引擎

## 1. 文档目标

Digest 是 AITeachMe 的知识组织层，负责把材料层转换成两类可消费结果：

- 面向系统的知识图谱与课程结构
- 面向用户的知识文档

Digest 当前由 3 条并行但边界清晰的工作流组成：

- Docs workflow
- Graph workflow
- Curriculum workflow

---

## 2. 当前总体结构

| 工作流 | 输入 | 输出 | 对外协议 |
| --- | --- | --- | --- |
| Docs | Markdown 材料 | 多章节知识文档 + merged 文档 | 无 job，只查已发布结果 |
| Graph | `DocumentChunk` | 知识图谱 | 有 job |
| Curriculum | 知识图谱 | 教学单元、主题树、先修 DAG、课程快照 | 有 job |

本轮重构只去掉 Docs workflow 的 job 体系，不混改 Graph / Curriculum。

---

## 3. Docs Workflow 现状

### 3.1 对外接口

Docs workflow 当前只有两个公开入口：

- `POST /knowledge/build`
- `POST /knowledge/docs`

旧接口已删除：

- `/knowledge/docgen/build`
- `/knowledge/docgen/get`

### 3.2 对外协议原则

Docs workflow 不再对外返回：

- `job_id`
- `status`
- `progress`
- `current_step`
- `error_message`

前端通过本地进度条和 `requested_at` 轮询完成等待体验。

---

## 4. Docs Workflow 内部阶段

知识文档构建仍然是多阶段工作流，但这些阶段只存在于内部实现和日志里：

1. `docgen_loading_inputs`
2. `docgen_cleaning_inputs`
3. `docgen_planning_outline`
4. `docgen_drafting_chapter`
5. `docgen_reviewing_chapter`
6. `docgen_extracting_metadata`
7. `docgen_merging_docs`
8. `docgen_publishing_docs`

构建生命周期的关键日志为：

- `knowledge_build_requested`
- `knowledge_build_started`
- `knowledge_build_completed`
- `knowledge_build_failed`

日志上下文只保留：

- `subject`
- `requested_at`
- `chapter_index`
- `chapter_title`

轮询 `knowledge/docs` 不再刷 info 日志。

---

## 5. Docs Workflow 产物模型

### 5.1 发布形态

每次成功发布都会生成：

- `knowledge_docs/chapter_01_*.md`
- `knowledge_docs/chapter_02_*.md`
- `...`
- `knowledge_docs/merged_knowledge_base.md`
- `knowledge_docs/manifest.json`

数据库中同步维护：

- `KnowledgeDoc` published 章节记录

### 5.2 多章节与 merged

知识文档必须保持清晰层次：

- 章节文件用于清晰的结构化沉淀
- merged 文档用于最终阅读页展示

这意味着 Docs workflow 不能退化成“只写一个大摘要文件”。

### 5.3 内容质量目标

当前 Writer / Review / Metadata 流程回到 LLM 主写风格：

- Writer 负责自然讲义式写作
- Review 负责查缺漏、公式错误、结构断裂
- Review 不通过时允许整章重写一次
- Metadata 负责 summary 和 tags

规则逻辑只作为辅助：

- OCR 清洗
- 公式校验
- 基础 fallback

不能再让规则模板主导正文。

---

## 6. Docs Workflow 存储布局

### 6.1 正式发布目录

`data/<subject>/knowledge_docs/`

其中包含：

- `chapter_XX_*.md`
- `merged_knowledge_base.md`
- `manifest.json`
- `.build.lock`

### 6.2 构建中的 staging 目录

`data/<subject>/knowledge_docs/_building/`

新一轮构建先写 staging：

- `_building/chapter_XX_*.md`
- `_building/merged_knowledge_base.md`

全部成功后再一次性覆盖正式目录。

### 6.3 中间文件目录

`data/<subject>/docgen_intermediate/latest/`

这里保存：

- clean 结果
- outline 结果
- draft 中间稿
- review / metadata 辅助产物

它用于观察和调试，不是对外协议的一部分。

---

## 7. Docs Workflow 的去 Job 化设计

### 7.1 互斥控制

Docs workflow 采用 subject 级构建锁：

- `data/<subject>/knowledge_docs/.build.lock`

行为：

- `knowledge/build` 进入时原子创建锁文件
- 若已存在锁文件，返回 `409 BUILD_IN_PROGRESS`
- 成功、失败、取消时都在 `finally` 释放锁

### 7.2 发布元信息

最近一版知识文档通过 `manifest.json` 表达：

- `updated_at`
- `source_file_ids`
- `prompt`
- `chapter_count`
- `chapter_titles`

`knowledge/docs` 只读取：

- `merged_knowledge_base.md`
- `manifest.json`

### 7.3 为什么不再需要 DocGenJob

Docs workflow 的核心需求是“发布新版本文档”，不是“长期暴露后台任务状态”。

用锁 + manifest 替代 job 表后：

- API 更简单
- 前端协议更稳定
- 旧版文档不会因失败而丢失
- 多章节与 merged 可以批量原子发布

---

## 8. Graph / Curriculum 仍保留 Job

本轮不要混淆：

- Graph workflow 仍有 `GraphDigestJob`
- Curriculum workflow 仍有 `CurriculumDeriveJob`

它们仍承担：

- 可恢复后台流程
- 进度追踪
- 实体激活与清理
- 跨工作流串联

Docs workflow 已经脱离这套 job 体系。

---

## 9. 节点职责

| 节点 | 主要职责 | 典型落盘 |
| --- | --- | --- |
| `load_files_node` | 读取 Markdown 输入 | 无 |
| `cleanse_node` | 清洗 OCR / 提取噪声 | `docgen_intermediate/latest/clean_*` |
| `outline_map_node` | 提取局部标题候选 | 内存为主 |
| `outline_reduce_node` | 全局规划章节结构 | `outline_tree.json`、`chapter_assignments.json` |
| `draft_node` | 分章撰写 | `draft_*.md` |
| `review_node` | 分章审校，必要时整章重写一次 | 内存为主 |
| `metadata_node` | 提取 summary / tags | 内存为主 |
| `finalize_node` | 生成 merged、发布章节、写 manifest、重建 `KnowledgeDoc` | `_building/`、正式 `knowledge_docs/` |

---

## 10. 当前结论

Digest Docs 已完成关键边界收束：

- 无 `job_id`
- 无后端状态返回
- 保留多章节 + merged
- 保留 LLM 主写质量
- 用锁和 manifest 管理发布
