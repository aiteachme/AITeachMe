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
    <img src="https://img.shields.io/badge/代码行数-169.0k-blue" alt="Lines of Code" />
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
cd backend ; conda activate atm ; uvicorn app.main:app --reload --port 9020

cd backend ; conda activate atm
uvicorn app.main:app --reload --port 9020
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

![代码量趋势](https://quickchart.io/chart?c=%7B%22type%22%3A%22line%22%2C%22data%22%3A%7B%22labels%22%3A%5B%222026-03-11%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-21%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-03-31%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-06%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-13%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-17%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-21%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-24%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%22%22%2C%222026-04-26%22%2C%22%22%2C%22%22%2C%22%22%5D%2C%22datasets%22%3A%5B%7B%22label%22%3A%22%5Cu4ee3%5Cu7801%5Cu884c%5Cu6570%22%2C%22data%22%3A%5B253%2C1446%2C7485%2C7646%2C6167%2C7166%2C7377%2C7374%2C11038%2C20483%2C21814%2C25480%2C34619%2C38753%2C26788%2C40324%2C41693%2C41693%2C43915%2C44248%2C49505%2C47627%2C62897%2C63471%2C66005%2C66993%2C67733%2C75220%2C75148%2C72160%2C79373%2C82768%2C83973%2C85531%2C85690%2C87010%2C87685%2C88978%2C88997%2C89646%2C96065%2C97141%2C99574%2C98865%2C104372%2C106640%2C107566%2C109173%2C109901%2C110464%2C110567%2C101616%2C99570%2C98782%2C101105%2C101750%2C105275%2C100048%2C100976%2C96423%2C96993%2C97551%2C97291%2C97155%2C99671%2C100454%2C101971%2C101230%2C100003%2C99932%2C101959%2C103979%2C103464%2C105724%2C106271%2C106129%2C106513%2C106226%2C107523%2C107756%2C107855%2C109450%2C110802%2C111725%2C113817%2C116312%2C117293%2C119498%2C122321%2C126118%2C125622%2C126616%2C127553%2C128651%2C131197%2C131788%2C134463%2C136353%2C136586%2C134150%5D%2C%22borderColor%22%3A%22rgb%2875%2C%20192%2C%20192%29%22%2C%22backgroundColor%22%3A%22rgba%2875%2C%20192%2C%20192%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%2C%7B%22label%22%3A%22%5Cu6ce8%5Cu91ca/%5Cu7a7a%5Cu884c%22%2C%22data%22%3A%5B272%2C955%2C3062%2C3077%2C2530%2C2678%2C2745%2C2745%2C4227%2C8017%2C8744%2C10216%2C13925%2C12680%2C12055%2C12604%2C12651%2C12651%2C12504%2C12455%2C13642%2C13227%2C22181%2C22709%2C22862%2C22958%2C23450%2C25413%2C24741%2C23816%2C25840%2C26246%2C26680%2C27470%2C27531%2C27496%2C27818%2C28219%2C28252%2C28237%2C29674%2C29910%2C30889%2C30382%2C31119%2C31714%2C32096%2C32569%2C33054%2C33145%2C32804%2C24812%2C28059%2C27540%2C28194%2C28745%2C29397%2C28535%2C29328%2C28511%2C28954%2C29026%2C28907%2C28822%2C29026%2C29160%2C29395%2C29387%2C28036%2C27998%2C28461%2C29046%2C29027%2C30105%2C30204%2C30190%2C30208%2C30089%2C30153%2C30220%2C30226%2C30454%2C30737%2C30877%2C31133%2C31568%2C31756%2C32085%2C32899%2C33382%2C33383%2C33489%2C33696%2C33794%2C33950%2C34048%2C34366%2C34552%2C34562%2C34236%5D%2C%22borderColor%22%3A%22rgb%28255%2C%20159%2C%2064%29%22%2C%22backgroundColor%22%3A%22rgba%28255%2C%20159%2C%2064%2C%200.5%29%22%2C%22fill%22%3Atrue%2C%22tension%22%3A0.4%7D%5D%7D%2C%22options%22%3A%7B%22title%22%3A%7B%22display%22%3Atrue%2C%22text%22%3A%22%5Cu4ee3%5Cu7801%5Cu91cf%5Cu53d8%5Cu5316%5Cu8d8b%5Cu52bf%22%2C%22fontSize%22%3A16%7D%2C%22scales%22%3A%7B%22yAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22ticks%22%3A%7B%22beginAtZero%22%3Atrue%7D%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu884c%5Cu6570%22%7D%7D%5D%2C%22xAxes%22%3A%5B%7B%22stacked%22%3Atrue%2C%22scaleLabel%22%3A%7B%22display%22%3Atrue%2C%22labelString%22%3A%22%5Cu65e5%5Cu671f%22%7D%7D%5D%7D%2C%22legend%22%3A%7B%22display%22%3Atrue%7D%7D%7D&width=800&height=400)

<!-- **感谢所有贡献者！**

[![贡献者](https://contrib.rocks/image?repo=aiteachme/AiTeachMe)](https://github.com/aiteachme/AiTeachMe/graphs/contributors) -->

---

<div align="center">
  <p>用 AI 赋能教育，让学习更高效</p>
  <p>Made with ❤️ by AITeachMe Team</p>
</div>
