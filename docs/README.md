# AITeachMe 文档维护说明

`docs/` 现在同时保留两类内容：

1. `docs/content/docs/`：Fumadocs 文档站的展示内容，只面向产品用户。
2. `docs/architecture`、`docs/workflows`、`docs/development` 等：仓库已有的内部事实文档，仅作为实现事实源保留，不进入对外文档站。

文档站不是另一个产品首页，也不单独承载营销落地页。根路径 `/` 仅重定向到 `/docs`，真正的阅读入口从 `/docs` 开始。

## 展示内容结构

文档站内容放在 `docs/content/docs/`：

- `index.mdx`：文档站总入口，说明推荐阅读路径和稳定概念。
- `quickstart/`：第一次使用、首页输入框和构建课程路径。
- `user-guide/`：资料上传、课程构建、自由对话、测验与画像。

写展示文档时优先回答“用户下一步该做什么”，避免把实现边界、临时 prompt、调试记录和历史方案写进对外页面。

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

文档站开发服务器固定使用 `5182` 端口；主前端开发服务器会把 `http://127.0.0.1:5180/docs` 代理到文档站。直接访问文档站根路径时会自动进入 `/docs`。

## 维护规则

- 新增展示页必须同步更新对应 `meta.json`。
- 用户教程要写成可执行路径，不要写抽象口号。
- 模块内部细节优先写在模块 README，例如 `backend/app/workflows/README.md` 和 `backend/app/shared/infra/README.md`。
- 文档不得包含真实密钥、私有部署地址、本机绝对路径或其他敏感内容。
