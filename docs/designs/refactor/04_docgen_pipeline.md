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

## 7. LangSmith 要求

- workflow node 看主骨架
- runtime span 看 chapter-level multi-step logic
- 每步都有 digest mode / course type / retrieval profile / teaching action
- 输入输出可回放，可定位 research 与 writer 的具体问题
