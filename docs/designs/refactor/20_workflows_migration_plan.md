# 20. Workflows 单层化迁移计划

最后更新：2026-04-16

本计划关注的是“怎么从当前代码走到新的 workflows 单层架构”，而不是抽象愿景本身。

## 1. 迁移目标

- 让 `workflows` 成为唯一业务层
- 完成 `services` 与 `teaching` 源层退场
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
- 新增 `shared.infra.tools.teaching_registry`
- 把 tool module 自动加载入口从 `app.teaching.tools` 切到 `app.shared.infra.tools.builtin.teaching_tools`
- 新增 `digest/common/events.py`、`digest/common/exports.py`
- 新增 `digest/common/runtime_config.py`
- 新增 `digest/common/pedagogy/`

`teaching_tools` 的长期分类规则：

- registry / sync / execution 机制归 `shared.infra.tools.teaching_registry`
- 通用内置教学工具归 `shared.infra.tools.builtin.teaching_tools`
- 单条链路私有教学逻辑归对应 lane 的 `nodes/` 或 `lib/`
- Digest 文档专属教学表达归 `digest/common/pedagogy`

### Phase 2: 清理 workflow 反向依赖

- 去掉 `workflows -> app.services.*`
- 去掉 `workflows -> app.teaching.*`
- 统一改走 `shared.infra` 或 `digest.common` facade

### Phase 3: Digest 应用用例迁移

- `app.services.knowledge_docs.build_planner_service` -> `app.workflows.digest.planner`
- `app.services.knowledge_docs.digest_service` -> `digest/docgen/builds.py`
- `app.services.knowledge_docs.overview_service` -> `workflows/support/knowledge_graph/overview.py`
- `app.services.knowledge_docs.cleanup_service` -> `digest/docgen/cleanup.py`
- `app.services.knowledge_graph.*` -> `digest/kg_file_ingest/*`、`digest/kg_docs_sync/*`、`workflows/support/knowledge_graph/*`

### Phase 4: 其他引擎迁移

- `chats_service` -> `interact/application/*`
- `exams_service/*` -> `examine/application/*`
- `profile_service` -> `profile/application/*`
- `file_service` / `subject_service` / `auth_service` / `system_service` / `export_import_service` -> `workflows/support/*`

### Phase 5: 兼容层收缩

- `services/` 源层已删除，不再保留 shim
- `teaching/` 源层已删除，不再保留 facade
- 后续禁止为兼容重新创建 `app.services` 或 `app.teaching`

## 3. 首批优先级

本轮优先级已经固定：

1. 文档规范
2. `shared.infra.tools.builtin.teaching_tools`
3. `digest/common/runtime_config` 与 `digest/common/pedagogy`
4. `digest/planner` 与 `digest/docgen` 的应用用例迁移

原因：

- Digest 是当前最混乱、也是最需要统一的主链
- teaching tool 注册入口改造影响小、收益高
- 先打通最小 canonical 路径，其他模块更容易照抄

## 4. 模块迁移清单

| 当前模块 | 迁移方向 | 备注 |
| --- | --- | --- |
| `services/knowledge_docs/*` | `workflows/digest/planner/*`、`workflows/digest/docgen/*`、`workflows/support/knowledge_graph/overview.py` | 已迁入 workflows |
| `services/knowledge_graph/*` | `workflows/digest/kg_file_ingest/*`、`workflows/digest/kg_docs_sync/*`、`workflows/support/knowledge_graph/*` | 已迁入 workflows |
| `services/chats_service.py` | `workflows/interact/application/chats.py` | 已迁入 interact application，SSE 口径不变 |
| `services/exams_service/*` | `workflows/examine/application/*` | 已迁入 examine application |
| `services/profile_service.py` | `workflows/profile/application/mastery.py` | 已迁入 profile application |
| `services/file_service.py` | `workflows/support/files` | 已迁入 support 模块 |
| `services/subject_service.py` / `subject_deletion_service.py` | `workflows/support/subjects` | 已迁入 support 模块 |
| `services/auth_service.py` | `workflows/support/auth` | 已迁入 support 模块 |
| `services/system_service.py` | `workflows/support/system` | 已迁入 support 模块 |
| `services/export_import_service.py` | `workflows/support/export_import` | 已迁入 support 模块 |
| `services/subject_embedding_service.py` | `shared.infra.subject.build_precheck` | 已迁入 infra subject |
| `teaching/runtime_config.py` | `workflows/digest/common/runtime_config.py` | 已迁为真实实现 |
| `teaching/documents/*` | `workflows/digest/common/pedagogy/*` | 已迁为真实实现 |
| `teaching/teaching.py` | `shared.infra.tools.teaching_registry` | 已先落地 |
| `teaching/tools.py` | `shared.infra.tools.builtin.teaching_tools` | 已迁为通用内置工具 |

## 5. 风险与对策

### 5.1 导入面破坏

风险：

- API、测试、脚本重新引用旧 `services` / `teaching`

对策：

- 不保 shim；发现旧导入就直接改到 canonical 新入口
- 每迁完一块，再做一次 import 扫描

### 5.2 模块级巨石反弹

风险：

- 把 service 并回 workflows 后，又把所有东西塞到 `graph.py`

对策：

- 明确模块根用例文件只做 use case
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
- `backend/app/teaching` 不存在，且不再通过 shim 恢复
- `backend/app/services` 不存在，且不再通过 shim 恢复
- 已迁移的 `auth_service / chats_service / exams_service / export_import_service / file_service / profile_service / subject_service / subject_deletion_service / subject_embedding_service / system_service` 不再出现旧路径 import
- 新规范里 Digest / Ingest 不再保留 `application/`
- 新规范里 Digest / Ingest 不在模块根保留业务 `.py`，根目录只保留 `__init__.py` 与 `README.md`
- support 模块与 engine 模块边界清晰

### 行为验收

- teaching tool 能通过 `app.shared.infra.tools` 入口被枚举与执行
- `shared.infra.tools` 的 project tool module 自动加载不再依赖 `app.teaching.tools`
- Digest 主线仍可正常读到 runtime_config / pedagogy 能力

## 7. 一句话总结

迁移顺序不是“先全仓库大搬家”，而是：

- 先改规范
- 再立 canonical 落点
- 再逐块把旧逻辑挪过去
- 最后清 shim
