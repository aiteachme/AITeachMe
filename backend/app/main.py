"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import init_db
from app.core.exceptions import AITeachMeError
from app.core.logger import configure_logging
from app.core.runtime_paths import get_runtime_data_dir, log_legacy_runtime_path_warnings

logger = structlog.get_logger()


def _maybe_export_openapi_schema(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.export_openapi_on_startup:
        return

    try:
        import sys
        from pathlib import Path

        script_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(script_dir))
        import export_api_docs

        export_api_docs.export_openapi_schema(app)
        sys.path.pop(0)
    except Exception as exc:  # noqa: BLE001
        logger.error("export_openapi_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期。"""

    init_db()
    _maybe_export_openapi_schema(app)

    logger.info("app_started")
    yield
    logger.info("app_shutdown")


def _build_app_metadata() -> dict[str, object]:
    settings = get_settings()
    return {
        "title": "AITeachMe",
        "description": "本地优先的 AI 助教后端服务。",
        "version": settings.app_version,
        "lifespan": lifespan,
    }


def _register_middlewares(app: FastAPI) -> None:
    settings = get_settings()
    # 从环境变量读取允许的跨域来源（逗号分隔），或使用默认白名单
    default_origins = [
        "https://aiteachme.cn",
        "https://www.aiteachme.cn",
        "https://aiteachme.pages.dev",
        "http://localhost:5173",
        "http://localhost:3000",
    ]
    configured = settings.cors_allowed_origins
    origins = [o.strip() for o in configured.split(",") if o.strip()] if configured else default_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_static_mounts(app: FastAPI) -> None:
    log_legacy_runtime_path_warnings()
    data_dir = get_runtime_data_dir()
    app.mount("/_assets", StaticFiles(directory=data_dir), name="runtime-assets")


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AITeachMeError)
    async def aiteachme_error_handler(request: Request, exc: AITeachMeError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "error_code": exc.error_code,
                "message": exc.detail,
                "data": None,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "服务内部异常。",
                "data": None,
            },
        )


def _register_routers(app: FastAPI) -> None:
    from app.api.auth import router as auth_router
    from app.api.chats import router as chats_router
    from app.api.exams import router as exams_router
    from app.api.files import router as files_router
    from app.api.health import router as health_router
    from app.api.knowledge import router as knowledge_router
    from app.api.profile import router as profile_router
    from app.api.subjects import router as subjects_router
    from app.api.system import router as system_router

    app.include_router(health_router)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(subjects_router)
    app.include_router(files_router)
    app.include_router(knowledge_router)
    app.include_router(chats_router)
    app.include_router(exams_router)
    app.include_router(profile_router)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""

    configure_logging()
    app = FastAPI(**_build_app_metadata())
    _register_middlewares(app)
    _register_static_mounts(app)
    _register_exception_handlers(app)
    _register_routers(app)
    return app


app = create_app()
