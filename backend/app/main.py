"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import sys
from time import perf_counter
from typing import AsyncGenerator
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.shared.infra.settings import get_settings
from app.shared.infra.database import init_db
from app.shared.infra.env_support import get_env, get_env_bool, get_env_list
from app.shared.infra.logger import (
    bind_logging_context,
    clear_logging_context,
    configure_logging,
)
from app.shared.infra.runtime import get_runtime_data_dir
from app.shared.infra.runtime import (
    get_app_version,
    resolve_auth_enabled,
    resolve_app_mode,
    resolve_guest_cookie_samesite,
    resolve_guest_cookie_secure,
)
from app.shared.infra.storage.config import (
    get_storage_backend,
    resolve_dogecloud_space_name,
    resolve_s3_addressing_style,
    resolve_s3_credential_mode,
    s3_uses_dogecloud_tmp_token,
    storage_is_s3,
)
from app.shared.infra.exceptions import AITeachMeError as InfraAITeachMeError
from app.shared.kernel.exceptions import AITeachMeError as KernelAITeachMeError
from app.shared.infra.runtime import BackgroundTaskRegistry
from app.shared.infra.settings.support import (
    get_llm_provider_model_defaults,
    llm_provider_requires_api_key,
    resolve_runtime_llm_provider,
)

logger = structlog.get_logger()


def _log_infra_diagnostics(settings) -> None:
    """启动时输出基础设施诊断信息，方便在 Render Logs 里排查。"""

    import os
    from app.shared.infra.database import get_engine, is_postgres, is_sqlite
    from app.workflows.digest.common.runtime_config import (
        get_teaching_runtime_settings_source,
    )

    engine = get_engine()
    dialect = engine.dialect.name
    project_settings_source = get_teaching_runtime_settings_source()
    llm_base_url = get_env("LLM_BASE_URL")
    llm_api_keys = get_env_list("LLM_API_KEY")
    runtime_provider = resolve_runtime_llm_provider(base_url=llm_base_url)
    runtime_provider_defaults = get_llm_provider_model_defaults(runtime_provider)
    openai_compatible_defaults = get_llm_provider_model_defaults("openai_compatible")

    app_mode = resolve_app_mode()
    storage_backend = get_storage_backend()
    uses_s3 = storage_is_s3()
    uses_dogecloud_tmp_token = s3_uses_dogecloud_tmp_token()

    lines = [
        "",
        "=" * 60,
        "  AITeachMe Infrastructure Diagnostics",
        "=" * 60,
        "",
        "  [ENV]",
        f"    APP_MODE (raw env)     : {os.environ.get('APP_MODE', '!! NOT_SET !!')}",
        f"    APP_MODE (resolved)    : {app_mode}",
        f"    DATABASE_URL           : {'SET' if os.environ.get('DATABASE_URL') else '!! NOT_SET !!'}",
        f"    STORAGE_BACKEND        : {os.environ.get('STORAGE_BACKEND', '!! NOT_SET !!')}",
        f"    Settings Source        : {project_settings_source}",
        f"    RENDER                 : {os.environ.get('RENDER', 'NOT_SET')}",
        f"    LLM_BASE_URL           : {'SET' if llm_base_url else '!! NOT_SET !!'}",
        f"    LLM_API_KEY            : {'SET' if llm_api_keys else '!! NOT_SET !!'}",
        "",
        "  [DATABASE]",
        f"    Dialect                : {dialect}",
    ]

    if is_postgres():
        lines.append(f"    Host                   : {engine.url.host or 'unknown'}")
        lines.append(f"    Database               : {engine.url.database or 'unknown'}")
        lines.append(f"    pgvector               : ready")
    elif is_sqlite():
        lines.append("    Subject Vector Index   : local subject-scoped store")

    lines.append("")
    lines.append("  [STORAGE]")
    lines.append(f"    Backend                : {storage_backend}")

    if uses_s3:
        lines.append(f"    S3 Bucket              : {get_env('S3_BUCKET') or '!! NOT_SET !!'}")
        lines.append(f"    S3 Endpoint            : {get_env('S3_ENDPOINT') or '!! NOT_SET !!'}")
        lines.append(f"    S3 CDN                 : {get_env('S3_PUBLIC_BASE_URL') or 'none'}")
        lines.append(f"    S3 Addressing Style    : {resolve_s3_addressing_style()}")
        lines.append(f"    S3 Credential Mode     : {resolve_s3_credential_mode()}")
        lines.append(
            f"    S3 Session Token       : {'SET' if get_env('S3_SESSION_TOKEN') or uses_dogecloud_tmp_token else 'not used'}"
        )
        if uses_dogecloud_tmp_token:
            lines.append(
                f"    DogeCloud Space Name   : {resolve_dogecloud_space_name() or '!! NOT_SET !!'}"
            )
        if get_env_bool("S3_STARTUP_SMOKE_TEST", False):
            try:
                from app.shared.infra.storage import get_artifact_store, run_store_sync

                store = get_artifact_store()
                test_key = "__healthcheck/startup_test.txt"
                test_data = b"aiteachme-s3-smoke-test-ok"
                run_store_sync(store.write_bytes, test_key, test_data)
                lines.append("    S3 Write               : OK")
                read_back = run_store_sync(store.read_bytes, test_key)
                if read_back == test_data:
                    lines.append(f"    S3 Read & Verify       : OK ({len(read_back)} bytes)")
                else:
                    lines.append("    S3 Read & Verify       : MISMATCH!")
                run_store_sync(store.delete, test_key)
                exists_after = run_store_sync(store.exists, test_key)
                lines.append(f"    S3 Delete              : {'OK' if not exists_after else 'FAILED - still exists'}")
                lines.append("    S3 Smoke Test          : ALL PASSED")
            except Exception as exc:
                lines.append(f"    S3 Smoke Test          : FAILED - {exc}")
        else:
            lines.append("    S3 Smoke Test          : skipped (set S3_STARTUP_SMOKE_TEST=true)")
    else:
        lines.append(f"    Data Dir               : {get_runtime_data_dir()}")

    lines.append("")
    lines.append("  [TEACHING]")
    lines.append(f"    Reason Model           : {settings.models.reason or settings.models.primary}")
    lines.append(f"    Primary Text Model     : {settings.models.primary}")
    lines.append(f"    Light Text Model       : {settings.models.light or settings.models.primary}")
    lines.append(f"    Vision Model           : {settings.models.vision or 'disabled'}")
    lines.append(f"    Document OCR Model     : {settings.models.ocr or 'disabled'}")
    lines.append(f"    Embedding Model        : {settings.models.embedding}")
    lines.append(f"    Rerank Model           : {settings.models.rerank or 'disabled'}")
    mineru_tokens = get_env_list("MINERU_API_TOKENS") or get_env_list("MINERU_API_TOKEN")
    lines.append(f"    MinerU Server Token    : {'SET' if mineru_tokens else 'not set'}")
    lines.append(
        f"    Image Generation Model : {settings.models.image_generation or 'disabled'}"
    )
    lines.append(f"    Speech->Text Model     : {settings.models.speech_to_text or 'disabled'}")
    lines.append(f"    Text->Speech Model     : {settings.models.text_to_speech or 'disabled'}")
    lines.append(f"    Video Model            : {settings.models.video_generation or 'disabled'}")
    lines.append(f"    Runtime Provider       : {runtime_provider}")
    if llm_provider_requires_api_key(runtime_provider, base_url=llm_base_url) and not llm_api_keys:
        lines.append("    LLM Connectivity       : NOT_READY (missing LLM_API_KEY)")
    else:
        lines.append("    LLM Connectivity       : READY")
    lines.append("    Runtime Provider Defaults:")
    for raw_line in json.dumps(
        runtime_provider_defaults,
        ensure_ascii=False,
        indent=6,
    ).splitlines():
        lines.append(f"      {raw_line}")
    lines.append("    openai_compatible Defaults:")
    for raw_line in json.dumps(
        openai_compatible_defaults,
        ensure_ascii=False,
        indent=6,
    ).splitlines():
        lines.append(f"      {raw_line}")

    lines.append("")
    lines.append("  [AUTH]")
    lines.append(f"    Enabled                : {resolve_auth_enabled()}")

    status = "CLOUD" if app_mode == "cloud" else "LOCAL"
    lines.append("")
    lines.append(f"  >>> Running in {status} mode <<<")
    lines.append("")
    lines.append("=" * 60)
    lines.append("")

    diagnostics_text = "\n".join(lines).lstrip("\n")
    print(diagnostics_text, file=sys.stderr, flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期。"""

    app.state.background_task_registry = BackgroundTaskRegistry()
    init_db()

    # ── 启动诊断日志 ──
    settings = get_settings()
    _log_infra_diagnostics(settings)

    from app.workflows.ingest import recover_stalled_enhancements

    app.state.background_task_registry.spawn(
        recover_stalled_enhancements(task_registry=app.state.background_task_registry),
        kind="ingest.recovery",
        name="ingest.recovery",
    )

    logger.info(
        "app_started",
        app_mode=resolve_app_mode(),
        guest_cookie_samesite=resolve_guest_cookie_samesite(),
        guest_cookie_secure=resolve_guest_cookie_secure(),
    )
    yield
    await app.state.background_task_registry.shutdown(cancel_timeout_s=8.0)
    logger.info("app_shutdown")


def _build_app_metadata() -> dict[str, object]:
    return {
        "title": "AITeachMe",
        "description": "本地优先的 AI 助教后端服务。",
        "version": get_app_version(),
        "lifespan": lifespan,
    }


def _register_middlewares(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        clear_logging_context()

        request_id = (request.headers.get("x-request-id") or "").strip() or uuid.uuid4().hex
        client_ip = request.client.host if request.client is not None else None
        bind_logging_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
        )

        access_logger = structlog.get_logger("app.access")
        started_at = perf_counter()
        try:
            response = await call_next(request)
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            response.headers.setdefault("x-request-id", request_id)

            if request.url.path == "/api/health":
                access_logger.debug(
                    "request_completed",
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                )
            else:
                log_method = access_logger.warning if response.status_code >= 500 else access_logger.info
                log_method(
                    "request_completed",
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                )
            return response
        except Exception:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            access_logger.exception("request_failed", elapsed_ms=elapsed_ms)
            return JSONResponse(
                status_code=500,
                headers={"x-request-id": request_id},
                content={
                    "code": 500,
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "message": "服务内部异常。",
                    "data": None,
                },
            )
        finally:
            clear_logging_context()

    # 从环境变量读取允许的跨域来源（逗号分隔），或使用默认白名单
    default_origins = [
        "https://aiteachme.cn",
        "https://www.aiteachme.cn",
        "https://aiteachme.pages.dev",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    configured = get_env("CORS_ALLOWED_ORIGINS", "")
    origins = [o.strip() for o in configured.split(",") if o.strip()] if configured else default_origins
    logger.info("cors_configured", allow_origins=origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(KernelAITeachMeError)
    @app.exception_handler(InfraAITeachMeError)
    async def aiteachme_error_handler(
        request: Request,
        exc: KernelAITeachMeError | InfraAITeachMeError,
    ) -> JSONResponse:
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
    from app.api.chats import global_router as global_chats_router
    from app.api.chats import router as chats_router
    from app.api.exams import router as exams_router
    from app.api.export_import import router as export_import_router
    from app.api.files import router as files_router
    from app.api.health import router as health_router
    from app.api.knowledge import router as knowledge_router
    from app.api.profile import router as profile_router
    from app.api.subjects import router as subjects_router
    from app.api.system import router as system_router
    from app.api.user_files import router as user_files_router

    app.include_router(health_router)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(subjects_router)
    app.include_router(user_files_router)
    app.include_router(files_router)
    app.include_router(knowledge_router)
    app.include_router(global_chats_router)
    app.include_router(chats_router)
    app.include_router(exams_router)
    app.include_router(profile_router)
    app.include_router(export_import_router)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""

    configure_logging()
    app = FastAPI(**_build_app_metadata())
    _register_middlewares(app)
    _register_exception_handlers(app)
    _register_routers(app)
    return app


app = create_app()
