# 本地开发

## 环境

推荐 Python 版本：

- Python 3.10+

创建并激活虚拟环境：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
```

安装项目：

```bash
pip install -e .
```

## 配置

创建 `.env`：

```env
LLM_API_KEY=sk-your-api-key-here
APP_MODE=local
AUTH_ENABLED=false
```

创建 repo-root `config.yaml`：

```yaml
models:
  primary: qwen-plus-latest
  embedding: text-embedding-v3

planner:
  default_digest_mode: systematic

docgen:
  max_parallel_chapters: 20
```

约定：

- `.env` 放密钥、部署和外部接入参数
- repo 根目录 `.env.sample` 已按“基础必填 / 高级可选”分层，普通本地开发通常只需要前半部分
- `config.yaml` 放模型名、planner/docgen/search 等运行默认值
- 页面 UI 只做用户级或当前请求级覆盖

## 启动

```bash
uvicorn app.main:app --reload --port 8000
```

首次启动时若缺少 SQLite 相关 Python 依赖，服务会自动尝试安装并继续启动。
如果检测到 `data/aiteachme.db` schema 过期，服务会自动备份旧库并重建新库。
这个自动重建只适用于本地 SQLite。云端 PostgreSQL 使用 Alembic 迁移，
流程见 `docs/designs/16_cloud_db_migrations.md`。

## 本地数据

- 运行时数据默认写入 `data/`
- 数据库文件默认创建为 `data/aiteachme.db`
- 手动验证脚本放在 `playground/`
- `playground/inputs/` 放输入文件
- `playground/outputs/` 查看输出结果
