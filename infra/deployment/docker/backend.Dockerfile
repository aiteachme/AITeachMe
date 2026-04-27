FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# 后端统一使用这份镜像定义；Render / Sealos / Compose 都应从仓库根目录构建。
# PYTHONUTF8 保证容器内读写和日志默认走 UTF-8，和本地开发约束保持一致。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# LibreOffice/soffice 用于 .doc -> .docx、PPT/PPTX -> PDF 等本地文件转换。
# Noto 字体用于减少中文文档和符号转换时的乱码/缺字。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        libreoffice \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

# 先只复制依赖清单，最大化 Docker layer cache；源码变化时不用重复解析锁文件。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-cache --no-install-project

# 再复制后端源码并安装当前项目本身。
COPY backend/ ./
RUN uv sync --frozen --no-cache

ENV PATH="/app/.venv/bin:$PATH"

# Render 默认通过 PORT 注入监听端口；Compose 会显式设置 PORT=9020。
EXPOSE 10000

# start_cloud_app 会在 APP_MODE=cloud 时先做数据库 bootstrap，再启动 uvicorn。
# 正式多副本平台如 Sealos 可改为单独 Job 跑迁移，Web 容器只跑 uvicorn。
CMD ["sh", "-c", "python scripts/start_cloud_app.py --host 0.0.0.0 --port ${PORT:-10000}"]
