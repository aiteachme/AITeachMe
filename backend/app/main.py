"""FastAPI application factory and top-level application wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.database import init_db
from app.core.exceptions import AITeachMeError
from app.core.logger import configure_logging

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize shared infrastructure when the ASGI app starts."""
    init_db()
    logger.info("app_started")
    yield
    logger.info("app_shutdown")


def _build_app_metadata() -> dict[str, object]:
    """Return the metadata block used when instantiating FastAPI."""

    return {
        "title": "AITeachMe",
        "description": (
            "AI 驱动的个性化学习助手后端。"
            "当前版本保持现有接口兼容，同时通过更完整的字段说明、示例和错误响应定义，"
            "让 OpenAPI / Redoc 更易读。"
        ),
        "version": "0.1.0",
        "lifespan": lifespan,
    }


def _register_middlewares(app: FastAPI) -> None:
    """Register all application middlewares in one place."""

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


def _register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers for business and unexpected errors."""

    @app.exception_handler(AITeachMeError)
    async def aiteachme_error_handler(request: Request, exc: AITeachMeError) -> JSONResponse:
        """Convert a known business exception into the standard JSON error payload."""

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_code": exc.error_code},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch unexpected exceptions, log them, and return a generic error payload."""

        logger.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "内部服务器错误", "error_code": "INTERNAL_ERROR"},
        )


def _register_routers(app: FastAPI) -> None:
    """Include all public route modules on the application."""

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    configure_logging()
    app = FastAPI(
        **_build_app_metadata(),
    )
    _register_middlewares(app)
    _register_exception_handlers(app)
    _register_routers(app)
    return app


app = create_app()
