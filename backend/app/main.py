"""FastAPI 应用入口。"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import threading
from time import perf_counter
from typing import Any, AsyncGenerator
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.shared.infra.settings import (
    PROJECT_SETTINGS_ENV_NAME,
    get_settings,
    get_system_settings_override_payload,
)
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
    resolve_runtime_llm_provider,
)
from app.shared.infra.llm_support.common import get_llm_runtime_snapshot

logger = structlog.get_logger()

_OPENAPI_EXPORT_LOCK = threading.Lock()
_OPENAPI_EXPORT_STARTED = False

_SENSITIVE_SETTING_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|access[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)


def _redact_for_logs(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = (
                "<redacted>"
                if _SENSITIVE_SETTING_KEY_RE.search(key_text)
                else _redact_for_logs(item)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_for_logs(item) for item in value]
    return value


def _run_openapi_export(app: FastAPI) -> None:
    script_dir = Path(__file__).parent.parent / "scripts"
    script_dir_text = str(script_dir)
    sys.path.insert(0, script_dir_text)
    try:
        import export_api_docs

        logger.info("openapi_export_started")
        if not export_api_docs.export_openapi_schema(app):
            raise RuntimeError("OpenAPI export returned false")
        logger.info("openapi_export_finished")
    finally:
        try:
            sys.path.remove(script_dir_text)
        except ValueError:
            pass


def _maybe_export_openapi_schema(app: FastAPI) -> None:
    global _OPENAPI_EXPORT_STARTED

    if not get_env_bool("EXPORT_OPENAPI_ON_STARTUP", False):
        return

    with _OPENAPI_EXPORT_LOCK:
        if _OPENAPI_EXPORT_STARTED:
            logger.info("openapi_export_already_scheduled")
            return
        _OPENAPI_EXPORT_STARTED = True

    def _run_export() -> None:
        try:
            _run_openapi_export(app)
        except Exception as exc:  # noqa: BLE001
            logger.error("export_openapi_failed", error=str(exc))

    threading.Thread(
        target=_run_export,
        name="openapi-export",
        daemon=True,
    ).start()


def _format_utc_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _inspect_project_settings_file() -> dict[str, Any]:
    from app.shared.infra.env_support import resolve_project_settings_path
    from app.shared.infra.settings.support import parse_yaml_mapping

    configured_value = (get_env(PROJECT_SETTINGS_ENV_NAME) or "").strip()
    resolved_path = resolve_project_settings_path()
    info: dict[str, Any] = {
        "env_name": PROJECT_SETTINGS_ENV_NAME,
        "configured_value": configured_value or None,
        "resolved_path": str(resolved_path) if resolved_path is not None else None,
        "status": "not_configured",
        "exists": False,
        "is_file": False,
        "readable": False,
        "size_bytes": None,
        "modified_at": None,
        "loaded_keys": [],
        "override_payload": {},
    }
    if resolved_path is None:
        return info

    try:
        exists = resolved_path.exists()
        is_file = resolved_path.is_file() if exists else False
        info.update(
            {
                "exists": exists,
                "is_file": is_file,
                "status": "missing" if not exists else "not_file",
            }
        )
        if not exists or not is_file:
            return info

        stat = resolved_path.stat()
        info["size_bytes"] = stat.st_size
        info["modified_at"] = _format_utc_timestamp(stat.st_mtime)

        text = resolved_path.read_text(encoding="utf-8")
        info["readable"] = True
        payload = parse_yaml_mapping(text)
        info["status"] = (
            "loaded"
            if payload
            else ("empty" if not text.strip() else "loaded_empty_mapping")
        )
        info["loaded_keys"] = sorted(str(key) for key in payload.keys())
        info["override_payload"] = _redact_for_logs(payload)
        return info
    except Exception as exc:  # noqa: BLE001
        info["status"] = "read_or_parse_failed"
        info["error"] = str(exc)
        return info


def _log_infra_diagnostics(settings) -> None:
    """启动时输出基础设施诊断信息，方便在 Render Logs 里排查。"""

    from app.shared.infra.database import get_engine, is_postgres, is_sqlite
    from app.workflows.digest.common.runtime_config import (
        get_teaching_runtime_settings_source,
    )

    engine = get_engine()
    dialect = engine.dialect.name
    project_settings_source = get_teaching_runtime_settings_source()
    llm_base_url = get_env("LLM_BASE_URL")
    llm_api_keys = get_env_list("LLM_API_KEY")
    llm_snapshot = get_llm_runtime_snapshot()
    primary_endpoint_count = len(llm_snapshot.primary_endpoints)
    fallback_endpoint_count = len(llm_snapshot.fallback_endpoints)
    runtime_provider = resolve_runtime_llm_provider(base_url=llm_base_url)
    runtime_provider_defaults = get_llm_provider_model_defaults(runtime_provider)
    openai_compatible_defaults = get_llm_provider_model_defaults("openai_compatible")
    settings_file_info = _inspect_project_settings_file()
    system_override_payload = get_system_settings_override_payload()
    effective_settings_payload = _redact_for_logs(settings.model_dump(mode="json"))

    app_mode = resolve_app_mode()
    storage_backend = get_storage_backend()
    uses_s3 = storage_is_s3()
    uses_dogecloud_tmp_token = s3_uses_dogecloud_tmp_token()

    logger.info(
        "runtime_settings_loaded",
        project_settings_file=settings_file_info,
        settings_source=project_settings_source,
        project_settings_file_loaded=settings_file_info["status"] == "loaded",
        system_override_present=bool(system_override_payload),
        system_override_keys=sorted(str(key) for key in system_override_payload.keys()),
        effective_settings=effective_settings_payload,
    )
    if settings_file_info["configured_value"] and settings_file_info["status"] != "loaded":
        logger.warning(
            "project_settings_file_not_loaded",
            project_settings_file=settings_file_info,
        )

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
        f"    LLM_BASE_URL           : {'SET' if llm_base_url else '!! NOT_SET !!'}",
        f"    LLM_API_KEY            : {'SET' if llm_api_keys else '!! NOT_SET !!'}",
        f"    LLM Primary Endpoints  : {primary_endpoint_count}",
        f"    LLM Fallback Endpoints : {fallback_endpoint_count}",
        "",
        "  [SETTINGS]",
        f"    {PROJECT_SETTINGS_ENV_NAME:<23}: {settings_file_info['configured_value'] or '!! NOT_SET !!'}",
        f"    Resolved Path          : {settings_file_info['resolved_path'] or 'none'}",
        f"    Source Label           : {project_settings_source}",
        f"    File Status            : {settings_file_info['status']}",
        f"    Exists / Is File       : {settings_file_info['exists']} / {settings_file_info['is_file']}",
        f"    Readable               : {settings_file_info['readable']}",
        f"    Size Bytes             : {settings_file_info['size_bytes'] if settings_file_info['size_bytes'] is not None else 'n/a'}",
        f"    Modified At            : {settings_file_info['modified_at'] or 'n/a'}",
        f"    Loaded Top-Level Keys  : {', '.join(settings_file_info['loaded_keys']) or 'none'}",
        f"    DB Runtime Override    : {'enabled' if system_override_payload else 'none'}",
        f"    DB Override Keys       : {', '.join(sorted(str(key) for key in system_override_payload.keys())) or 'none'}",
        "",
        "    Project Override Payload:",
    ]
    for raw_line in json.dumps(
        settings_file_info["override_payload"],
        ensure_ascii=False,
        indent=6,
        sort_keys=True,
    ).splitlines():
        lines.append(f"      {raw_line}")
    lines.append("")
    lines.append("    Effective Runtime Settings:")
    for raw_line in json.dumps(
        effective_settings_payload,
        ensure_ascii=False,
        indent=6,
        sort_keys=True,
    ).splitlines():
        lines.append(f"      {raw_line}")
    lines.extend(
        [
            "",
            "  [DATABASE]",
            f"    Dialect                : {dialect}",
        ]
    )

    if is_postgres():
        lines.append(f"    Host                   : {engine.url.host or 'unknown'}")
        lines.append(f"    Database               : {engine.url.database or 'unknown'}")
        lines.append(f"    pgvector               : ready")
    elif is_sqlite():
        lines.append("    Course Vector Index   : local course-scoped store")

    lines.append("")
    lines.append("  [STORAGE]")
    lines.append(f"    Backend                : {storage_backend}")

    if uses_s3:
        lines.append(f"    S3 Bucket              : {get_env('S3_BUCKET') or '!! NOT_SET !!'}")
        lines.append(f"    S3 Endpoint            : {get_env('S3_ENDPOINT') or '!! NOT_SET !!'}")
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
    if not llm_snapshot.has_usable_completion_endpoint():
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
    _maybe_export_openapi_schema(app)

    from app.workflows.ingest import recover_stalled_enhancements
    from app.workflows.support.system import refresh_community_qr_cache

    app.state.background_task_registry.spawn(
        recover_stalled_enhancements(task_registry=app.state.background_task_registry),
        kind="ingest.recovery",
        name="ingest.recovery",
        dedupe_key="ingest.recovery",
    )
    app.state.background_task_registry.spawn(
        refresh_community_qr_cache(),
        kind="system.community_qr_warmup",
        name="system.community_qr_warmup",
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
        request.state.request_id = request_id
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
    from app.api.courses import router as courses_router
    from app.api.system import router as system_router
    from app.api.user_files import router as user_files_router

    app.include_router(health_router)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(courses_router)
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
