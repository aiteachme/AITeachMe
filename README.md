# AITeachMe

让天下没有难学的知识。

AITeachMe 是一个资料驱动的 AI 学习系统：把 PDF、Word、PPT、Markdown、笔记等学习材料转成可讲、可问、可测、可追踪的个人学习空间。

当前仓库是一个前后端分离的 MVP：

- 前端：React + TypeScript + Vite
- 后端：FastAPI + SQLModel + LangGraph
- 数据：本地 SQLite，云端 PostgreSQL + pgvector
- 存储：本地 ContentStore，云端可接 S3-compatible OSS

## 核心闭环

```text
Ingest    透视引擎：上传资料 -> 标准 Markdown / assets
Digest    织网引擎：学习方案 -> 知识文档 -> 知识图谱
Interact  伴读引擎：结合资料、画像和上下文进行教学对话
Examine   诊断引擎：生成试卷、判卷、解释错因
Profile   显影引擎：沉淀掌握度、薄弱点、复习任务和学习画像
```

## 快速启动

后端：

```powershell
cd backend
conda activate atm
$env:PYTHONUTF8 = "1"
uvicorn app.main:app --reload --port 9020
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

默认端口：

- 前端：`http://127.0.0.1:5180`
- 后端：`http://127.0.0.1:9020`
- 健康检查：`http://127.0.0.1:9020/api/health`

Windows 也可以在仓库根目录运行：

```powershell
.\dev.bat
```

## 目录结构

```text
AITeachMe/
├── frontend/       # React 前端、Electron/Tauri 桌面端入口
├── backend/        # FastAPI 后端、workflows、models、migrations
├── docs/           # 当前文档事实源、标准、部署和开发说明
├── infra/          # Docker、Compose、Nginx、部署脚本
├── packaging/      # 桌面端打包脚本与说明
└── scripts/        # 仓库级辅助脚本
```

后端当前依赖方向：

```text
api -> workflows -> repositories / shared.infra / models / schemas
shared.infra -> shared.kernel
```

`backend/app/workflows/` 是唯一业务层，承接五大引擎和 support 用例。`backend/app/shared/infra/` 只负责 LLM、检索、存储、数据库、workflow runtime、observability 等共享基础设施。

## 文档

从 [docs/README.md](./docs/README.md) 开始阅读。高频入口：

- [产品愿景](./docs/product/vision.md)
- [系统架构](./docs/architecture/system-architecture.md)
- [仓库结构与运行时文件](./docs/architecture/repo-structure-and-runtime-files.md)
- [本地开发](./docs/development/local-development.md)
- [API 契约与开发流程](./docs/development/api-contracts-and-dev-workflow.md)
- [Workflows 结构规则](./backend/app/workflows/README.md)
- [Infra 分层说明](./backend/app/shared/infra/README.md)

## 开发约束

- Python 环境默认使用 `conda activate atm`。
- 输入输出文件读写统一使用 UTF-8。
- `frontend/src/api/generated/` 由 Orval 生成，不手动修改。
- 架构改动优先同步 `docs/` 的当前事实源，以及对应模块目录内 README。
- 文档中不要提交真实密钥、私有部署地址、本机绝对路径或其他项目内容。
