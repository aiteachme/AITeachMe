# AITeachMe 文档维护说明

`docs/` 现在同时承担两类职责：

1. `docs/content/docs/`：Fumadocs 文档站的展示内容，面向用户教程、开发者入口和简短产品说明。
2. `docs/architecture`、`docs/workflows`、`docs/development` 等：仓库已有的内部事实文档，先继续作为实现事实源保留，后续逐步整理进更清晰的 reference 区域。

文档站不是另一个产品首页，也不单独承载营销落地页。根路径 `/` 仅重定向到 `/docs`，真正的阅读入口从 `/docs` 开始。

## 展示内容结构

文档站内容放在 `docs/content/docs/`：

- `index.mdx`：文档站总入口，说明推荐阅读路径和稳定概念。
- `quickstart/`：第一次使用、首页输入框和构建课程路径。
- `user-guide/`：资料上传、课程构建、自由对话、测验与画像。
- `developer/`：本地开发、架构、workflows/infra、API 契约。
- `product/`：简短产品介绍，保持克制，不替代根 README。

写展示文档时优先回答“用户或开发者下一步该做什么”，避免把临时 prompt、调试记录、历史方案写进对外页面。

## 内部事实文档

现有目录暂时保留原位：

- `architecture/`
- `workflows/`
- `development/`
- `deployment/`
- `operations/`
- `product/`
- `standards/`
- `brand/`

如果展示文档和内部事实文档冲突，以当前代码、模块 README 和内部事实文档为准，并同步修正文档站内容。

## 本地预览

```powershell
cd docs
npm install
npm run dev
```

开发服务器默认由 Next.js 分配端口。访问根路径时会自动进入 `/docs`。

## 维护规则

- 新增展示页必须同步更新对应 `meta.json`。
- 用户教程要写成可执行路径，不要写抽象口号。
- 开发者文档只放稳定入口、边界和检查方式。
- 模块内部细节优先写在模块 README，例如 `backend/app/workflows/README.md` 和 `backend/app/shared/infra/README.md`。
- 文档不得包含真实密钥、私有部署地址、本机绝对路径或其他敏感内容。
