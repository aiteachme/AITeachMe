"""System settings overview service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
import structlog
from sqlmodel import Session

from app.repositories.system_settings_repo import (
    clear_system_runtime_settings,
    get_system_runtime_settings_payload,
    upsert_system_runtime_settings_payload,
)
from app.repositories.user_settings_repo import (
    clear_user_runtime_settings,
    get_user_runtime_settings_payload,
    upsert_user_runtime_settings_payload,
)
from app.schemas.system import SettingEntry, SettingSection, SettingsOverviewData
from app.shared.infra.env_support import (
    describe_project_settings_source,
    get_env,
    resolve_writable_local_env_path,
    write_local_env_updates,
)
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.runtime import is_local_mode, resolve_app_mode
from app.shared.infra.settings import (
    PROJECT_SETTINGS_ENV_NAME,
    PROJECT_SETTINGS_SOURCE_LABEL,
    Settings,
    get_project_settings,
    get_system_settings_override_payload,
    merge_settings_values,
    reset_project_settings_cache,
    set_system_settings_override,
    upgrade_legacy_settings_payload,
)
from app.shared.infra.settings.support import get_llm_api_version, resolve_runtime_llm_provider
from app.workflows.support.system.catalog import (
    ENV_ENTRY_KEY_MAP,
    SETTINGS_CATALOG,
    SettingsCatalogEntry,
    build_settings_notes,
)

_MISSING = object()
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _OverviewContext:
    settings: Settings
    base_payload: dict[str, Any]
    settings_payload: dict[str, Any]
    system_payload: Mapping[str, Any]
    user_payload: Mapping[str, Any]
    mode: str
    settings_source: str
    llm_provider: str | None
    llm_api_version: str | None
    llm_base_url: str | None
    llm_api_key: str | None


def _has_env(name: str) -> bool:
    return bool((get_env(name) or "").strip())


def _display(value: Any) -> str:
    if value is None:
        return "未配置"
    if isinstance(value, bool):
        return "开启" if value else "关闭"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if str(item).strip()) or "空"
    if isinstance(value, dict):
        return f"{len(value)} 项"
    text = str(value)
    return text if text.strip() else "空"


def _project_by_override_keys(
    effective_payload: Mapping[str, Any],
    raw_override: Mapping[str, Any],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, raw_value in raw_override.items():
        if key not in effective_payload:
            continue
        effective_value = effective_payload[key]
        if isinstance(raw_value, Mapping) and isinstance(effective_value, Mapping):
            child = _project_by_override_keys(effective_value, raw_value)
            if child:
                projected[key] = child
            continue
        projected[key] = effective_value
    return projected


def _diff_from_base(base_payload: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return only values in ``payload`` that differ from project defaults."""

    diff: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in base_payload:
            continue
        base_value = base_payload[key]
        if isinstance(value, Mapping) and isinstance(base_value, Mapping):
            child = _diff_from_base(base_value, value)
            if child:
                diff[key] = child
            continue
        if value != base_value:
            diff[key] = value
    return diff


def _project_known_settings_keys(
    schema_payload: Mapping[str, Any],
    raw_override: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep only user setting keys still recognized by the current schema."""

    raw_override = upgrade_legacy_settings_payload(raw_override)
    projected: dict[str, Any] = {}
    for key, raw_value in raw_override.items():
        if key not in schema_payload:
            continue
        schema_value = schema_payload[key]
        if isinstance(raw_value, Mapping) and isinstance(schema_value, Mapping):
            child = _project_known_settings_keys(schema_value, raw_value)
            if child:
                projected[key] = child
            continue
        projected[key] = raw_value
    return projected


def _normalize_user_settings_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and shrink a settings override payload."""

    base_payload = get_project_settings().model_dump(mode="json")
    known_payload = _project_known_settings_keys(base_payload, raw_payload)
    candidate_payload = merge_settings_values(base_payload, known_payload)
    try:
        effective = Settings.model_validate(candidate_payload)
    except ValidationError as exc:
        raise AITeachMeError(
            detail="用户 settings 配置格式不合法，请检查字段名和字段类型。",
            error_code="INVALID_USER_SETTINGS",
            status_code=422,
            data=exc.errors(),
        ) from exc
    projected_payload = _project_by_override_keys(effective.model_dump(mode="json"), known_payload)
    return _diff_from_base(base_payload, projected_payload)


def _safe_user_settings_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize persisted settings without letting stale rows break reads."""

    try:
        return _normalize_user_settings_payload(raw_payload)
    except AITeachMeError as exc:
        logger.warning("invalid_user_settings_ignored", error=str(exc), error_code=exc.error_code)
        return {}


def _merge_system_settings(base_settings: Settings, system_payload: Mapping[str, Any]) -> Settings:
    if not system_payload:
        return base_settings
    normalized_payload = _safe_user_settings_payload(system_payload)
    merged_payload = merge_settings_values(base_settings.model_dump(mode="json"), normalized_payload)
    return Settings.model_validate(merged_payload)


def _lookup_path(payload: Mapping[str, Any], dotted_key: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, _MISSING
        current = current[part]
    return True, current


def _require_path(payload: Mapping[str, Any], dotted_key: str) -> Any:
    found, value = _lookup_path(payload, dotted_key)
    if not found:
        raise RuntimeError(f"Unknown settings catalog key: {dotted_key}")
    return value


def _lookup_attr_path(value: Any, dotted_key: str) -> tuple[bool, Any]:
    current: Any = value
    for part in dotted_key.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return False, _MISSING
            current = current[part]
            continue
        if not hasattr(current, part):
            return False, _MISSING
        current = getattr(current, part)
    return True, current


def _require_attr_path(value: Any, dotted_key: str) -> Any:
    found, resolved = _lookup_attr_path(value, dotted_key)
    if not found:
        raise RuntimeError(f"Unknown settings catalog value path: {dotted_key}")
    return resolved


def _editable_settings_entry(
    key: str,
    label: str,
    value: Any,
    default_value: Any,
    system_payload: Mapping[str, Any],
    user_payload: Mapping[str, Any],
    description: str = "",
    *,
    editable_in_local: bool = True,
    editable_in_cloud: bool = True,
    ui_group: str = "",
    ui_order: int = 0,
) -> SettingEntry:
    has_system_value, _ = _lookup_path(system_payload, key)
    has_user_value, user_value = _lookup_path(user_payload, key)
    if has_system_value:
        source = "system_settings"
    elif has_user_value:
        source = "user_settings"
    else:
        source = "settings"
    status = "configured" if has_system_value or has_user_value or value not in (None, "", [], {}) else "default"
    editable = editable_in_local if is_local_mode() else editable_in_cloud
    return SettingEntry(
        key=key,
        label=label,
        source=source,
        value=value,
        default_value=default_value,
        user_value=None if user_value is _MISSING else user_value,
        display_value=_display(value),
        status=status,
        editable=editable,
        restart_required=False,
        ui_group=ui_group,
        ui_order=ui_order,
        description=description,
    )


def _env_entry(
    key: str,
    label: str,
    env_name: str,
    description: str = "",
    *,
    secret: bool = False,
    value: Any | None = None,
    restart_required: bool = True,
    ui_group: str = "",
    ui_order: int = 0,
) -> SettingEntry:
    configured = _has_env(env_name)
    local_mode = is_local_mode()
    env_value = get_env(env_name)
    actual_value = env_value if env_value is not None and str(env_value).strip() else value
    safe_secret = bool(secret and not local_mode)
    safe_value = None if safe_secret else actual_value
    if safe_secret and configured:
        display_value = "已配置"
    elif safe_secret:
        display_value = "未配置"
    else:
        display_value = _display(safe_value)
    return SettingEntry(
        key=key,
        label=label,
        source="env",
        value=safe_value,
        display_value=display_value,
        status="configured" if configured else "missing",
        secret=safe_secret,
        editable=local_mode,
        restart_required=restart_required if local_mode else True,
        ui_group=ui_group,
        ui_order=ui_order,
        description=description,
    )


def _runtime_entry(
    key: str,
    label: str,
    value: Any,
    description: str = "",
    *,
    ui_group: str = "",
    ui_order: int = 0,
) -> SettingEntry:
    return SettingEntry(
        key=key,
        label=label,
        source="runtime",
        value=value,
        display_value=_display(value),
        status="runtime",
        derived=True,
        restart_required=False,
        ui_group=ui_group,
        ui_order=ui_order,
        description=description,
    )


def _build_catalog_entry(entry: SettingsCatalogEntry, context: _OverviewContext) -> SettingEntry:
    if entry.kind == "setting":
        return _editable_settings_entry(
            entry.key,
            entry.label,
            _require_path(context.settings_payload, entry.key),
            _require_path(context.base_payload, entry.key),
            context.system_payload,
            context.user_payload,
            entry.description,
            editable_in_local=entry.editable_in_local,
            editable_in_cloud=entry.editable_in_cloud,
            ui_group=entry.ui_group,
            ui_order=entry.ui_order,
        )

    if entry.kind == "env":
        resolved_value = _require_attr_path(context, entry.value_path) if entry.value_path else None
        return _env_entry(
            entry.key,
            entry.label,
            entry.env_name or "",
            entry.description,
            secret=entry.secret,
            value=resolved_value,
            restart_required=entry.restart_required,
            ui_group=entry.ui_group,
            ui_order=entry.ui_order,
        )

    if entry.kind == "runtime":
        if entry.value_path is None:
            raise RuntimeError(f"Runtime catalog entry requires value_path: {entry.key}")
        return _runtime_entry(
            entry.key,
            entry.label,
            _require_attr_path(context, entry.value_path),
            entry.description,
            ui_group=entry.ui_group,
            ui_order=entry.ui_order,
        )

    raise RuntimeError(f"Unsupported settings catalog entry kind: {entry.kind}")


def _build_sections(context: _OverviewContext) -> list[SettingSection]:
    return [
        SettingSection(
            id=section.id,
            label=section.label,
            description=section.description,
            entries=[_build_catalog_entry(entry, context) for entry in section.entries],
        )
        for section in SETTINGS_CATALOG
    ]


def build_settings_overview_data(
    *,
    session: Session | None = None,
    user_id: str | None = None,
) -> SettingsOverviewData:
    """Build a safe overview of env, project defaults, and runtime overrides."""

    base_settings = get_project_settings()
    raw_system_payload = (
        get_system_runtime_settings_payload(session)
        if session is not None
        else get_system_settings_override_payload()
    )
    raw_user_payload = (
        get_user_runtime_settings_payload(session, user_id)
        if session is not None and user_id and is_local_mode()
        else {}
    )
    system_payload = _safe_user_settings_payload(raw_system_payload)
    user_payload = _safe_user_settings_payload(raw_user_payload)

    if session is not None:
        if raw_system_payload != system_payload:
            if system_payload:
                upsert_system_runtime_settings_payload(session, payload=system_payload)
            else:
                clear_system_runtime_settings(session)
            set_system_settings_override(system_payload)
        if user_id and raw_user_payload != user_payload:
            if user_payload:
                upsert_user_runtime_settings_payload(session, user_id=user_id, payload=user_payload)
            else:
                clear_user_runtime_settings(session, user_id=user_id)

    if is_local_mode() and session is not None and not system_payload and user_payload:
        upsert_system_runtime_settings_payload(session, payload=user_payload)
        set_system_settings_override(user_payload)
        system_payload = user_payload

    settings = _merge_system_settings(base_settings, system_payload)
    context = _OverviewContext(
        settings=settings,
        base_payload=base_settings.model_dump(mode="json"),
        settings_payload=settings.model_dump(mode="json"),
        system_payload=system_payload,
        user_payload=user_payload,
        mode=resolve_app_mode(),
        settings_source=describe_project_settings_source(),
        llm_provider=resolve_runtime_llm_provider(),
        llm_api_version=get_llm_api_version(),
        llm_base_url=get_env("LLM_BASE_URL"),
        llm_api_key=get_env("LLM_API_KEY"),
    )

    return SettingsOverviewData(
        settings_source=context.settings_source,
        mode=context.mode,
        sections=_build_sections(context),
        notes=build_settings_notes(
            project_settings_env_name=PROJECT_SETTINGS_ENV_NAME,
            project_settings_source_label=PROJECT_SETTINGS_SOURCE_LABEL,
        ),
    )


def update_user_settings_overview_data(
    *,
    session: Session,
    user_id: str,
    settings_payload: Mapping[str, Any],
    env_payload: Mapping[str, str | None] | None = None,
    reset: bool = False,
) -> SettingsOverviewData:
    """Persist local system settings and return a fresh overview."""

    env_updates = {
        ENV_ENTRY_KEY_MAP[key]: value
        for key, value in dict(env_payload or {}).items()
        if key in ENV_ENTRY_KEY_MAP
    }
    has_settings_updates = bool(dict(settings_payload))

    if not is_local_mode() and (env_updates or has_settings_updates or reset):
        raise AITeachMeError(
            detail="云端模式下普通用户无服务端设置写权限。",
            error_code="SETTINGS_EDIT_FORBIDDEN",
            status_code=403,
        )

    if env_updates:
        write_local_env_updates(env_updates)
        reset_project_settings_cache()
        logger.info(
            "local_env_updated_via_settings",
            env_path=str(resolve_writable_local_env_path()),
            updated_keys=sorted(env_updates),
        )

    if reset:
        clear_system_runtime_settings(session)
        clear_user_runtime_settings(session, user_id=user_id)
        set_system_settings_override({})
    else:
        normalized_payload = _normalize_user_settings_payload(settings_payload)
        upsert_system_runtime_settings_payload(session, payload=normalized_payload)
        set_system_settings_override(normalized_payload)

    return build_settings_overview_data(session=session, user_id=user_id)


__all__ = [
    "build_settings_overview_data",
    "update_user_settings_overview_data",
]
