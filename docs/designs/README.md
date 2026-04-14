# AITeachMe 开发设计文档

## 1. 文档定位

`docs/designs/` 用来描述当前仓库的工程真相、领域边界和后续演进方向。

阅读这些文档时，请始终记住三条原则：

1. 以当前代码为准，不以历史分支和旧生成物为准。
2. 以本地数据库收敛后的主设计为准，不以旧 version 表方案为准。
3. 以当前 ingest 两阶段实现为准，不以旧的单阶段说明为准。

---

## 2. 核心文档

| 文档 | 作用 |
| --- | --- |
| `01_system_architecture.md` | 系统分层、五大引擎位置、主链路 |
| `02_domain_model_and_state.md` | 稳定业务对象、运行时状态、兼容别名 |
| `03_api_contracts_and_dev_workflow.md` | API 契约与联调方式 |
| `04_ingest_engine.md` | 两阶段 Ingest (Fast Parse + Deep Enhance)、LangGraph 流程、Prompt 模板 |
| `05_digest_engine.md` | Digest 三 Lane (KG + Curriculum + Docs)、节点级逻辑、完整 Prompt |
| `06_interact_engine.md` | RAG 检索 + 教学策略 + 流式 SSE 对话、完整 Prompt |
| `07_examine_engine.md` | 构题 + 智能组卷 + LLM 判卷、风格画像体系 |
| `08_profile_engine.md` | 掌握度公式 + SM-2 复习调度 + 薄弱点分析 + 双层画像 |
| `10_repo_structure_and_runtime_files.md` | 仓库结构与运行时目录 |
| `11_database_and_storage_architecture.md` | 本地部署、中心化部署、存储抽象 |
| `12_api_refactor_plan.md` | API 收敛计划 |
| `13_database_schema_inventory.md` | 当前数据库唯一主设计文档 |
| `15_export_import.md` | 导入导出 `.atmx` 格式设计 |
| `future.md` | 未来学习形态与产品化路线（与当前代码能力映射） |
| `refactor/` | Digest refactor 设计（见 [refactor/README.md](refactor/README.md)） |

---

## 3. 推荐阅读顺序

### 3.1 新加入项目

1. `01_system_architecture.md`
2. `10_repo_structure_and_runtime_files.md`
3. `13_database_schema_inventory.md`
4. `11_database_and_storage_architecture.md`
5. `02_domain_model_and_state.md`
6. 再进入具体引擎文档

### 3.2 后端开发

1. `01_system_architecture.md`
2. `02_domain_model_and_state.md`
3. `13_database_schema_inventory.md`
4. `04_ingest_engine.md`
5. `05_digest_engine.md`
6. `11_database_and_storage_architecture.md`

### 3.3 前端开发

1. `01_system_architecture.md`
2. `03_api_contracts_and_dev_workflow.md`
3. `10_repo_structure_and_runtime_files.md`
4. `04_ingest_engine.md`
5. `05_digest_engine.md`
6. `06_interact_engine.md`
7. `07_examine_engine.md`
8. `08_profile_engine.md`

---

## 4. 这轮 merge 的重点口径

这轮代码合并后的文档口径必须统一为：

- ingest 方法层采用两阶段加速
- 数据库主线采用 `curriculum` 单表版本语义
- 知识文档和知识图谱在同一轮 digest 中共享版本
- 运行时目录采用 `raw_files / raw_markdowns / assets / knowledge_markdowns`
- API 形态是“POST 主导 + 少量 GET 读取 + SSE 聊天主通道”，不是全 POST
- Profile 已包含学科级与用户级双层摘要，并应进一步投影到运行时学习档案

---

## 5. 一句话总纲

这套文档的目标不是“记录所有想法”，而是把当前 AITeachMe 的真实工程边界写清楚：

- 五大引擎如何协作
- 数据如何流动
- 哪些对象是长期真相
- 哪些状态只是运行时实现
- 在不增加 API 复杂度前提下，未来优先演进哪些能力

