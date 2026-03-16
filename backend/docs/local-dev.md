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

可选配置：

- `LLM_BASE_URL`
- `LLM_MODEL`
- `EMBEDDING_MODEL`
- `DATA_DIR`
- `MAX_UPLOAD_SIZE_MB`
- `RAG_TOP_K`
- `RAG_SIMILARITY_THRESHOLD`
- `CHAT_HISTORY_TURNS`

## 启动

```bash
uvicorn app.main:app --reload --port 8000
```

## 本地数据

- 运行时数据默认写入 `data/`
- 手动验证脚本放在 `playground/`
- `playground/inputs/` 放输入文件
- `playground/outputs/` 查看输出结果
