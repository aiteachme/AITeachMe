# AITeachMe 文档导航

AITeachMe 文档采用四层结构：

1. 根 `README.md`：项目定位、快速启动、架构总览。
2. `docs/README.md`：全仓文档导航和阅读顺序。
3. `docs/*`：跨模块当前事实源，不放历史流水账。
4. 模块内 README：代码附近的局部权威文档。

如果文档和当前代码冲突，以当前代码和模块 README 为准，并尽快修正文档。

## 推荐阅读

### 新加入项目

1. [产品愿景](./product/vision.md)
2. [系统架构](./architecture/system-architecture.md)
3. [仓库结构与运行时文件](./architecture/repo-structure-and-runtime-files.md)
4. [本地开发](./development/local-development.md)
5. [Workflows 结构规则](../backend/app/workflows/README.md)
6. [Infra 分层说明](../backend/app/shared/infra/README.md)

### 后端开发

1. [系统架构](./architecture/system-architecture.md)
2. [领域模型与状态](./architecture/domain-model-and-state.md)
3. [AI 技术栈与 Infra 接入](./architecture/ai-stack-and-infra.md)
4. [Workflows 结构规则](../backend/app/workflows/README.md)
5. [Infra 分层说明](../backend/app/shared/infra/README.md)
6. 按任务进入对应 engine 文档和模块 README。

### 前端开发

1. [API 契约与开发流程](./development/api-contracts-and-dev-workflow.md)
2. [仓库结构与运行时文件](./architecture/repo-structure-and-runtime-files.md)
3. [本地开发](./development/local-development.md)
4. [前端 README](../frontend/README.md)

### 部署与运维

1. [云端部署架构](./deployment/cloud-architecture.md)
2. [云端部署配置](./deployment/cloud-deployment.md)
3. [云端数据库迁移](./deployment/cloud-db-migrations.md)
4. [Sealos 前端 Nginx 部署](./deployment/sealos-frontend.md)
5. [导入导出](./operations/export-import.md)
6. [桌面端打包](../packaging/README.md)

## 文档分区

### Product

- [产品愿景](./product/vision.md)
- [可计算教材愿景](./product/computable-textbook.md)

### Architecture

- [系统架构](./architecture/system-architecture.md)
- [领域模型与状态](./architecture/domain-model-and-state.md)
- [AI 技术栈与 Infra 接入](./architecture/ai-stack-and-infra.md)
- [仓库结构与运行时文件](./architecture/repo-structure-and-runtime-files.md)
- [数据库与存储架构](./architecture/database-and-storage.md)
- [数据库结构清单](./architecture/database-schema-inventory.md)
- [设置与配置归属](./architecture/settings-config-ownership.md)

### Workflows

- [Ingest 透视引擎](./workflows/ingest-engine.md)
- [Digest 织网引擎](./workflows/digest-engine.md)
- [Interact 伴读引擎](./workflows/interact-engine.md)
- [Examine 诊断引擎](./workflows/examine-engine.md)
- [Profile 显影引擎](./workflows/profile-engine.md)
- [DocGen 封面 Sidecar](./workflows/docgen-cover-sidecar.md)
- [Workflows 调试指南](./workflows/debugging.md)
- [进度事件规范](./workflows/progress-events.md)

### Development

- [本地开发](./development/local-development.md)
- [API 契约与开发流程](./development/api-contracts-and-dev-workflow.md)
- [手动验证](./development/manual-testing.md)

### Deployment

- [云端部署架构](./deployment/cloud-architecture.md)
- [云端部署配置](./deployment/cloud-deployment.md)
- [云端数据库迁移](./deployment/cloud-db-migrations.md)
- [Sealos 前端 Nginx 部署](./deployment/sealos-frontend.md)

### Operations

- [导入导出](./operations/export-import.md)
- [运维入口](./operations/README.md)

### Standards

- [项目目录架构规范](./standards/standard-01-project-directory-architecture.md)
- [Git 分支管理规范](./standards/standard-02-git-branch-management.md)

## 维护规则

- 新增当前事实文档必须同步更新本文件。
- 历史方案、交接稿、过程稿不要放进 active docs。
- 单个主题只保留一个当前事实源。
- 模块内部结构优先写在模块 README，不复制到跨模块文档。
- 文档不得包含真实密钥、私有部署地址、本机绝对路径或其他项目内容。
