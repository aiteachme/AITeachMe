# 本地开发

本文是 AITeachMe 本地开发入口。更细的后端、前端和工作流调试说明分别见对应模块 README。

## 环境要求

- Windows 优先支持。
- Python `3.11+`，项目默认使用 Conda 环境 `atm`。
- Node.js 建议 `18+`。
- 文件读写和终端输出尽量使用 UTF-8。

## 后端

```powershell
cd backend
conda activate atm
$env:PYTHONUTF8 = "1"
pip install -e .
uvicorn app.main:app --reload --port 9020
```

默认本地数据目录：

```text
backend/data/
```

默认 SQLite：

```text
backend/data/aiteachme.db
```

本地 SQLite 会在 schema drift 时做开发便利处理；云端 PostgreSQL 必须走 Alembic migration，见 [云端数据库迁移](../deployment/cloud-db-migrations.md)。

## 前端

```powershell
cd frontend
npm install
npm run dev
```

默认前端端口是 `5180`。开发模式通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:9020`。

后端 OpenAPI 变化后，通过 Orval 重新生成前端客户端；不要手改：

```text
frontend/src/api/generated/
```

## 一键脚本

仓库根目录提供 Windows 开发脚本：

```powershell
.\dev.bat
```

脚本会优先复用已有端口，也支持通过 `.env` 或环境变量覆盖：

```env
AITEACHME_BACKEND_PORT=9020
AITEACHME_FRONTEND_PORT=5180
AITEACHME_CONDA_ENV=atm
```

## 环境变量

本地用户侧变量以根目录 `.env.sample` 为主；开发、部署、验证码、通知等变量参考 `.env.developer.sample`。

最小本地示例：

```env
APP_MODE=local
AUTH_ENABLED=false
LLM_API_KEY=<model-api-key>
LLM_BASE_URL=https://api.example.com/v1
```

未开启鉴权的本地模型网关可以不填 `LLM_API_KEY`。实际模型槽位可在设置页或项目 settings override 中配置。

## 常用检查

```powershell
python scripts\check_mojibake.py docs
```

手动接口验证见 [manual-testing.md](./manual-testing.md)。
