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
    <img src="https://img.shields.io/badge/Python-3.11+-green" alt="Python" />
    <img src="https://img.shields.io/badge/TypeScript-5.0+-blue" alt="TypeScript" />
    <img src="https://img.shields.io/badge/代码行数-128.6k-blue" alt="Lines of Code" />
    <img src="https://img.shields.io/badge/Status-MVP-orange" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-blue" alt="License" />
  </p>
</div>


## 开发

- 前端访问地址 (Cloudflare Pages): https://aiteachme.pages.dev
- 后端 API 服务 (Render): https://aiteachme.onrender.com/api/health


## 环境变量
```bash
$env:PYTHONUTF8="1"
```


## 启动

```bash
cd frontend ; npm run dev

cd frontend
npm run dev
```

```bash
cd backend ; conda activate atm ; uvicorn app.main:app --reload --port 8010

cd backend ; conda activate atm
uvicorn app.main:app --reload --port 8010
```



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
├── workflows/      # 唯一业务层（五大引擎 + support 用例）
├── repositories/   # 查询与持久化
├── models/         # 业务表模型（SQLAlchemy）
├── schemas/        # API 请求/响应模型（Pydantic）
├── shared/         # 共享基础层（kernel + infra）
└── utils/          # 通用工具函数
```

**依赖方向**：`api → workflows → repositories / shared.infra / models / schemas`。
`backend/app/services` 与 `backend/app/teaching` 已不再作为源码层存在。

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

![代码量趋势](https://quickchart.io/chart?c=%7B%22type%22%3A%22line%22%2C%22data%22%3A%7B%22labels%22%3A%5B%222026-03-11%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-17%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-01%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-04%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-09%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-14%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-17%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-19%22%2C%22%22%2C%22%22%2C%22%22%5D%2C%22datasets%22%3A%5B%7B%22label%22%3A%22%5Cu4ee3%5Cu7801%5Cu884c%5Cu6570%22%2C%22data%22%3A%5B253%2C1446%2C3049%2C7485%2C7646%2C7673%2C6167%2C6270%2C7375%2C7377%2C9048%2C11038%2C11038%2C20483%2C23102%2C21814%2C24796%2C25973%2C30278%2C36113%2C38777%2C26813%2C40324%2C40267%2C41693%2C43245%2C43453%2C43915%2C44539%2C44247%2C50475%2C52879%2C54961%2C62897%2C63176%2C66080%2C66983%2C66993%2C67697%2C68859%2C74047%2C71022%2C75385%2C72029%2C79372%2C79747%2C82768%2C83699%2C80868%2C85493%2C85560%2C85924%2C87010%2C86028%2C88035%2C84621%2C89456%2C89012%2C89646%2C93690%2C96477%2C97141%2C99160%2C100146%2C98865%2C104003%2C105921%2C106640%2C98994%2C108604%2C109173%2C85690%2C110449%2C110464%2C109870%2C106607%2C98230%2C99784%2C95505%2C101063%2C99200%2C101709%2C103695%2C102027%2C106520%2C101358%2C101209%2C96350%2C101395%2C96684%2C97509%2C97566%2C96745%2C97275%2C97340%2C99663%2C99850%2C100591%2C101729%2C101834%5D%2C%22borderColor%22%3A%22rgb%2875%2C%20192%2C%20192%29%22%2C%22backgroundColor%22%3A%22rgba%2875%2C%20192%2C%20192%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%2C%7B%22label%22%3A%22%5Cu6ce8%5Cu91ca/%5Cu7a7a%5Cu884c%22%2C%22data%22%3A%5B272%2C955%2C1461%2C3062%2C3077%2C3086%2C2530%2C2567%2C2745%2C2745%2C3993%2C4228%2C4227%2C8018%2C9655%2C8744%2C10128%2C10311%2C11472%2C11940%2C12462%2C12055%2C12604%2C12644%2C12651%2C12493%2C12437%2C12504%2C12565%2C12458%2C14130%2C15044%2C15908%2C22181%2C22663%2C22837%2C22955%2C22958%2C23403%2C23681%2C25135%2C23773%2C24774%2C23797%2C25837%2C25889%2C26246%2C26620%2C26556%2C27454%2C27471%2C27580%2C27496%2C27421%2C27926%2C26842%2C28342%2C28127%2C28237%2C29153%2C29769%2C29910%2C31007%2C31345%2C30382%2C31213%2C31348%2C31714%2C30299%2C32450%2C32569%2C27531%2C33145%2C33145%2C32500%2C29098%2C27461%2C27964%2C24353%2C28259%2C27774%2C28337%2C28923%2C28876%2C29735%2C29514%2C29430%2C28435%2C29643%2C28747%2C29016%2C29016%2C28890%2C28905%2C28826%2C28993%2C29057%2C29227%2C29300%2C29336%5D%2C%22borderColor%22%3A%22rgb%28255%2C%20159%2C%2064%29%22%2C%22backgroundColor%22%3A%22rgba%28255%2C%20159%2C%2064%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%5D%7D%2C%22options%22%3A%7B%22title%22%3A%7B%22display%22%3Atrue%2C%22text%22%3A%22%5Cu4ee3%5Cu7801%5Cu91cf%5Cu53d8%5Cu5316%5Cu8d8b%5Cu52bf%22%2C%22fontSize%22%3A16%7D%2C%22scales%22%3A%7B%22yAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22ticks%22%3A%7B%22beginAtZero%22%3Atrue%7D%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu884c%5Cu6570%22%7D%7D%5D%2C%22xAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu65e5%5Cu671f%22%7D%7D%5D%7D%2C%22legend%22%3A%7B%22display%22%3Atrue%7D%7D%7D&width=800&height=400)

<!-- **感谢所有贡献者！**

[![贡献者](https://contrib.rocks/image?repo=aiteachme/AiTeachMe)](https://github.com/aiteachme/AiTeachMe/graphs/contributors) -->

---

<div align="center">
  <p>用 AI 赋能教育，让学习更高效</p>
  <p>Made with ❤️ by AITeachMe Team</p>
</div>
