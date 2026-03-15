# Windows 开发

## Windows 环境配置

### 1. python 环境

```bash
uv venv --python 3.11
.\.venv\Scripts\Activate.ps1
python -m ensurepip --upgrade
python -m pip install -U pip setuptools wheel
python -m pip -V
```

```bash
python -m venv .venv # requires Python >=3.10, <=3.13
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
```

```bash
pip install -r requirements.txt
```

### 2. 环境变量配置

推荐先运行：

```bash
python scripts/init_env.py
```

如果你想手动创建 `.env`，再执行下面这步：

```bash
cp .env.example .env
```

编辑 `.env`，填入以下字段：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_API_KEY` | ✅ | — | LLM 服务的 API Key（如阿里云百炼） |
| `LLM_BASE_URL` | | `https://dashscope.aliyuncs.com/compatible-mode/v1` | LLM API 地址 |
| `LLM_MODEL` | | `qwen-plus` | 使用的语言模型 |
| `EMBEDDING_MODEL` | | `text-embedding-v3` | 向量嵌入模型 |
| `DATA_DIR` | | `./data` | 数据存储目录 |
| `MAX_UPLOAD_SIZE_MB` | | `50` | 上传文件大小上限（MB） |
| `RAG_TOP_K` | | `5` | RAG 检索返回的 Top K 数量 |
| `RAG_SIMILARITY_THRESHOLD` | | `0.3` | RAG 相似度阈值 |
| `CHAT_HISTORY_TURNS` | | `10` | 对话历史保留轮数 |

建议在启动前先验证一次配置：

```bash
python scripts/test_env.py
```
