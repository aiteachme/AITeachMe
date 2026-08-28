FROM astral/uv:python3.12-trixie-slim

# 后端统一使用这份镜像定义；Render / Sealos / Compose 都应从仓库根目录构建。
# 这是轻量镜像，不包含 LibreOffice / soffice；需要本地 Office 转 PDF 时使用
# infra/deployment/docker/backend-office.Dockerfile。
# PYTHONUTF8 保证容器内读写和日志默认走 UTF-8，和本地开发约束保持一致。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HOME=/tmp \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 先只复制依赖清单，最大化 Docker layer cache；源码变化时不用重复解析锁文件。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-cache --extra cloud --no-install-project

# 再复制后端源码并安装当前项目本身。
COPY backend/ ./
RUN uv sync --locked --no-cache --extra cloud

# 构建期验证启动和本地文档兜底所需依赖，避免不完整镜像进入发布阶段。
RUN .venv/bin/python -c "from argon2 import PasswordHasher; import markitdown, pdfplumber, pptx"

ENV PATH="/app/.venv/bin:$PATH"

RUN groupadd --gid 10001 aiteachme \
    && useradd --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin --no-create-home aiteachme \
    && chown -R aiteachme:aiteachme /app

USER 10001:10001

# 默认部署端口统一为 9020；Render 等平台仍可通过 PORT 覆盖。
EXPOSE 9020

# start_cloud_app 会先校验完整云端配置并做数据库 bootstrap，再启动 uvicorn。
# 正式多副本平台如 Sealos 可改为单独 Job 跑迁移，Web 容器只跑 uvicorn。
CMD ["sh", "-c", "python scripts/start_cloud_app.py --host 0.0.0.0 --port ${PORT:-9020}"]
