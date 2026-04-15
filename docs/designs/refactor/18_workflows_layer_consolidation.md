# 18. Workflows 单层化边界收敛

最后更新：2026-04-16

这份文档记录本轮重构最重要的边界调整：`backend/app/workflows/` 正式升级为后端唯一业务层，`app/services` 与 `app/teaching` 不再作为长期正式架构层继续扩张。

## 1. 核心决策

- 新的推荐依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
```

- `workflows` 承接：
  - 五大引擎图编排
  - 面向 API 的业务用例
  - 模块内数据库读写协调
  - 与 `shared.infra` 的能力组合
- `shared.infra` 继续只承接基础设施。
- `repositories` 继续只承接持久化读写封装。
- `app/services` 整体退出主架构，只保留迁移期 shim。
- `app/teaching` 源层已退出并删除，教学语义拆入 workflows/support 与 shared.infra。

## 2. 为什么要收缩 `services`

当前仓库里 `services` 已经混合了三类完全不同的职责：

- API 适配型业务用例
- 五大引擎主链的编排残留
- 一些本质上只是查询/命令门面的薄封装

继续保留这层会出现几个问题：

- `api -> services -> workflows` 经常只是再转一次手，信息价值很低
- `workflows` 反过来又依赖部分 `services`，层级已经不再单向
- 模块边界被拆散，Digest/Interact/Examine 的真实主线很难从目录上读出来

因此本轮不再把 `services` 当作长期架构层，而是把引擎相关用例并回各自的 `workflows/<module>/application/`，把非引擎业务用例并入 `workflows/support/`

## 3. 为什么要拆散 `teaching`

`app/teaching` 的历史价值是真实存在的，但当前已经出现两类不同性质的内容被放在同一层：

- Digest 专属的教学语义：`runtime_config.py`、`documents/*`
- 兼容 facade：`checker.py`、`memory/*`、`skill_tools.py`
- 教学工具注册门面：`teaching.py`、`tools.py`

继续把这些内容都留在同一层，会造成：

- Digest 主链持续跨层 import `app.teaching.*`
- tool registry 语义与工具实现位置分离
- 兼容层看起来像正式架构层

因此新的拆分方向是：

- Digest 专属教学语义 -> `app.workflows.digest._shared.*`
- 教学工具注册语义 -> `app.shared.infra.tools.teaching_registry`
- 教学工具实现 -> `app.workflows.support.teaching_tools`
- checker/memory/skill_tools -> 删除正式角色；如确需兼容，落到测试或 infra-local facade，不恢复 `app.teaching`

## 4. 新边界下的职责表

| 层 | 长期职责 | 不再承担 |
| --- | --- | --- |
| `api/` | HTTP、鉴权依赖注入、请求响应转换、SSE Response 包装 | 业务编排、引擎主链 |
| `workflows/` | 业务用例、引擎编排、模块级协调 | 基础设施实现 |
| `repositories/` | 数据读写封装 | 业务流程判断 |
| `shared/infra/` | LLM、storage、search、tools、workflow support 等基础设施 | 业务用例 |
| `models/` / `schemas/` | 持久化模型与边界数据结构 | 业务编排 |
| `services/` | 迁移期兼容 | 正式新增业务逻辑 |
| `teaching/` | 已移除 | 不再恢复为正式层或兼容层 |

## 5. 旧层到新层的总映射

| 旧位置 | 新位置 |
| --- | --- |
| `app.services.knowledge_docs.*` | `app.workflows.digest.application.*` |
| `app.services.knowledge_graph.*` | `app.workflows.digest.application.*` 或 `digest/knowledge_graph/` 门面 |
| `app.services.chats_service` | `app.workflows.interact.application.*` |
| `app.services.exams_service.*` | `app.workflows.examine.application.*` |
| `app.services.profile_service` | `app.workflows.profile.application.*` |
| `app.services.file_service` | `app.workflows.support.files` |
| `app.services.subject_service` / `subject_deletion_service` | `app.workflows.support.subjects` |
| `app.services.auth_service` | `app.workflows.support.auth` |
| `app.services.system_service` | `app.workflows.support.system` |
| `app.services.export_import_service` | `app.workflows.support.export_import` |
| `app.services.subject_embedding_service` | `app.shared.infra.subject.*` |
| `app.teaching.runtime_config` | `app.workflows.digest._shared.runtime_config` |
| `app.teaching.documents.*` | `app.workflows.digest._shared.pedagogy.*` |
| `app.teaching.teaching` | `app.shared.infra.tools.teaching_registry` |
| `app.teaching.tools` | `app.workflows.support.teaching_tools` |
| `app.teaching.checker` / `memory` / `skill_tools` | 已删除正式入口；需要的能力改走 `shared.infra` 或测试专用导入 |

## 6. 本轮已落地的最小代码对齐

本轮先做最关键的一小步，避免“文档先飞、代码不跟”：

- `shared.infra.tools.api` 的 project tool module 加载入口已经切到 `app.workflows.support.teaching_tools`
- 新增 `app.shared.infra.tools.teaching_registry`
- 新增 `app.workflows.support.teaching_tools`
- 新增 `app.workflows.digest._shared.runtime_config`
- 新增 `app.workflows.digest._shared.pedagogy`
- 删除旧 `backend/app/teaching` 源层
- `app.services.system_service` 已迁入 `app.workflows.support.system`
- `app.services.file_service` 已迁入 `app.workflows.support.files`
- `app.services.profile_service` 已迁入 `app.workflows.profile.application.mastery`
- `app.services.subject_service` 与 `subject_deletion_service` 已迁入 `app.workflows.support.subjects`
- `app.services.chats_service` 已迁入 `app.workflows.interact.application.chats`
- `app.services.export_import_service` 已迁入 `app.workflows.support.export_import`
- `app.services.subject_embedding_service` 已迁入 `app.shared.infra.subject.build_precheck`
- Digest / Interact workflow 已消除对 `app.services` 的直接 import
- Digest workflow 已消除对 `app.teaching` 的直接 import，统一改走 `_shared` 真实实现

注意：

- `services/` 仍然存在，目的是保迁移兼容，不是继续扩大
- `teaching/` 不再作为源代码目录存在；不要为兼容重新创建该层

## 7. 一句话总结

本轮最重要的不是“把代码挪目录”，而是重新把后端业务边界钉死：

- `api` 只接请求
- `workflows` 只管业务
- `shared.infra` 只管能力
- `services` 进入兼容退场期，`teaching` 已完成源层退场
