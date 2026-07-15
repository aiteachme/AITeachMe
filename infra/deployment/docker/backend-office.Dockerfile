FROM astral/uv:python3.12-trixie-slim

# Office 镜像用于后续恢复 .doc / .ppt / .pptx 本地转 PDF 能力。
# 系统依赖必须在镜像构建期安装，不在 Sealos/Render 容器启动时临时 apt install。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    SAL_USE_VCLPLUGIN=svp

WORKDIR /app

# LibreOffice 转换链路依赖 Impress/Writer；Noto CJK 避免中文 PPT/PDF 缺字。
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-impress \
    libreoffice-writer \
    libreoffice-calc \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-liberation \
    fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# 先只复制依赖清单，最大化 Docker layer cache；源码变化时不用重复解析锁文件。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-cache --extra cloud --no-install-project

# 再复制后端源码并安装当前项目本身。
COPY backend/ ./
RUN uv sync --frozen --no-cache --extra cloud

ENV PATH="/app/.venv/bin:$PATH"

# 构建阶段直接验证 soffice 存在，避免部署后才发现系统依赖缺失。
RUN command -v soffice && soffice --headless --version

RUN groupadd --gid 10001 aiteachme \
    && useradd --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin --no-create-home aiteachme \
    && chown -R aiteachme:aiteachme /app

USER 10001:10001

# 默认部署端口统一为 9020；Render 等平台仍可通过 PORT 覆盖。
EXPOSE 9020

# 默认命令会校验完整云端配置；正式多副本仍建议单独 Job 跑 bootstrap，Web 只跑 uvicorn。
CMD ["sh", "-c", "python scripts/start_cloud_app.py --host 0.0.0.0 --port ${PORT:-9020}"]
