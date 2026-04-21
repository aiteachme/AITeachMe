# AITeachMe 设计文档

最后更新：2026-04-19

`docs/designs/` 只保留当前系统设计和少量长期演进方向。历史重构子目录已经删除；已落地的重构结论已下沉到当前主文档。

阅读原则：

1. 当前代码优先于文档。
2. `backend/app/workflows/*.md` 和 `backend/app/shared/infra/*.md` 作为模块入口；长期规则以下方主文档为准。
3. 不再以 `services`、`teaching`、`shared.infra.facade`、`guardrails` 作为正式架构层。

## 核心文档

| 文档 | 作用 |
| --- | --- |
| `01_system_architecture.md` | 当前系统分层、主链路、五大引擎和配置边界 |
| `02_domain_model_and_state.md` | 领域对象、运行时状态、兼容别名 |
| `03_api_contracts_and_dev_workflow.md` | API 契约和联调方式 |
| `04_ingest_engine.md` | Ingest 两阶段解析当前设计 |
| `05_digest_engine.md` | Digest 当前主线：Planner、DocGen、KG lanes |
| `06_interact_engine.md` | Interact 对话引擎设计 |
| `07_examine_engine.md` | Examine 诊断测评设计 |
| `08_profile_engine.md` | Profile 掌握度、复习、画像设计 |
| `09_ai_stack_and_infra_guide.md` | AI 技术栈、模型路由、Search、Infra 接入指南 |
| `10_repo_structure_and_runtime_files.md` | 仓库结构、运行时目录、不要手改的文件 |
| `11_database_and_storage_architecture.md` | 数据库与存储架构 |
| `12_api_refactor_plan.md` | API 收敛计划 |
| `13_database_schema_inventory.md` | 当前数据库结构清单 |
| `14_cloud_deployment_architecture.md` | 云端部署总体架构 |
| `14b_cloud_implementation_plan.md` | 云端部署实施计划 |
| `14c_cloud_dev_handover.md` | 云端开发交接说明 |
| `15_export_import.md` | `.atmx` 导入导出设计 |
| `16_cloud_db_migrations.md` | 云端 PostgreSQL 迁移、校验与运维流程 |
| `17_settings_config_ownership.md` | 设置、环境变量、数据库覆盖与 local/cloud 页面边界 |
| `18_effective_settings_runtime.md` | effective settings 的合并规则与运行时真相 |
| `future.md` | 未来学习形态与产品路线 |

## 文档维护规则

- 新增长期设计文档时，必须同步更新本 README。
- 阶段性探索、外部项目对比、临时迁移计划不要放进长期目录。
- 如果一篇文档和当前代码明显冲突，要么更新，要么删除，不保留“仅供参考”的旧权威文档。
- 文件名优先保持编号顺序；同一主题的补充文档可使用 `14b / 14c` 这类后缀，但不要无限扩散。

## 推荐阅读顺序

### 新加入项目

1. `01_system_architecture.md`
2. `10_repo_structure_and_runtime_files.md`
3. `09_ai_stack_and_infra_guide.md`
4. `backend/app/workflows/README.md`
5. `backend/app/workflows/STRUCTURE.md`
6. `backend/app/shared/infra/README.md`
7. `13_database_schema_inventory.md`
8. 按任务进入具体 engine 文档

### 后端开发

1. `01_system_architecture.md`
2. `09_ai_stack_and_infra_guide.md`
3. `10_repo_structure_and_runtime_files.md`
4. `04_ingest_engine.md`
5. `05_digest_engine.md`
6. `13_database_schema_inventory.md`
7. `11_database_and_storage_architecture.md`

### 前端开发

1. `01_system_architecture.md`
2. `03_api_contracts_and_dev_workflow.md`
3. `10_repo_structure_and_runtime_files.md`
4. `04_ingest_engine.md`
5. `05_digest_engine.md`
6. `06_interact_engine.md`
7. `07_examine_engine.md`
8. `08_profile_engine.md`

## 当前统一口径

- 后端业务层是 `api -> workflows -> repositories / shared.infra / models / schemas`。
- `backend/app/services` 和 `backend/app/teaching` 不再存在。
- Ingest 是两阶段解析：fast parse + background enhance。
- Digest 主线是 Planner 生成 confirmed plan，DocGen 生成知识文档。
- Search 层只负责找来源、读来源、压缩上下文，不直接产最终教学答案。
- Settings 分项目默认、用户级非敏感覆盖、环境变量/敏感项三类。
- 前端生成代码目录 `frontend/src/api/generated/` 不手改。

## 一句话

这套文档不是历史想法合集，而是当前 AITeachMe 工程边界的短说明。
