# AITeachMe 前端

基于 AI 的现代化个性化学习平台。

## 技术栈

- React 18
- TypeScript
- Vite
- TailwindCSS
- React Router
- Lucide Icons

## 功能特性

- 📚 学科管理 - 创建和管理多个学科
- 📤 资料上传 - 上传课程材料和笔记
- 📝 知识总结 - AI 生成摘要和思维导图
- 💬 AI 对话 - 交互式学习助手
- 📋 模拟考试 - AI 出题练习
- 📊 学习分析 - 追踪学习进度和表现

## 快速开始

### 前置条件

确保已安装 Node.js（推荐 v18 或更高版本）。

### 安装

1. 安装依赖：

```bash
npm install
```

2. 启动开发服务器：

```bash
npm run dev
```

3. 打开浏览器访问 `http://localhost:5173`

### 生产构建

```bash
npm run build
```

构建产物位于 `dist` 目录。

## 项目结构

```
src/
├── pages/           # 路由页面组件
│   ├── HomePage.tsx
│   ├── UploadPage.tsx
│   ├── SummaryPage.tsx
│   ├── ChatPage.tsx
│   ├── ExamPage.tsx
│   └── AnalysisPage.tsx
├── components/
│   ├── layout/      # 布局组件
│   │   ├── Layout.tsx
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx
│   └── ui/          # 可复用 UI 原子组件
│       ├── Button.tsx
│       └── Card.tsx
├── api/             # API 客户端与生成代码
│   ├── client.ts
│   └── generated/
├── lib/
│   └── utils.ts     # 工具函数
├── App.tsx          # 主应用（含路由）
├── main.tsx         # 入口文件
└── index.css        # 全局样式
```

## 设计理念

UI 遵循现代 SaaS 设计原则：

- 简洁布局，留白充足
- 柔和阴影与圆角
- 响应式设计（移动端友好）
- 设计灵感来自 Linear、Notion 和 ChatGPT

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_URL` | 后端 API 地址 | `http://localhost:8000` |

## 部署

### Cloudflare Pages

前端可部署至 Cloudflare Pages：

1. 连接 GitHub 仓库
2. 框架预设选择 Vite
3. 在控制台配置环境变量
4. 部署

## 许可证

私有项目
