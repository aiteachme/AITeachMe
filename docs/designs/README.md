# AITeachMe 设计文档导航

最后更新：2026-04-27

`docs/designs/` 只放和当前产品、工程架构、近期落地方案强相关的设计文档。这里不是历史想法合集；如果文档和代码冲突，以当前代码和模块 README 为准，并尽快修正文档。

已完成的实施计划、交接稿、重复体验稿和未来探索稿已移到 `docs/archive/designs/`。需要查历史上下文时去 archive；日常开发不要把 archive 当作当前事实源。

## 1. 阅读原则

1. 当前代码优先于文档。
2. `backend/app/workflows/README.md` 和 `backend/app/shared/infra/README.md` 是后端模块边界的入口。
3. `backend/app/workflows/<engine-or-support>/README.md` 是对应目录的局部事实源。
4. `docs/designs/` 负责跨模块设计、长期规则和近期方案，不记录已废弃实现细节。
5. `services`、`teaching`、`shared.infra.facade`、`guardrails` 不再是正式架构层。

## 2. 文档状态

| 状态 | 含义 | 维护要求 |
| --- | --- | --- |
| 当前事实 | 描述当前代码和上线口径 | 代码改动后必须同步 |
| 模块设计 | 描述某个 engine 或 support 方向 | 以对应模块 README 和代码为校准点 |
| 实施方案 | 描述近期落地步骤或迁移切口 | 完成后要下沉结论，并移出当前目录 |

## 3. 当前事实

这些文档是现在开发时最应该优先看的跨模块事实源。

| 文档 | 状态 | 作用 |
| --- | --- | --- |
| `01_system_architecture.md` | 当前事实 | 当前系统分层、五大引擎、support 边界 |
| `02_domain_model_and_state.md` | 当前事实 | 领域对象、运行时状态、兼容别名 |
| `03_api_contracts_and_dev_workflow.md` | 当前事实 | API 契约和联调方式 |
| `09_ai_stack_and_infra_guide.md` | 当前事实 | AI 技术栈、模型路由、Search、Infra 接入方式 |
| `10_repo_structure_and_runtime_files.md` | 当前事实 | 仓库结构、运行时目录、不要手改的文件 |
| `11_database_and_storage_architecture.md` | 当前事实 | 数据库和 ContentStore 存储架构 |
| `13_database_schema_inventory.md` | 当前事实 | 当前数据库结构清单 |
| `15_export_import.md` | 当前事实 | `.atmx` 导入导出、演示课程分发、安全边界 |
| `16_cloud_db_migrations.md` | 当前事实 | 云端 PostgreSQL 迁移、校验与运维流程 |
| `17_settings_config_ownership.md` | 当前事实 | 设置、环境变量、数据库覆盖、effective settings 与 local/cloud 页面边界 |

## 4. 五大引擎

这些文档描述各引擎当前主线。具体文件落点和入口仍以 `backend/app/workflows/<engine>/README.md` 为准。

| 文档 | 状态 | 作用 |
| --- | --- | --- |
| `04_ingest_engine.md` | 模块设计 | Ingest 两阶段解析与 Digest 准入 |
| `05_digest_engine.md` | 模块设计 | Digest 主线：Planner、DocGen、KG lanes |
| `06_interact_engine.md` | 模块设计 | Interact 对话引擎设计 |
| `07_examine_engine.md` | 模块设计 | Examine 诊断测评当前链路 |
| `08_profile_engine.md` | 模块设计 | Profile 掌握度、复习、画像设计 |

## 5. 部署与迁移

这些文档服务云端上线、部署和迁移。已完成的实施计划和交接稿在 archive 中保留。

| 文档 | 状态 | 作用 |
| --- | --- | --- |
| `14_cloud_deployment_architecture.md` | 当前事实 | 云端部署总体架构和 local/cloud 边界 |

## 6. DocGen 当前事实

`docs/designs` 只保留已进入当前实现口径的 DocGen 文档。过程可视化、SSE 工作台和视觉稿等规划文档已归档。

| 文档 | 状态 | 作用 |
| --- | --- | --- |
| `19_docgen_cover_sidecar.md` | 当前事实 | DocGen 封面 sidecar、配置归属与发布接入 |

## 7. 归档文档

以下文档曾用于规划或交接，但不再放在当前设计目录中：

| 文档 | 原因 |
| --- | --- |
| `../archive/designs/12_api_refactor_plan.md` | API 收敛计划已沉淀到当前 API 契约和代码中 |
| `../archive/designs/14_cloud_deployment_architecture_full.md` | 云端部署长实施方案已浓缩为当前事实页 |
| `../archive/designs/14b_cloud_implementation_plan.md` | 云端实施计划已完成主要结论 |
| `../archive/designs/14c_cloud_dev_handover.md` | 云端开发交接稿属于历史上下文 |
| `../archive/designs/18_effective_settings_runtime.md` | 已合并到 `17_settings_config_ownership.md` |
| `../archive/designs/20_docgen_live_build_experience.md` | DocGen 体验规划稿，未作为当前事实源 |
| `../archive/designs/20_docgen_workspace_ui_design.md` | DocGen UI/UX 草稿，和后续视觉稿重复 |
| `../archive/designs/21_docgen_build_workspace_experience.md` | DocGen SSE/工作台落地计划，当前未落成事实 |
| `../archive/designs/21_docgen_sse_integration.md` | SSE 状态机浓缩稿，和 21 号方案重复 |
| `../archive/designs/22_docgen_build_workspace_visual_style.md` | 视觉实现稿，作为历史方案保留 |
| `../archive/designs/future.md` | 未来路线探索，不作为当前实现约束 |

## 8. 推荐阅读顺序

### 新加入项目

1. `01_system_architecture.md`
2. `10_repo_structure_and_runtime_files.md`
3. `09_ai_stack_and_infra_guide.md`
4. `backend/app/workflows/README.md`
5. `backend/app/shared/infra/README.md`
6. `13_database_schema_inventory.md`
7. 按任务进入具体 engine 或 support README

### 后端开发

1. `01_system_architecture.md`
2. `10_repo_structure_and_runtime_files.md`
3. `backend/app/workflows/README.md`
4. `backend/app/shared/infra/README.md`
5. `09_ai_stack_and_infra_guide.md`
6. `13_database_schema_inventory.md`
7. 进入具体模块文档

### 前端开发

1. `03_api_contracts_and_dev_workflow.md`
2. `10_repo_structure_and_runtime_files.md`
3. `01_system_architecture.md`
4. `04_ingest_engine.md`
5. `05_digest_engine.md`
6. `06_interact_engine.md`
7. `07_examine_engine.md`
8. `08_profile_engine.md`

### 导入导出与演示课程

1. `15_export_import.md`
2. `10_repo_structure_and_runtime_files.md`
3. `backend/app/workflows/support/export_import/README.md`

## 9. 维护规则

- 新增设计文档必须同步更新本 README。
- 一个主题只保留一个当前事实源；规划稿、交接稿、体验草稿默认进 archive。
- 阶段性探索、外部项目对比、临时迁移计划不要继续扩散到当前设计目录。
- 如果一篇文档和当前代码明显冲突，要么修正，要么移到 archive，不保留“仅供参考”的旧权威文档。
- 文件名优先保持编号顺序；同一主题的补充文档可使用 `14b / 14c` 这类后缀，但不要无限扩散。
- 当前目录里的单篇文档优先写“职责、入口、流程、约束”，长 prompt、节点详解和实施流水账放回模块 README 或 archive。

## 10. 当前统一口径

- 后端业务层是 `api -> workflows -> repositories / shared.infra / models / schemas`。
- `backend/app/services` 和 `backend/app/teaching` 不再存在。
- Ingest 是两阶段解析：fast parse + background enhance。
- Digest 主线是 Planner 生成 confirmed plan，DocGen 生成知识文档。
- Search 层只负责找来源、读来源、压缩上下文，不直接产最终教学答案。
- Settings 分项目默认、用户级非敏感覆盖、环境变量和敏感项三类。
- 本地模式不依赖 OSS 演示课程；云端模式通过后端统一读取演示课程目录。
- 前端生成代码目录 `frontend/src/api/generated/` 不手改。
