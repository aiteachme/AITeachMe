# 20. Workflows 单层化迁移计划

最后更新：2026-04-16

本计划关注的是“怎么从当前代码走到新的 workflows 单层架构”，而不是抽象愿景本身。

## 1. 迁移目标

- 让 `workflows` 成为唯一业务层
- 让 `services` 进入兼容退场期，并完成 `teaching` 源层退场
- 先用 Digest 打样，再复制到其他引擎与 support 模块

## 2. 分阶段计划

### Phase 0: 文档与规范对齐

- 新增 `18/19/20` 三篇文档
- 更新 `refactor/README.md`、`refactor.md`
- 更新 `backend/app/workflows/STRUCTURE.md`
- 更新 `backend/app/workflows/README.md`
- 明确 `backend/app/teaching` 不再作为长期层存在

### Phase 1: 最小代码骨架落地

- 新增 `workflows/support/`
- 新增 `workflows/support/teaching_tools/`
- 新增 `shared.infra.tools.teaching_registry`
- 把 tool module 自动加载入口从 `app.teaching.tools` 切到 `app.workflows.support.teaching_tools`
- 新增 `digest/application/`
- 新增 `digest/_shared/runtime_config.py`
- 新增 `digest/_shared/pedagogy/`

### Phase 2: 清理 workflow 反向依赖

- 去掉 `workflows -> app.services.*`
- 去掉 `workflows -> app.teaching.*`
- 统一改走 `shared.infra` 或 `digest._shared` facade

### Phase 3: Digest 应用用例迁移

- `app.services.knowledge_docs.build_planner_service` -> `digest/application/build_plans.py`
- `app.services.knowledge_docs.digest_service` -> `digest/application/builds.py`
- `app.services.knowledge_docs.overview_service` -> `digest/application/overview.py`
- `app.services.knowledge_docs.cleanup_service` -> `digest/application/cleanup.py`
- `app.services.knowledge_graph.*` -> `digest/application/*` 或 `digest/knowledge_graph/` 模块门面

### Phase 4: 其他引擎迁移

- `chats_service` -> `interact/application/*`
- `exams_service/*` -> `examine/application/*`
- `profile_service` -> `profile/application/*`
- `file_service` / `subject_service` / `auth_service` / `system_service` / `export_import_service` -> `workflows/support/*`

### Phase 5: 兼容层收缩

- `services/` 只保留薄 shim，逐步标记 deprecated
- `teaching/` 源层已删除，不再保留 facade
- 最后清理历史兼容目录和导入面

## 3. 首批优先级

本轮优先级已经固定：

1. 文档规范
2. `support/teaching_tools`
3. `digest/_shared/runtime_config` 与 `digest/_shared/pedagogy`
4. `digest/planner` 与 `digest/docgen` 的应用用例迁移

原因：

- Digest 是当前最混乱、也是最需要统一的主链
- teaching tool 注册入口改造影响小、收益高
- 先打通最小 canonical 路径，其他模块更容易照抄

## 4. 模块迁移清单

| 当前模块 | 迁移方向 | 备注 |
| --- | --- | --- |
| `services/knowledge_docs/*` | `workflows/digest/application/*` | 首批主线 |
| `services/knowledge_graph/*` | `workflows/digest/application/*` / `digest/knowledge_graph/*` | 与 Digest 一起迁 |
| `services/chats_service.py` | `workflows/interact/application/*` | 保持 SSE 口径不变 |
| `services/exams_service/*` | `workflows/examine/application/*` | 保持组卷/判卷入口不变 |
| `services/profile_service.py` | `workflows/profile/application/mastery.py` | 已迁入 profile application |
| `services/file_service.py` | `workflows/support/files` | 已迁入 support 模块 |
| `services/subject_service.py` | `workflows/support/subjects` | support 模块 |
| `services/auth_service.py` | `workflows/support/auth` | support 模块 |
| `services/system_service.py` | `workflows/support/system` | 已迁入 support 模块 |
| `services/export_import_service.py` | `workflows/support/export_import` | support 模块 |
| `services/subject_embedding_service.py` | `shared.infra.subject.build_precheck` | 已迁入 infra subject |
| `teaching/runtime_config.py` | `workflows/digest/_shared/runtime_config.py` | 已迁为真实实现 |
| `teaching/documents/*` | `workflows/digest/_shared/pedagogy/*` | 已迁为真实实现 |
| `teaching/teaching.py` | `shared.infra.tools.teaching_registry` | 已先落地 |
| `teaching/tools.py` | `workflows/support/teaching_tools` | 已先落地 |

## 5. 风险与对策

### 5.1 导入面破坏

风险：

- API、测试、脚本仍引用旧 `services` / `teaching`

对策：

- 大链路先保 shim；已确认无旧调用的小模块可直接删除旧入口
- 新位置稳定后再改上层调用
- 每迁完一块，再做一次 import 扫描

### 5.2 模块级巨石反弹

风险：

- 把 service 并回 workflows 后，又把所有东西塞到 `graph.py`

对策：

- 明确 `application/` 只做 use case
- 链路目录只做 graph / state / nodes / prompts / lib
- support 模块只做 command/query，不承接引擎链路

### 5.3 迁移期双份实现漂移

风险：

- 新旧路径并存时，行为逐渐不一致

对策：

- 旧路径如需保留，只做 import shim，不做新逻辑；无调用的旧路径直接删除
- README 标清 canonical 路径
- 测试逐步转到新路径

## 6. 验收标准

### 文档验收

- `18/19/20` 三篇文档可以独立阅读
- `refactor/README.md` 与 `refactor.md` 索引完整
- `backend/app/workflows/STRUCTURE.md` 与 refactor 文档一致

### 结构验收

- `workflows` 业务链路与 application 不再直接 import `app.services.*`
- `workflows` 业务链路与 application 不再直接 import `app.teaching.*`
- 新规范里明确允许 `application/`
- support 模块与 engine 模块边界清晰

### 行为验收

- teaching tool 能通过 `app.workflows.support.teaching_tools` 入口被枚举与执行
- `shared.infra.tools` 的 project tool module 自动加载不再依赖 `app.teaching.tools`
- Digest 主线仍可正常读到 runtime_config / pedagogy 能力

## 7. 一句话总结

迁移顺序不是“先全仓库大搬家”，而是：

- 先改规范
- 再立 canonical 落点
- 再逐块把旧逻辑挪过去
- 最后清 shim
