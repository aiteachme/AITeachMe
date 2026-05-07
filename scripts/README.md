# Scripts

`scripts/` 放仓库级辅助脚本，主要用于本地检查和一次性维护任务。

当前脚本：

- `check_mojibake.py`：检查文档或源码中的常见乱码。
- `cleanup_residual_dirs.py`：清理重构后遗留的空目录或残留目录。
- `build_backend_image.ps1`：本地构建后端镜像的辅助入口。

业务功能、部署编排和桌面端打包不要放这里：

- 后端业务脚本放 `backend/scripts/`。
- 部署资产放 `infra/deployment/`。
- 桌面端打包放 `packaging/`。
