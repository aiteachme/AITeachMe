# 10. 仓库结构与运行时文件规范

> 文档定位：这是后续所有重构与新增代码的分层准绳，不只是“现状说明”。  
> 最后更新：2026-04-09

---

## 1. 设计原则

### 1.1 当前最重要的结构判断

这个仓库的核心不是“FastAPI 项目 + React 项目”，而是：

- 前端：负责交互、构建体验、阅读体验
- 后端：负责用例入口、五大引擎编排、教学语义、AI runtime

### 1.2 以后改代码要先遵守这几条

1. `shared/infra` 是接口、抽象、策略和统一 runtime 的底座，不承载教学专属语义。
2. `teaching` 是面向 AITeachMe 教学任务的适配层，不复制第二套 `infra`。
3. `workflows` 是五大引擎编排层，不沉重业务细节和底层接入。
4. `services` 是用例入口和后台任务控制层，不变成第二个 workflow 层。
5. `utils` 只放纯 helper 或运行时路径 helper，不继续承接核心业务。
6. 运行时文件路径必须统一走 helper，读写统一用 UTF-8。

---

## 2. 推荐阅读顺序

### 后端主顺序

`api -> services -> workflows -> teaching -> shared -> repositories/models/schemas -> utils`

### 原因

- `api`：看对外暴露什么能力
- `services`：看一个请求如何收敛成用例
- `workflows`：看五大引擎怎么跑
- `teaching`：看教学语义如何被表达
- `shared`：看通用底座从哪里来
- `repositories/models/schemas`：看数据与契约
- `utils`：看路径和纯工具

---

## 3. 顶层目录

| 目录 | 作用 |
| --- | --- |
| `frontend/` | React 前端、阅读器、交互页面、前端 API 封装 |
| `backend/` | FastAPI 后端、五大引擎、运行时数据、脚本 |
| `docs/` | 设计文档、标准文档、交接文档 |

### 前端补充规范

- `frontend/src/api/generated/` 是 Orval 生成目录，不手改
- 业务 API 包装应写在非 generated 目录

---

## 4. `backend/app` 的分层图

### 4.1 目标依赖方向

```text
api
  ↓
services
  ↓
workflows / repositories / teaching
  ↓
shared/infra
  ↓
shared/kernel
```

辅助层：

- `models`
- `schemas`
- `utils`

### 4.2 需要特别强调的四点

1. `teaching` 不在 `shared/infra` 下面，因为它不是底层能力，而是领域语义层。
2. `workflows/common` 不是通用基础设施，而是 workflow 专属的编排公共层。
3. `infra` 和 `teaching` 的关系不是“上下两个业务层”，而是“通用能力接口层”与“任务适配层”的关系。
4. 目标态应以 `teaching -> infra` 为主；当前若存在 `infra -> teaching`，只能是显式的教学表达 hook，不能扩散成普遍依赖。

---

## 5. 各目录职责

## 5.1 `api/`

### 负责

- FastAPI 路由
- 参数接收与资源定位
- 调用 service
- 资源级 streaming / SSE 封装

### 不负责

- 写复杂业务逻辑
- 直接调 LLM
- 直接操作 workflow state

---

## 5.2 `services/`

### 负责

- 用例级 orchestration
- 后台任务启动、锁控制、状态读写
- 把 API 请求转换成系统内部调用
- 协调 repository / workflow / shared / teaching

### 不负责

- 写 LangGraph 拓扑
- 承载通用 infra 能力
- 复制 teaching 表达模板

### 当前尤其重要

`services/knowledge/*` 是知识构建的用例边界。  
像构建锁、确认方案加载、后台任务调度，应该留在这里，不要塞回 `workflow`。

---

## 5.3 `workflows/`

### 负责

- 五大引擎的状态流转
- LangGraph graph / state / runtime
- lane 间组织与并发
- 节点级观测与进度事件

### 不负责

- 直接维护数据库 session 生命周期
- 直接定义教学模板
- 直接实现底层 retriever / scraper / memory store

### 结构约定

```text
workflows/<engine>/
├── graph.py
├── state.py
├── runtime.py
├── exports.py
├── prompts/
└── nodes/
```

### 特别说明

- `digest` 是当前 AI 主链路最复杂的引擎
- `workflows/common` 放 workflow 共享编排能力，不新增顶层 `app/common`

---

## 5.4 `teaching/`

### 负责

- 教学语义
- AITeachMe 任务适配规则
- 教学上下文
- 教学文档脚手架
- 错因解释、学习建议、练习讲评等教学表达

### 不负责

- 第二套 memory store
- 第二套 runtime path
- 第二套 retriever / llm provider / tracing

### canonical 设计

- `teaching` 依赖 `shared/infra`
- `teaching` 包装 `shared/infra`
- 目标态下 `shared/infra` 不应普遍反向依赖 `teaching`

### 当前允许的过渡例外

当前代码里已存在少量 `infra -> teaching` 的显式调用，例如写作 Skill 在产出草稿后调用 `app.teaching.documents` 补齐教学脚手架。  
这类调用暂时允许存在，但它的性质应被视为：

- 明确列出的教学表达 hook
- 过渡期兼容实现
- 后续应尽量收敛为稳定 adapter / contract，而不是继续扩散 import 链

### 当前重要决策

`app.teaching.memory` 视为迁移期兼容层，不再作为新的底层实现入口。  
canonical memory 在 `app.shared.infra.memory`。

---

## 5.5 `shared/kernel/`

### 负责

- 纯内核概念
- 与具体基础设施无关的最小抽象

示例：

- `ids`
- `time`
- `events`
- `exceptions`

### 不负责

- config
- db
- llm
- search
- teaching

---

## 5.6 `shared/infra/`

### 负责

- config / db / logger / runtime paths
- llm / embedding / model routing / fallback
- tracing / observability
- search / retrievers / scrapers
- tools / skills / mcp / sandbox
- canonical memory / storage / cache
- 跨场景可复用的接口、基类、工厂和策略

### 不负责

- 学科专属教学话术
- LangGraph graph 编排
- 章节结构设计

### 一句话

`infra` 解决“系统有哪些稳定能力接口、这些接口如何统一接入、如何统一策略、如何统一观测”。

---

## 5.7 `repositories/`

### 负责

- 数据访问
- 查询与持久化封装

### 不负责

- LLM
- 业务编排
- 教学模板

---

## 5.8 `models/`

### 负责

- 持久化模型定义

### 不负责

- API request/response
- workflow state

---

## 5.9 `schemas/`

### 负责

- API 契约
- service / workflow 输入输出 DTO

### 不负责

- 数据库存储逻辑
- 复杂业务函数

---

## 5.10 `utils/`

### 负责

- 纯 helper
- 路径 helper
- 不值得进入 `shared/infra` 的轻量工具

### 不负责

- 核心业务决策
- 教学逻辑
- 第二套 infrastructure

### 放入 `utils` 的判断标准

只有当一个函数：

- 基本无状态
- 没有明显跨模块复用语义
- 不牵涉外部系统接入

才适合放到 `utils`

---

## 6. 新功能应该放哪里

| 功能类型 | 正确落点 |
| --- | --- |
| LLM 调用封装、模型路由、fallback | `shared/infra` |
| 搜索引擎、抓取器、重排器、内容分析 | `shared/infra` |
| 教学导读、章节 recap、错因解释 | `teaching` |
| LangGraph 节点与状态流转 | `workflows` |
| 构建锁、后台任务、用例控制 | `services` |
| 数据查询与落库 | `repositories` |
| 路径构造与纯 helper | `utils` |

---

## 7. 当前最重要的 canonical / transition 口径

## 7.1 Canonical

- `app.shared.*`：新的基础层 canonical import path
- `app.shared.infra.memory`：canonical memory
- `app.shared.infra.runtime_paths`：runtime root 真相源
- `app.utils.path_helpers`：业务路径真相源
- `app.teaching.documents`：教学文档脚手架的 canonical 入口

## 7.2 Transition

- `app.teaching.memory`：兼容层，不再新增底层逻辑
- `app.teaching.skill_tools.py`：轻量原型区；一旦变复杂应升级为 `shared/infra/skills`

## 7.3 禁止

- 不新增 `app/core`
- 不新增 `app/common`
- 不在 `teaching` 再造一套 path / memory / tool registry

---

## 8. Prompt 的放置规则

### 放在 `workflows/<engine>/prompts`

当 prompt：

- 强绑定某个 workflow 阶段
- 随该引擎的 state 变化而变化

### 放在 `teaching`

当 prompt：

- 是教学表达模板
- 可跨多个 workflow 复用
- 更偏“教学话术”和“教学结构”

### 放在 `shared/infra`

当 prompt：

- 是通用 skill / tool 的内部实现 prompt
- 不带明显教学专属语义

---

## 9. 当前运行时根目录

runtime root 的真相源：

- `app.shared.infra.runtime_paths.get_runtime_data_dir()`

当前默认常见落点：

`backend/data/`

---

## 10. Subject 运行时目录

当前主要目录：

```text
backend/data/<subject>/
├─ raw_files/
├─ raw_markdowns/
├─ assets/
│  └─ <file_id>/
├─ exam/
├─ knowledge_markdowns/
│  └─ _build/
├─ temp/
└─ debug/
```

### 目录职责

| 目录 | 作用 |
| --- | --- |
| `raw_files/` | 原始上传文件 |
| `raw_markdowns/` | ingest 产出的解析 Markdown |
| `assets/<file_id>/` | 文件级附件和图片 |
| `exam/` | 试卷相关导出产物 |
| `knowledge_markdowns/` | 已发布知识文档 |
| `knowledge_markdowns/_build/` | 构建中的 staging 和中间产物 |
| `temp/` | 临时文件 |
| `debug/` | 调试产物 |

### 后续推荐新增

如果后续要支持富媒体课程文档，建议在保持现有结构兼容的前提下，逐步引入：

```text
knowledge_markdowns/
├─ assets/
├─ render_manifest.json
└─ _build/
```

注意：

> 这是目标态建议，不代表当前代码已经全部落地。

---

## 11. 用户级运行时目录

当前 canonical 语义应统一为：

```text
backend/data/users/<user_id>/
└─ LEARNER.md
```

后续推荐演进为：

```text
backend/data/users/<user_id>/
└─ profile/
   ├─ LEARNING_PROFILE.md
   ├─ LEARNER.md
   └─ subjects/
      └─ <subject>/
         └─ LEARNING_SUBJECT_PROFILE.md
```

### 重要说明

- 结构化真相仍在数据库
- Markdown 画像是运行时可读档案，不是唯一真相源
- 后续不能再引入与此冲突的另一套家目录语义

---

## 12. 路径 helper 规范

### 真相源

- runtime root：`app.shared.infra.runtime_paths`
- 业务路径：`app.utils.path_helpers`

### 规则

- 所有文件落盘都必须走 helper
- 不能在业务代码中手写拼接 `backend/data/...`
- 不能同时维护两套路径规则

---

## 13. 运行时文件读写规范

### 编码

- 一律使用 UTF-8

### 删除与重建边界

可以安全重建：

- `temp/`
- `debug/`
- `knowledge_markdowns/_build/`

谨慎处理：

- `raw_files/`
- `raw_markdowns/`
- `assets/`
- `knowledge_markdowns/*.md`
- 用户级学习档案

---

## 14. 当前最值得警惕的结构债

### 债务 1：`teaching/memory` 与 canonical memory 并存

这是当前最明显也最值得尽快冻结的架构债。

### 债务 2：部分旧 README / 文档仍带过渡口径

后续一律以本设计文档为准，逐步清理局部 README 中残留的旧语义。

### 债务 3：DocGen 富媒体产物还没有稳定 sidecar contract

这不是现在就要全改完，但后续若继续深做知识文档，必须补。

---

## 15. 一句话结论

这个仓库后续要长期稳定演进，靠的不是“多写几个目录”，而是守住这条分层线：

- `api` 入口
- `services` 用例
- `workflows` 编排
- `teaching` 教学语义
- `shared/infra` 通用底座
- `shared/kernel` 纯内核
- `repositories/models/schemas/utils` 支撑层

只要这条线不乱，后续 Digest 重构、教学工具扩展和 LangSmith 适配才不会越做越乱。
