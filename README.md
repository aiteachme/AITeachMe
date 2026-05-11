# AITeachMe

让天下没有难学的知识。

AITeachMe 是一个资料驱动的 AI 学习系统：把 PDF、Word、PPT、Markdown、笔记等学习材料转成可讲、可问、可测、可追踪的个人学习空间。

当前仓库是一个前后端分离的 MVP：

- 前端：React + TypeScript + Vite
- 后端：FastAPI + SQLModel + LangGraph
- 数据：本地 SQLite，云端 PostgreSQL + pgvector
- 存储：本地 ContentStore，云端可接 S3-compatible OSS

<!-- CODE_STATS_START -->
## 代码量概览

![代码行数](https://img.shields.io/badge/代码行数-195.1k-blue)

![代码量趋势](https://quickchart.io/chart?c=%7B%22type%22%3A%22line%22%2C%22data%22%3A%7B%22labels%22%3A%5B%222026-03-11%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-23%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-05%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-16%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-20%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-24%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-27%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-30%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-05-05%22%2C%22%22%2C%22%22%2C%22%22%5D%2C%22datasets%22%3A%5B%7B%22label%22%3A%22%5Cu4ee3%5Cu7801%5Cu884c%5Cu6570%22%2C%22data%22%3A%5B253%2C6294%2C7646%2C6270%2C7375%2C10481%2C20483%2C23364%2C26821%2C38753%2C39725%2C41670%2C41751%2C44539%2C50563%2C55810%2C63663%2C66993%2C67733%2C70967%2C72160%2C79589%2C83973%2C85623%2C86176%2C88035%2C89456%2C92068%2C96716%2C99574%2C103974%2C106640%2C108604%2C100146%2C109661%2C107322%2C99784%2C94612%2C101750%2C104088%2C100179%2C96899%2C97510%2C97537%2C99337%2C100591%2C98926%2C100137%2C101971%2C102663%2C105479%2C106302%2C106674%2C106211%2C107525%2C107808%2C109450%2C112589%2C113817%2C116323%2C119498%2C121199%2C126319%2C127188%2C127497%2C131200%2C132754%2C136353%2C136672%2C133702%2C135278%2C136574%2C131036%2C139260%2C133118%2C134527%2C135392%2C137447%2C138005%2C138919%2C137517%2C138552%2C140912%2C141518%2C142034%2C144158%2C145536%2C147066%2C146015%2C149784%2C154609%2C149282%2C150230%2C150232%2C150334%2C152322%2C153327%2C154033%2C154754%2C156735%5D%2C%22borderColor%22%3A%22rgb%2875%2C%20192%2C%20192%29%22%2C%22backgroundColor%22%3A%22rgba%2875%2C%20192%2C%20192%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%2C%7B%22label%22%3A%22%5Cu6ce8%5Cu91ca/%5Cu7a7a%5Cu884c%22%2C%22data%22%3A%5B272%2C2638%2C3077%2C2567%2C2745%2C4161%2C8018%2C9817%2C10421%2C12680%2C12729%2C12667%2C12666%2C12565%2C14169%2C16099%2C22720%2C22958%2C23450%2C23707%2C23816%2C25883%2C26680%2C27514%2C27620%2C27926%2C28342%2C28927%2C29787%2C30889%2C31195%2C31714%2C32450%2C31345%2C32476%2C29511%2C27964%2C23960%2C28745%2C29470%2C28488%2C28828%2C29016%2C28945%2C28911%2C29227%2C27812%2C28048%2C28450%2C28700%2C30038%2C30206%2C30230%2C30082%2C30153%2C30225%2C30452%2C30887%2C31133%2C31567%2C32085%2C32286%2C33421%2C33525%2C33675%2C33928%2C34138%2C34552%2C34575%2C33864%2C34023%2C34176%2C32881%2C34594%2C33205%2C33384%2C33749%2C34091%2C34183%2C34581%2C34126%2C34271%2C34725%2C34832%2C34954%2C35262%2C35515%2C35666%2C35617%2C36041%2C36533%2C31851%2C32073%2C32075%2C32109%2C32304%2C32493%2C32326%2C32460%2C32637%5D%2C%22borderColor%22%3A%22rgb%28255%2C%20159%2C%2064%29%22%2C%22backgroundColor%22%3A%22rgba%28255%2C%20159%2C%2064%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%5D%7D%2C%22options%22%3A%7B%22title%22%3A%7B%22display%22%3Atrue%2C%22text%22%3A%22%5Cu4ee3%5Cu7801%5Cu91cf%5Cu53d8%5Cu5316%5Cu8d8b%5Cu52bf%22%2C%22fontSize%22%3A16%7D%2C%22scales%22%3A%7B%22yAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22ticks%22%3A%7B%22beginAtZero%22%3Atrue%7D%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu884c%5Cu6570%22%7D%7D%5D%2C%22xAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu65e5%5Cu671f%22%7D%7D%5D%7D%2C%22legend%22%3A%7B%22display%22%3Atrue%7D%7D%7D&width=800&height=400)
<!-- CODE_STATS_END -->

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
pip install -e .
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

## License 与商标

本仓库代码使用 [GNU Affero General Public License v3.0 only](./LICENSE)（`AGPL-3.0-only`）。

如果你修改本项目并通过网络服务向用户提供访问，需要按照 AGPL-3.0 的要求向这些用户提供相应源码。需要在不触发 AGPL 源码开放义务的场景中使用、集成或托管 AITeachMe，请参考 [商业授权说明](./COMMERCIAL.md)。

`AITeachMe` 名称、标识、Logo 和相关品牌资产不随代码许可证授权。商标和品牌使用边界见 [TRADEMARKS.md](./TRADEMARKS.md)。

## 开发约束

- Python 使用 3.11+；如使用 Conda、venv 或其他环境管理器，请先激活自己的项目环境。
- 输入输出文件读写统一使用 UTF-8。
- `frontend/src/api/generated/` 由 Orval 生成，不手动修改。
- 架构改动优先同步 `docs/` 的当前事实源，以及对应模块目录内 README。
- 文档中不要提交真实密钥、私有部署地址、本机绝对路径或其他项目内容。
