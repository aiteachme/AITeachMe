<div align="center">
  <img
    src="./docs/brand/atm-proj-logo-trans.png"
    alt="AI TeachMe"
    style="height:300px; width:auto; display:block; margin:0 auto -8px auto;"
  />

  <p style="margin:0 0 6px 0;">
    AI 驱动的个性化学习平台 · 知识图谱 · 智能诊断 · 自适应教学
  </p>

  <p style="margin:0;">
    <img src="https://img.shields.io/badge/Python-3.10+-green" alt="Python" />
    <img src="https://img.shields.io/badge/TypeScript-5.0+-blue" alt="TypeScript" />
    <img src="https://img.shields.io/badge/代码行数-113.0k-blue" alt="Lines of Code" />
    <img src="https://img.shields.io/badge/Status-MVP-orange" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-blue" alt="License" />
  </p>
</div>


## 开发

- 前端访问地址 (Cloudflare Pages): https://aiteachme.pages.dev
- 后端 API 服务 (Render): https://aiteachme.onrender.com/api/health


## 项目简介

AITeachMe 是一个基于 AI 的个性化学习平台，通过知识图谱、智能诊断和自适应教学技术，为学习者提供精准的学习路径和个性化辅导。

### 核心特性

- **知识图谱构建**: 自动解析学习内容，构建结构化知识体系
- **智能诊断**: AI 分析学习者掌握情况，精准定位薄弱环节
- **自适应出题**: 根据学习者水平动态生成练习题
- **个性化讲解**: 针对错题提供定制化的讲解和辅导
- **学习路径规划**: 基于知识图谱推荐最优学习路径

## 项目结构

```text
AITeachMe/
├── frontend/          # 前端应用 (React + TypeScript)
├── backend/           # 后端应用 (Python + FastAPI)
├── docs/              # 项目文档
├── scripts/           # 工程脚本
├── datasets/          # 数据集与样本
├── models/            # AI 模型资源
├── configs/           # 配置模板
└── infra/             # 部署与基础设施配置
```

### 后端分层架构

```text
backend/app/
├── api/            # HTTP 资源入口（路由、请求校验）
├── services/       # 用例入口（业务编排、结果封装）
├── workflows/      # 五大引擎编排（Ingest/Digest/Interact/Examine/Profile）
├── repositories/   # 查询与持久化
├── models/         # 业务表模型（SQLAlchemy）
├── schemas/        # API 请求/响应模型（Pydantic）
├── core/           # 应用基础设施（config, database, exceptions, logger, runtime_paths）
├── infra/          # AI 平台引擎（LLM, embedding, agent, tools, search, memory 等）
└── utils/          # 通用工具函数
```

**依赖方向**：`api → services → workflows → infra → core`，`infra/` 可以 import `core/`，反之不可。

详细架构说明请参考 [项目目录架构规范](./docs/standards/standard-01-project-directory-architecture.md)

## 文档导航

开发规范
- [Standard-01: 项目目录架构规范](./docs/standards/standard-01-project-directory-architecture.md)
- [Standard-02: Git 分支管理规范](./docs/standards/standard-02-git-branch-management.md)

开发指南
- [本地开发环境搭建](./docs/local-dev.md)
- [前端开发文档](./frontend/README.md)
- [后端开发文档](./backend/README.md)

## 看板

### 📈 代码量变化趋势

![代码量趋势](https://quickchart.io/chart?c=%7B%22type%22%3A%22line%22%2C%22data%22%3A%7B%22labels%22%3A%5B%222026-03-11%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-15%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-17%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-21%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-23%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-25%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-01%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-03%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-04%22%2C%22%22%2C%22%22%2C%22%22%5D%2C%22datasets%22%3A%5B%7B%22label%22%3A%22%5Cu4ee3%5Cu7801%5Cu884c%5Cu6570%22%2C%22data%22%3A%5B253%2C1402%2C1446%2C1446%2C3049%2C6294%2C7485%2C7687%2C7646%2C7646%2C7673%2C5539%2C6167%2C6270%2C7673%2C7162%2C7170%2C7379%2C7377%2C7374%2C7675%2C7374%2C10794%2C11038%2C11038%2C11038%2C20924%2C20483%2C21371%2C23880%2C26880%2C24433%2C24824%2C28531%2C25876%2C26821%2C34619%2C32089%2C36114%2C30526%2C38761%2C39384%2C39384%2C39402%2C39402%2C39445%2C40367%2C42643%2C41670%2C44303%2C42730%2C43928%2C43032%2C41901%2C43667%2C43943%2C44539%2C44108%2C44238%2C45054%2C50588%2C49168%2C49345%2C47560%2C55619%2C54961%2C62897%2C62898%2C63176%2C63176%2C63663%2C66080%2C66005%2C66983%2C66983%2C66993%2C66993%2C67697%2C67117%2C68859%2C53984%2C74047%2C76133%2C70967%2C71927%2C75385%2C72046%2C72970%2C78469%2C79372%2C69244%2C79747%2C70096%2C82396%2C82771%2C83699%2C83973%2C83973%2C83973%2C85493%5D%2C%22borderColor%22%3A%22rgb%2875%2C%20192%2C%20192%29%22%2C%22backgroundColor%22%3A%22rgba%2875%2C%20192%2C%20192%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%2C%7B%22label%22%3A%22%5Cu6ce8%5Cu91ca/%5Cu7a7a%5Cu884c%22%2C%22data%22%3A%5B272%2C926%2C955%2C955%2C1461%2C2638%2C3062%2C3114%2C3077%2C3077%2C3086%2C2362%2C2530%2C2567%2C3086%2C2675%2C2678%2C2745%2C2745%2C2745%2C2757%2C2745%2C4214%2C4228%2C4227%2C4227%2C8075%2C8017%2C8262%2C9823%2C12281%2C10382%2C10474%2C11254%2C10301%2C10421%2C13925%2C13869%2C11940%2C11528%2C12461%2C12557%2C12557%2C12387%2C12387%2C12391%2C12608%2C12845%2C12667%2C12973%2C12809%2C12517%2C12401%2C12691%2C12477%2C12508%2C12565%2C12441%2C12455%2C12606%2C14044%2C13716%2C13904%2C13211%2C16223%2C15908%2C22181%2C22181%2C22663%2C22663%2C22720%2C22837%2C22862%2C22955%2C22955%2C22958%2C22958%2C23403%2C23059%2C23681%2C15137%2C25135%2C25738%2C23707%2C24460%2C24774%2C23797%2C24196%2C25240%2C25837%2C23744%2C25889%2C23564%2C26195%2C26248%2C26620%2C26680%2C26680%2C26680%2C27454%5D%2C%22borderColor%22%3A%22rgb%28255%2C%20159%2C%2064%29%22%2C%22backgroundColor%22%3A%22rgba%28255%2C%20159%2C%2064%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%5D%7D%2C%22options%22%3A%7B%22title%22%3A%7B%22display%22%3Atrue%2C%22text%22%3A%22FluxHive%20%5Cu4ee3%5Cu7801%5Cu91cf%5Cu53d8%5Cu5316%5Cu8d8b%5Cu52bf%22%2C%22fontSize%22%3A16%7D%2C%22scales%22%3A%7B%22yAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22ticks%22%3A%7B%22beginAtZero%22%3Atrue%7D%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu884c%5Cu6570%22%7D%7D%5D%2C%22xAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu65e5%5Cu671f%22%7D%7D%5D%7D%2C%22legend%22%3A%7B%22display%22%3Atrue%7D%7D%7D&width=800&height=400)

<!-- **感谢所有贡献者！**

[![贡献者](https://contrib.rocks/image?repo=aiteachme/AiTeachMe)](https://github.com/aiteachme/AiTeachMe/graphs/contributors) -->

---

<div align="center">
  <p>用 AI 赋能教育，让学习更高效</p>
  <p>Made with ❤️ by AITeachMe Team</p>
</div>