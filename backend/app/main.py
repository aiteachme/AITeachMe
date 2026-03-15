"""
FastAPI 应用工厂 — 路由注册、CORS、全局异常处理器、数据库初始化
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.database import init_db
from app.core.exceptions import AITeachMeError

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时初始化数据库。"""
    init_db()
    logger.info("app_started")
    yield
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AITeachMe",
        description="AI 驱动的个性化学习助手后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://aiteachme.pages.dev",
            "http://localhost:5173",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 全局异常处理器 ──
    @app.exception_handler(AITeachMeError)
    async def aiteachme_error_handler(request: Request, exc: AITeachMeError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_code": exc.error_code},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "内部服务器错误", "error_code": "INTERNAL_ERROR"},
        )

    # ── 注册路由 ──
    from app.api.health import router as health_router
    from app.api.upload import router as upload_router
    from app.api.knowledge import router as knowledge_router
    from app.api.chat import router as chat_router
    from app.api.exam import router as exam_router
    from app.api.profile import router as profile_router

    app.include_router(health_router)
    app.include_router(upload_router)
    app.include_router(knowledge_router)
    app.include_router(chat_router)
    app.include_router(exam_router)
    app.include_router(profile_router)

    return app


app = create_app()
