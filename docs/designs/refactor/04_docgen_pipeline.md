# 04. DocGen Pipeline

## 1. 主骨架不变

DocGen 顶层骨架继续保持：

```text
load_context
-> targeted_research
-> resolve_titles
-> pedagogy_craft
-> enrich_document
-> inject_examine
-> finalize
```

这轮不推倒 graph，只调整 ownership 和扩展点。

## 2. 当前 ownership

### 2.1 Workflow-local runtime

- `workflows/digest/docgen/runtime/research.py`
- `workflows/digest/docgen/runtime/writer.py`
- `workflows/digest/docgen/runtime/assets.py`

这些文件拥有 DocGen 业务专属的多步逻辑。

### 2.2 Infra helper

- `ContextManager`
- `SourceCurator`
- provider 级 `MermaidGenerator`
- provider 级 `ImageGenerator`

这些仍在 infra，因为它们离开 DocGen 仍可复用。

### 2.3 Teaching

- 文档 overview
- 章节学习脚手架
- effective chapter title resolver

## 3. Skillpack 接入点

### 3.1 Planner

- 用户选择 `selected_skillpacks`
- 写入 confirmed plan contract
- planner prompt 注入 strategy guidance

### 3.2 DocGen

- `load_context` 解析 selected skillpacks
- document context 中携带：
  - `selected_skillpacks`
  - `skillpack_defaults`
  - `recommended_tool_tags`
  - `skillpack_guidance`
- research runtime 与 writer runtime 按 scope 再次渲染 chapter-level guidance

## 4. Asset 处理原则

- provider 级生成能力仍在 infra
- placeholder 发现、嵌入、文档级处理回到 workflow-local runtime
- 后续如果要加 sidecar plan、交互 HTML、动画资产，继续沿 `runtime/assets.py` 扩展

## 5. 系统课 vs 速成课

### 5.1 速成课

- 重视考点抓手、题型拆解、易错提醒、速记卡
- 研究阶段优先高频题型与最后复盘价值
- 练习与例题权重更高

### 5.2 系统课

- 重视概念、结构、推理、边界、综合迁移
- 章节间结构关系更重要
- 面向 1w 字以上长文档、公式兼容、结构化知识脉络

## 6. 下一步增强，不改骨架

- research micro-loop
- asset sidecar planning
- 更细颗粒度的 chapter writing block
- 更强的公式、图示、交互 HTML 插槽
- systematic / sprint 的更严格章节 contract

## 7. Asset Sidecar 详细设计（2026-04-11 补充）

> 借鉴 DeepTutor `InteractiveAgent` 和 `GuideManager` 的产品形态。

### 7.1 Sidecar 原则

正文生成和富媒体生成必须解耦：
- 正文 `pedagogy_craft` 只在 markdown 中留占位符（`<!-- [MERMAID: ...] -->`、`<!-- [IMAGE: ...] -->`、`<!-- [INTERACTIVE: ...] -->`）
- `enrich_document` 阶段的 `runtime/assets.py` 负责展开占位符
- 每种资产类型有独立的生成 → 校验 → 重试链
- 资产失败不阻塞正文发布（降级为文字描述）

### 7.2 交互 HTML 资产（借鉴 DeepTutor InteractiveAgent）

DeepTutor 为每个知识点生成独立的交互 HTML 页面，支持：
- KaTeX 公式渲染
- 可折叠的推导步骤
- 自检小测验
- fallback 模板（生成失败时使用静态模板）

AITeachMe 的借法：
- 在 `AssetPlan` 中新增 `interactive_html` 类型
- `runtime/assets.py` 中新增 `process_interactive_placeholders()`
- 生成的 HTML 片段嵌入 markdown 的 `<details>` 或 iframe 块
- MVP 阶段只做公式推导和概念对比两种交互模板
- 使用 `TaskType.DOCGEN`、`tier=smart`（交互内容需要质量）

### 7.3 资产配额与 LangSmith 追踪

每种资产在 LangSmith 中必须作为独立 span：
- tag: `asset:mermaid` / `asset:image` / `asset:interactive_html`
- metadata: `chapter_index`、`asset_kind`、`success`
- 失败时记录 `asset_failures` 和降级策略

当前 backend-first 落地状态：
- `enrich_document` 已返回 `mermaid_block_count / image_block_count / interactive_block_count / asset_count / asset_summary`
- lane summary 已可直接统计文档级资产数量，不需要再从 markdown 文本二次猜测
- `animation` 仍保持 `contract + trace` 预留位，未进入执行链

## 8. LangSmith 要求

> 详细实现参考 `backend/app/workflows/LANGSMITH.md`

- workflow node 看主骨架
- runtime span 看 chapter-level multi-step logic
- 每步都有 digest mode / course type / retrieval profile / teaching action
- 输入输出可回放，可定位 research 与 writer 的具体问题
- asset sidecar 必须有独立 span，不埋在正文节点输出里
