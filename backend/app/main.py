"""FastAPI 应用入口。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import init_db
from app.core.exceptions import AITeachMeError
from app.core.logger import configure_logging

logger = structlog.get_logger()


def _sync_frontend_api_client(app: FastAPI) -> None:
    """导出 OpenAPI 并尝试触发 Orval 生成前端客户端。"""

    if os.getenv("AITEACHME_SYNC_OPENAPI", "true").lower() in {"0", "false", "no"}:
        logger.info("sync_openapi_skipped", reason="env_disabled")
        return

    project_root = Path(__file__).resolve().parents[2]
    frontend_dir = project_root / "frontend"
    openapi_path = frontend_dir / "openapi.json"
    orval_config = frontend_dir / "orval.config.js"
    generated_dir = frontend_dir / "src" / "api" / "generated"

    if not frontend_dir.exists():
        logger.info("sync_openapi_skipped", reason="frontend_not_found", path=str(frontend_dir))
        return

    try:
        schema = app.openapi()
        payload = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        openapi_path.parent.mkdir(parents=True, exist_ok=True)

        previous = openapi_path.read_text(encoding="utf-8") if openapi_path.exists() else ""
        schema_changed = previous != payload
        if schema_changed:
            openapi_path.write_text(payload, encoding="utf-8")
            logger.info("openapi_exported", path=str(openapi_path))
        else:
            logger.info("openapi_unchanged", path=str(openapi_path))

        should_run_orval = schema_changed or not generated_dir.exists()
        if not should_run_orval:
            logger.info("orval_generation_skipped", reason="schema_unchanged")
            return

        if not orval_config.exists():
            logger.warning("orval_generation_skipped", reason="config_missing", path=str(orval_config))
            return

        npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
        result = subprocess.run(
            [npx_cmd, "orval", "--config", orval_config.name],
            cwd=frontend_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("orval_generation_succeeded", output_dir=str(generated_dir))
            return

        logger.warning(
            "orval_generation_failed",
            returncode=result.returncode,
            stdout=(result.stdout or "").strip()[-800:],
            stderr=(result.stderr or "").strip()[-800:],
        )
    except Exception as exc:
        logger.warning("sync_openapi_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期。"""

    init_db()
    _sync_frontend_api_client(app)
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
    from app.api.assessment import router as assessment_router
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
    app.include_router(assessment_router)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""

    configure_logging()
    app = FastAPI(**_build_app_metadata())
    _register_middlewares(app)
    _register_exception_handlers(app)
    _register_routers(app)
    return app


app = create_app()
