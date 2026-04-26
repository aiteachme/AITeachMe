FROM python:3.10-slim

WORKDIR /app

# 安装依赖
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir -e .

# 复制应用代码
COPY backend/ .

# 暴露端口
EXPOSE 9020

# 启动命令
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9020"]
