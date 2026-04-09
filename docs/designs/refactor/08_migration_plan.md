## 八、迁移落位与清理计划

> 目标：回答“后续新增能力应该落到哪里、哪些目录停止扩张、哪些技术债要逐步清理”。
> 最后更新：2026-04-09

---

## 8.1 迁移总原则

### 原则 1：不搞一次性大搬家

这次不是“把旧代码全删掉再重建”，而是：

- 先冻结 canonical 模块
- 再停止旧入口继续长新逻辑
- 最后逐步迁移调用点

### 原则 2：先收口，再清理

先确定哪一层是唯一真相源，再去删兼容层。
顺序不能反。

### 原则 3：Digest 改造不外溢

Docs Lane 的升级不应该迫使其他四大引擎跟着重写。

---

## 8.2 当前需要明确的 canonical 模块

| 能力 | canonical 落点 | 过渡/兼容 |
| --- | --- | --- |
| runtime root | `app.shared.infra.runtime_paths` | 无 |
| 业务路径 helper | `app.utils.path_helpers` | 无 |
| memory store / learner doc | `app.shared.infra.memory` | `app.teaching.memory` 仅兼容 |
| 通用 retriever / scraper | `app.shared.infra.search` | 无 |
| 原子工具 | `app.shared.infra.tools` | 无 |
| 组合 skill | `app.shared.infra.skills` | 无 |
| 教学脚手架 / 教学块 | `app.teaching.documents` | 无 |
| 教学语义动作 | `app.teaching` | `skill_tools.py` 为轻量原型区 |
| workflow 公共编排 | `app.workflows.common` | 无 |

---

## 8.3 当前停止继续扩张的目录或入口

### 1. `app.teaching.memory`

处理策略：

- 保留兼容
- 停止新增底层逻辑
- 所有新实现直接落到 `app.shared.infra.memory`

### 2. `app.teaching.skill_tools.py`

处理策略：

- 可继续放轻量样例
- 一旦出现多步 orchestration、独立 tracing、检索/LLM 组合，迁到 `shared/infra/skills`

### 3. workflow 节点中的教学字符串拼接

处理策略：

- 不再直接在 node 中堆教学块模板
- 统一沉回 `app.teaching.documents`

---

## 8.4 后续新增能力的落位指南

### 新的检索器 / 抓取器 / 工具

落点：

- `shared/infra/search`
- `shared/infra/tools`

### 新的研究型 / 媒体型 / 写作型 Skill

落点：

- `shared/infra/skills`

### 新的教学块 / 课程模板 / 错因讲评

落点：

- `app.teaching`

### 新的 DocGen 章节节点或状态流

落点：

- `workflows/digest/docgen`

---

## 8.5 推荐清理顺序

### Step 1：冻结 memory 真相源

- 文档层和代码层都明确 `shared/infra/memory` 为 canonical
- 不再在 `teaching/memory` 新增路径或存储语义

### Step 2：让教学表达只从 `teaching` 输出

- 章节导读
- 学习目标对照
- glossary
- recap
- 错因块

都统一从 `app.teaching` 导出。

### Step 3：让 workflow 只做 orchestration

- research 在 `infra/skills`
- 教学结构在 `teaching`
- graph 只负责编排与 state

### Step 4：再逐步回收兼容层

等调用点收敛后，再考虑进一步瘦身 `teaching/memory` 等过渡目录。

---

## 8.6 当前不建议做的事情

- 不建议新建 `app/core`
- 不建议把 `teaching` 再往 `shared/infra` 里面塞
- 不建议为了“目录好看”大规模移动已稳定的 workflow 文件
- 不建议为了复用 `gpt-researcher` 而强行复制其整个目录结构

---

## 8.7 一句话结论

这份迁移计划的本质不是“删除哪些文件”，而是：

- 先定唯一真相源
- 先停止旧入口继续膨胀
- 再逐步让新能力各归其位

只有这样，后续 Digest 深度重构才不会把整仓结构一起拖乱。
