"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
import threading
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.shared.infra.config import get_settings
from app.shared.infra.database import init_db
from app.shared.infra.logger import configure_logging
from app.shared.infra.runtime_paths import get_runtime_data_dir, log_legacy_runtime_path_warnings
from app.shared.kernel.exceptions import AITeachMeError
from app.shared.infra.task_registry import BackgroundTaskRegistry

logger = structlog.get_logger()
_OPENAPI_EXPORT_LOCK = threading.Lock()
_OPENAPI_EXPORT_STARTED = False


def _maybe_export_openapi_schema(app: FastAPI) -> None:
    global _OPENAPI_EXPORT_STARTED

    settings = get_settings()
    if not settings.export_openapi_on_startup:
        return

    with _OPENAPI_EXPORT_LOCK:
        if _OPENAPI_EXPORT_STARTED:
            logger.info("openapi_export_already_scheduled")
            return
        _OPENAPI_EXPORT_STARTED = True

    def _run_export() -> None:
        try:
            import sys
            from pathlib import Path

            script_dir = Path(__file__).parent.parent / "scripts"
            sys.path.insert(0, str(script_dir))
            import export_api_docs

            logger.info("openapi_export_started")
            export_api_docs.export_openapi_schema(app)
            logger.info("openapi_export_finished")
        except Exception as exc:  # noqa: BLE001
            logger.error("export_openapi_failed", error=str(exc))
        finally:
            try:
                sys.path.pop(0)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(
        target=_run_export,
        name="openapi-export",
        daemon=True,
    ).start()


def _log_infra_diagnostics(settings) -> None:
    """启动时输出基础设施诊断信息，方便在 Render Logs 里排查。"""

    import os
    from app.shared.infra.database import get_engine, is_postgres, is_sqlite, is_vec_ready
    from app.teaching.runtime_config import get_teaching_runtime_config_path

    engine = get_engine()
    dialect = engine.dialect.name
    project_config_path = get_teaching_runtime_config_path()

    lines = [
        "",
        "=" * 60,
        "  AITeachMe Infrastructure Diagnostics",
        "=" * 60,
        "",
        "  [ENV]",
        f"    APP_MODE (raw env)     : {os.environ.get('APP_MODE', '!! NOT_SET !!')}",
        f"    APP_MODE (resolved)    : {settings.resolved_app_mode}",
        f"    DATABASE_URL           : {'SET' if os.environ.get('DATABASE_URL') else '!! NOT_SET !!'}",
        f"    STORAGE_BACKEND        : {os.environ.get('STORAGE_BACKEND', '!! NOT_SET !!')}",
        f"    PROJECT_CONFIG_PATH    : {project_config_path}",
        f"    RENDER                 : {os.environ.get('RENDER', 'NOT_SET')}",
        "",
        "  [DATABASE]",
        f"    Dialect                : {dialect}",
    ]

    if is_postgres():
        lines.append(f"    Host                   : {engine.url.host or 'unknown'}")
        lines.append(f"    Database               : {engine.url.database or 'unknown'}")
        lines.append(f"    pgvector               : ready")
    elif is_sqlite():
        lines.append(f"    sqlite-vec             : {'ready' if is_vec_ready() else 'NOT available'}")

    lines.append("")
    lines.append("  [STORAGE]")
    lines.append(f"    Backend                : {settings.storage_backend}")

    if settings.storage_is_s3:
        lines.append(f"    S3 Bucket              : {settings.s3_bucket or '!! NOT_SET !!'}")
        lines.append(f"    S3 Endpoint            : {settings.s3_endpoint or '!! NOT_SET !!'}")
        lines.append(f"    S3 CDN                 : {settings.s3_public_base_url or 'none'}")
        lines.append(f"    S3 Addressing Style    : {settings.resolved_s3_addressing_style}")
        lines.append(f"    S3 Credential Mode     : {settings.resolved_s3_credential_mode}")
        lines.append(
            f"    S3 Session Token       : {'SET' if settings.s3_session_token or settings.s3_uses_dogecloud_tmp_token else 'not used'}"
        )
        if settings.s3_uses_dogecloud_tmp_token:
            lines.append(
                f"    DogeCloud Space Name   : {settings.resolved_dogecloud_space_name or '!! NOT_SET !!'}"
            )
        # ── S3 冒烟测试（写→读→删）── 后续可删除此段 ──
        try:
            from app.shared.infra.storage import get_artifact_store, run_store_sync
            store = get_artifact_store()
            test_key = "__healthcheck/startup_test.txt"
            test_data = b"aiteachme-s3-smoke-test-ok"
            # 1. 写入
            run_store_sync(store.write_bytes, test_key, test_data)
            lines.append(f"    S3 Write               : OK")
            # 2. 读取并验证
            read_back = run_store_sync(store.read_bytes, test_key)
            if read_back == test_data:
                lines.append(f"    S3 Read & Verify       : OK ({len(read_back)} bytes)")
            else:
                lines.append(f"    S3 Read & Verify       : MISMATCH!")
            # 3. 删除
            run_store_sync(store.delete, test_key)
            exists_after = run_store_sync(store.exists, test_key)
            lines.append(f"    S3 Delete              : {'OK' if not exists_after else 'FAILED - still exists'}")
            lines.append(f"    S3 Smoke Test          : ALL PASSED")
        except Exception as exc:
            lines.append(f"    S3 Smoke Test          : FAILED - {exc}")
    else:
        from app.shared.infra.runtime_paths import get_runtime_data_dir
        lines.append(f"    Data Dir               : {get_runtime_data_dir()}")

    lines.append("")
    lines.append("  [TEACHING]")
    lines.append(f"    Primary Model          : {settings.llm_model}")
    lines.append(f"    Light Model            : {settings.llm_model_light or settings.llm_model}")
    lines.append(f"    Extract Model          : {settings.llm_model_extract or settings.llm_model}")
    lines.append(f"    Embedding Model        : {settings.embedding_model}")
    lines.append(f"    OCR Model              : {settings.ocr_model or settings.llm_model}")
    lines.append(
        f"    MinerU Server Token    : {'SET' if settings.mineru_api_token else 'not set'}"
    )
    lines.append(
        f"    Mermaid Model          : {settings.mermaid_generation_model or 'disabled'}"
    )
    lines.append(
        f"    Image Model            : {settings.image_generation_model or 'disabled'}"
    )

    lines.append("")
    lines.append("  [AUTH]")
    lines.append(f"    Enabled                : {settings.auth_enabled}")

    status = "CLOUD" if settings.resolved_app_mode == "cloud" else "LOCAL"
    lines.append("")
    lines.append(f"  >>> Running in {status} mode <<<")
    lines.append("")
    lines.append("=" * 60)
    lines.append("")

    print("\n".join(lines), flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期。"""

    app.state.background_task_registry = BackgroundTaskRegistry()
    init_db()
    _maybe_export_openapi_schema(app)

    # ── 启动诊断日志 ──
    settings = get_settings()
    _log_infra_diagnostics(settings)

    logger.info(
        "app_started",
        app_mode=settings.resolved_app_mode,
        guest_cookie_samesite=settings.resolved_guest_cookie_samesite,
        guest_cookie_secure=settings.resolved_guest_cookie_secure,
    )
    yield
    await app.state.background_task_registry.shutdown(cancel_timeout_s=8.0)
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
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    configured = settings.cors_allowed_origins
    origins = [o.strip() for o in configured.split(",") if o.strip()] if configured else default_origins
    logger.info("cors_configured", allow_origins=origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_static_mounts(app: FastAPI) -> None:
    settings = get_settings()
    if settings.is_local_mode:
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
                "data": exc.data,
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
    from app.api.export_import import router as export_import_router
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
    app.include_router(export_import_router)


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
