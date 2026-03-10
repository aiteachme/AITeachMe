# Standard-01 项目目录架构文档

**项目名称：AITeachMe**
**文档编号：Standard-01**
**版本：v1.2（正式版标准 + MVP 兼容条款）**
**状态：Active**
**适用范围：AITeachMe 全仓库**
**最后更新：2026-03-10**

---

## 1. 目的

本文档用于统一 AITeachMe 的项目目录结构、模块边界与引用链规则，确保项目在不同阶段都具备清晰职责、稳定依赖方向和可演进能力。

本标准同时覆盖两种实施形态：

* **MVP 兼容形态**：适用于本地运行、前后端各一个应用、后端单体部署的早期阶段
* **正式版目标形态**：适用于多应用、多服务、Agent 化与平台化演进阶段

本标准的核心不是强制固定某一种目录树，而是约束以下不变原则：

1. 模块职责清楚
2. 引用链单向稳定
3. 同语言共享与跨语言共享分离
4. 架构可从 MVP 平滑演进到正式版

---

## 2. 架构原则（所有阶段必须遵守）

### 2.1 职责分离

前端、后端、AI 能力、数据、脚本、文档、基础设施资产必须可以区分，不得随意混放。

### 2.2 依赖单向

依赖必须从上层流向下层，禁止反向依赖与循环依赖。

### 2.3 逻辑分层优先于物理拆分

即使在 MVP 阶段采用单体部署，也必须在代码组织上保持分层；允许物理合并，不允许逻辑混乱。

### 2.4 同语言共享与跨语言共享分离

TypeScript 前端与 Python 后端通常不直接共享源码实现；跨语言共享应通过 Schema、IDL、契约、错误码与生成产物实现。

### 2.5 渐进演进

MVP 架构必须是正式版架构的可演进起点，而不是未来必须推翻重做的临时堆砌结构。

---

## 3. 分阶段架构适用规则

### 3.1 MVP 兼容形态

适用于以下情况：

* 当前不做在线服务部署
* 前端仅一个应用
* 后端仅一个本地运行应用
* AI 能力以内嵌模块形式存在
* 目标是尽快跑通最小产品闭环

MVP 阶段允许采用简化顶层目录：

```text
AITeachMe/
├── frontend/
├── backend/
├── docs/
├── scripts/
├── datasets/
├── models/
├── configs/
└── README.md
```

该形态**不违反本标准**，前提是 `backend/` 内部仍按模块与层次组织，而不是把所有逻辑堆在一起。

### 3.2 正式版目标形态

适用于以下情况：

* 出现多个前端应用
* 出现多个后端服务
* AI 能力逐步独立为 Agent / Worker / 推理模块
* 需要更清晰的共享边界、团队边界与部署边界

正式版推荐采用：

```text
AITeachMe/
├── apps/
├── services/
├── agents/
├── packages/
├── models/
├── datasets/
├── infra/
├── scripts/
├── tests/
├── docs/
├── configs/
├── tools/
├── examples/
├── .github/
└── README.md
```

说明：

* `frontend/backend` 是 MVP 友好命名
* `apps/services/agents/packages` 是正式版推荐命名
* 两种形态都受同一套引用链原则约束

---

## 4. MVP 兼容目录标准

### 4.1 顶层目录

```text
AITeachMe/
├── frontend/               # 前端应用（TS）
├── backend/                # 后端应用（Python）
├── docs/                   # 文档
├── scripts/                # 工程脚本
├── datasets/               # 测试数据/样本/标注
├── models/                 # 模型封装、Prompt、推理资源
├── configs/                # 配置模板
└── README.md
```

### 4.2 MVP 前端目录

```text
frontend/
├── src/
│   ├── app/
│   ├── pages/
│   ├── features/
│   ├── components/
│   ├── services/
│   ├── hooks/
│   ├── styles/
│   └── main.tsx
├── public/
└── package.json
```

要求：

* 页面、交互、前端状态与前端展示逻辑放在 `frontend/`
* 前端不得直接依赖后端私有实现
* 前端不得直接访问数据库或模型内部逻辑

### 4.3 MVP 后端目录

```text
backend/
├── app/
│   ├── api/                # HTTP 接口层
│   ├── core/               # 配置、日志、数据库初始化
│   ├── domain/             # 领域模型与业务规则
│   ├── services/           # 用例/业务流程编排
│   ├── repositories/       # 数据访问层
│   ├── ai/                 # AI 能力模块
│   ├── schemas/            # DTO / Pydantic 模型
│   ├── utils/
│   └── main.py
├── tests/
├── uploads/
├── data/
└── pyproject.toml
```

要求：

* `api/` 负责接入层，不直接承载复杂业务规则
* `domain/` 负责核心业务规则
* `services/` 负责流程编排
* `repositories/` 负责数据访问
* `ai/` 负责解析、知识点提取、出题、诊断、讲解等 AI 能力
* 虽然是单体部署，但必须保持逻辑分层

### 4.4 MVP 引用链规则

MVP 阶段推荐引用方向：

```text
frontend
    ↓ HTTP/API
backend/app/api
    ↓
backend/app/services
    ↓
backend/app/domain
    ↓
backend/app/repositories
```

AI 能力模块应通过 `services/` 被调用，不建议由 API 层直接到处调用底层实现。

---

## 5. 正式版目录标准

### 5.1 顶层目录

```text
AITeachMe/
├── apps/                  # 前端应用集合
├── services/              # 后端服务集合
├── agents/                # AI Agent 与编排模块
├── packages/              # 同生态共享包 + 跨语言协议
├── models/                # 算法模型与推理/训练代码
├── datasets/              # 数据集与标注数据
├── infra/                 # 部署与运行基础设施资产
├── scripts/               # 工程脚本
├── tests/                 # 跨模块测试
├── docs/                  # 文档体系
├── configs/               # 全局配置模板
├── tools/                 # 内部开发工具
├── examples/              # 示例输入与样例流程
├── .github/
└── README.md
```

### 5.2 `apps/`

用于存放前端应用集合。

```text
apps/
├── web-student/
├── web-admin/
└── web-marketing/
```

### 5.3 `services/`

用于存放独立后端服务。

```text
services/
├── gateway/
├── user-service/
├── content-service/
├── knowledge-service/
├── practice-service/
├── learning-service/
├── tutoring-service/
└── analytics-service/
```

### 5.4 `agents/`

用于存放 AI Agent 与任务编排模块。

```text
agents/
├── orchestrator/
├── parser-agent/
├── diagnosis-agent/
├── exercise-agent/
└── tutor-agent/
```

### 5.5 `packages/`

用于存放共享内容，但必须区分同语言共享和跨语言共享。

```text
packages/
├── frontend/
│   ├── ui/
│   ├── sdk/
│   ├── config/
│   └── utils/
├── backend/
│   ├── common/
│   ├── config/
│   ├── storage/
│   ├── llm/
│   ├── retrieval/
│   └── observability/
└── schemas/
```

说明：

* `packages/frontend/*` 仅供前端生态复用
* `packages/backend/*` 仅供后端/Agent/模型侧复用
* `packages/schemas/*` 用于放 OpenAPI、JSON Schema、Proto、事件 Schema、错误码、枚举等跨语言共识

### 5.6 `infra/`

用于存放项目级部署与运行基础设施资产。

```text
infra/
├── docker/
├── compose/
├── kubernetes/
├── nginx/
├── ci/
├── monitoring/
├── logging/
└── security/
```

说明：

* 根目录 `infra/` 是项目级部署目录
* 它与服务内部 `app/infra/` 或具体实现层不是同一个概念

---

## 6. 服务内部标准（正式版）

每个后端服务推荐采用如下结构：

```text
services/<service-name>/
├── app/
│   ├── api/               # 接口层
│   ├── usecases/          # 用例编排层
│   ├── domain/            # 领域规则层
│   ├── ports/             # 抽象接口层
│   ├── infra/             # 具体实现层
│   ├── tasks/             # 异步任务
│   ├── schemas/           # 内部 DTO / ViewModel
│   ├── security/          # 权限/审计/认证
│   ├── wiring/            # 装配层
│   └── main.py
├── tests/
├── migrations/
├── configs/
└── pyproject.toml
```

职责说明：

* `api/`：接入层，只负责协议适配与参数进出
* `usecases/`：负责流程编排
* `domain/`：核心业务规则，不依赖数据库、Web 框架、Redis、LLM SDK 等具体实现
* `ports/`：定义仓储、模型调用、外部服务等抽象接口
* `infra/`：实现 `ports/`
* `wiring/`：依赖注入与启动装配

---

## 7. 统一引用链规则（所有阶段适用）

### 7.1 总体依赖方向

```text
UI / API
    ↓
UseCases / Services
    ↓
Domain
    ↓
Ports / Repositories / Contracts
    ↓
Infrastructure Implementations
```

核心要求：

* 上层可以依赖下层抽象
* 下层不得反向依赖上层
* `domain` 不得依赖具体基础设施实现
* 共享层不得依赖具体业务服务内部实现

### 7.2 MVP 阶段补充约束

* `frontend/` 只能通过 API 调用 `backend/`
* `backend/app/api/` 不得绕过 `services/` 直接大面积操作数据访问层和 AI 底层实现
* `backend/app/domain/` 不得依赖具体 Web 框架与 ORM 实现

### 7.3 正式版阶段补充约束

#### `apps/` 可以引用

* `packages/frontend/*`
* `packages/schemas/*` 生成出的前端类型与契约
* API / SDK

#### `services/` 可以引用

* `packages/backend/*`
* `packages/schemas/*` 生成出的后端契约
* `models/*`
* 通过契约或调用方式接入 `agents/*`

#### `agents/` 可以引用

* `packages/backend/*`
* `packages/schemas/*`
* `models/*`
* 通过 API / 消息 / 契约接入 `services/*`

#### `packages/` 可以引用

* 同生态更底层共享包
* 不得跨生态直接依赖实现代码

---

## 8. 命名规范

### 8.1 MVP 阶段允许命名

* `frontend/`
* `backend/`

### 8.2 正式版推荐命名

* `apps/`
* `services/`
* `agents/`
* `packages/`

### 8.3 目录与模块命名

统一使用小写短横线风格：

* `learning-service`
* `web-student`
* `parser-agent`

### 8.4 Python 文件命名

统一使用小写下划线：

* `knowledge_graph_builder.py`

### 8.5 React 组件命名

组件文件使用 PascalCase：

* `KnowledgeMapPanel.tsx`

### 8.6 标准文档命名

统一使用：

```text
standard-01-project-directory-architecture.md
standard-02-code-style-guide.md
standard-03-module-dependency-rules.md
```

---

## 9. 禁止事项

以下行为在任何阶段一律禁止：

1. 在根目录堆积业务代码、临时脚本、试验文件
2. 把明确属于业务域的逻辑塞进共享层
3. `domain` 反向依赖 `infra` / 具体实现层
4. 一个服务直接 import 另一个服务的内部实现
5. 前端直接访问数据库、模型内部逻辑或后端内部模块
6. 将日志、缓存、用户隐私原始数据、临时产物直接提交到业务代码目录
7. 因为是 MVP 就把所有逻辑堆进单个文件或单个目录

---

## 10. 演进规则

项目应按以下方向平滑演进：

* `frontend/` → `apps/web-student/` 或多个前端应用
* `backend/` → `services/` 下的多个后端服务
* `backend/app/ai/` → `agents/` 中的独立 Agent / Worker 模块
* 单体内部共享代码 → `packages/backend/` 或 `packages/frontend/`
* 前后端接口定义 → `packages/schemas/`

要求：

* MVP 阶段的目录与代码组织必须为未来拆分保留边界
* 未来拆分应以“提取已有模块”为主，而不是“大规模推倒重来”

---

## 11. 执行要求

* 新增模块前，必须先明确其目录归属与上下游引用链
* Code Review 必须检查是否违反本标准
* 后续建议在 CI 中增加 import boundary / forbidden path 检查

---

## 12. 标准结论

本标准采用“**正式版标准 + MVP 兼容条款**”模式。

这意味着：

* **MVP 可以简化目录形态**，但不能破坏分层与引用链原则
* **正式版可以扩展为多应用、多服务、Agent 化结构**，但仍受同一套原则约束
* Standard-01 约束的是架构秩序，而不是机械固定某一版目录名

对 AITeachMe 项目：

* 早期本地单机阶段，可采用 `frontend/ + backend/`
* 后续平台化阶段，演进为 `apps/ + services/ + agents/ + packages/`

二者均属于本标准允许范围。

---

## 13. 文档归档路径

建议本文档保存为：

```text
docs/standards/standard-01-project-directory-architecture.md
```
