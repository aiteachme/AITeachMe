from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import main as app_main
from app.shared.infra.runtime import cloud_config, mode
from app.shared.infra.storage import config as storage_config
from app.shared.infra.settings import Settings, reset_project_settings_cache
from scripts import bootstrap_cloud_db, check_cloud_db, start_cloud_app


def _valid_cloud_env() -> dict[str, str]:
    return {
        "APP_MODE": "cloud",
        "DATABASE_URL": "postgresql+psycopg://user:pass@db.example.com:5432/aiteachme",
        "STORAGE_BACKEND": "s3",
        "S3_CREDENTIAL_MODE": "static",
        "S3_BUCKET": "course-assets",
        "S3_ENDPOINT": "https://s3.example.com",
        "S3_ACCESS_KEY": "access-key",
        "S3_SECRET_KEY": "secret-key",
        "AUTH_ENABLED": "true",
        "AUTH_TOKEN_SECRET": "x" * 32,
    }


def _patch_cloud_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    monkeypatch.setattr(
        cloud_config,
        "get_env",
        lambda name, default=None: values.get(name, default),
    )


def test_app_mode_defaults_to_local_but_rejects_invalid_explicit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mode, "get_env", lambda _name: None)
    assert mode.resolve_app_mode() == "local"

    monkeypatch.setattr(mode, "get_env", lambda _name: " CLOUD ")
    assert mode.resolve_app_mode() == "cloud"

    monkeypatch.setattr(mode, "get_env", lambda _name: "production")
    with pytest.raises(ValueError, match="APP_MODE"):
        mode.resolve_app_mode()


def test_cloud_runtime_config_accepts_complete_static_s3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cloud_env(monkeypatch, _valid_cloud_env())

    assert cloud_config.collect_cloud_runtime_config_errors() == []


def test_cloud_runtime_config_reports_settings_schema_mismatch_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings.model_validate(
            {"fallback_models": {"removed_field": "must-not-appear-in-errors"}}
        )

    def raise_validation_error():
        raise caught.value

    _patch_cloud_env(monkeypatch, _valid_cloud_env())
    monkeypatch.setattr(cloud_config, "get_project_settings", raise_validation_error)

    errors = cloud_config.collect_cloud_runtime_config_errors()

    assert any("fallback_models.removed_field" in error for error in errors)
    assert all("must-not-appear-in-errors" not in error for error in errors)


@pytest.mark.parametrize(
    ("contents", "expected_error"),
    [
        (None, "does not exist"),
        ("llm: [", "not valid YAML"),
    ],
)
def test_configured_project_settings_file_must_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contents: str | None,
    expected_error: str,
) -> None:
    settings_path = tmp_path / "settings.yaml"
    if contents is not None:
        settings_path.write_text(contents, encoding="utf-8")
    monkeypatch.setenv("PROJECT_SETTINGS_PATH", str(settings_path))
    reset_project_settings_cache()

    try:
        errors = cloud_config.collect_project_settings_config_errors()
    finally:
        monkeypatch.delenv("PROJECT_SETTINGS_PATH")
        reset_project_settings_cache()

    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize(
    ("name", "value", "expected_error"),
    [
        ("APP_MODE", "local", "APP_MODE"),
        ("DATABASE_URL", "sqlite:///local.db", "PostgreSQL"),
        ("STORAGE_BACKEND", "local", "STORAGE_BACKEND"),
        ("S3_BUCKET", "", "S3_BUCKET"),
        ("AUTH_ENABLED", "false", "AUTH_ENABLED"),
        ("AUTH_TOKEN_SECRET", "too-short", "AUTH_TOKEN_SECRET"),
    ],
)
def test_cloud_runtime_config_rejects_fail_open_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    expected_error: str,
) -> None:
    values = _valid_cloud_env()
    values[name] = value
    _patch_cloud_env(monkeypatch, values)

    assert any(
        expected_error in error
        for error in cloud_config.collect_cloud_runtime_config_errors()
    )


def test_cloud_runtime_config_accepts_dogecloud_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _valid_cloud_env()
    for name in ("S3_BUCKET", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        values.pop(name)
    values.update(
        {
            "S3_CREDENTIAL_MODE": "dogecloud_tmp_token",
            "DOGECLOUD_API_ACCESS_KEY": "doge-access-key",
            "DOGECLOUD_API_SECRET_KEY": "doge-secret-key",
            "DOGECLOUD_SPACE_NAME": "course-assets",
        }
    )
    _patch_cloud_env(monkeypatch, values)

    assert cloud_config.collect_cloud_runtime_config_errors() == []


def test_cloud_runtime_config_accepts_dogecloud_legacy_s3_credential_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _valid_cloud_env()
    values.update(
        {
            "S3_CREDENTIAL_MODE": "dogecloud_tmp_token",
            "S3_BUCKET": "course-assets",
            "DOGECLOUD_API_ACCESS_KEY": "   ",
            "DOGECLOUD_API_SECRET_KEY": "\t",
        }
    )
    values.pop("S3_ENDPOINT")
    _patch_cloud_env(monkeypatch, values)
    monkeypatch.setattr(
        storage_config,
        "get_env",
        lambda name, default=None: values.get(name, default),
    )

    assert cloud_config.collect_cloud_runtime_config_errors() == []
    assert storage_config.resolve_dogecloud_api_access_key() == "access-key"
    assert storage_config.resolve_dogecloud_api_secret_key() == "secret-key"
    assert storage_config.resolve_dogecloud_space_name() == "course-assets"


def test_cloud_entrypoint_stops_before_bootstrap_when_config_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        start_cloud_app,
        "collect_cloud_runtime_config_errors",
        lambda: ["APP_MODE must be explicitly set to cloud"],
    )
    monkeypatch.setattr(
        start_cloud_app,
        "_run_bootstrap",
        lambda **_kwargs: pytest.fail("bootstrap must not run for invalid cloud config"),
    )

    assert start_cloud_app.main([]) == 2


def test_cloud_database_bootstrap_stops_before_inspection_on_settings_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(bootstrap_cloud_db, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(
        bootstrap_cloud_db,
        "collect_project_settings_config_errors",
        lambda: ["project settings schema mismatch at fallback_models"],
    )
    monkeypatch.setattr(
        bootstrap_cloud_db,
        "_inspect_database_state",
        lambda: pytest.fail("database inspection must not run for invalid settings"),
    )

    assert bootstrap_cloud_db.main([]) == 2
    assert "stopped before database inspection" in capsys.readouterr().err


def test_cloud_database_post_migration_steps_run_in_order_in_one_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        bootstrap_cloud_db,
        "_prepare_runtime_schema",
        lambda: calls.append("prepare") or 0,
    )
    monkeypatch.setattr(
        bootstrap_cloud_db,
        "_validate_runtime_dependencies",
        lambda: calls.append("validate") or 0,
    )

    bootstrap_cloud_db._run_post_migration_steps()

    assert calls == ["prepare", "validate"]


def test_cloud_lifespan_rejects_invalid_config_before_database_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_calls: list[str] = []
    monkeypatch.setattr(app_main, "resolve_app_mode", lambda: "cloud")
    monkeypatch.setattr(
        app_main,
        "collect_cloud_runtime_config_errors",
        lambda: ["DATABASE_URL must use PostgreSQL"],
    )
    monkeypatch.setattr(
        app_main,
        "init_db",
        lambda: database_calls.append("init_db"),
    )

    async def start_lifespan() -> None:
        async with app_main.lifespan(app_main.app):
            pytest.fail("invalid cloud config must stop lifespan startup")

    with pytest.raises(RuntimeError, match="DATABASE_URL must use PostgreSQL"):
        asyncio.run(start_lifespan())
    assert database_calls == []


def test_cloud_storage_check_never_skips_non_s3_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check_cloud_db, "storage_is_s3", lambda: False)

    assert check_cloud_db._collect_storage_errors() == [
        "object storage validation requires STORAGE_BACKEND=s3"
    ]


def test_deploy_workflow_serializes_and_reconciles_current_successful_main() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")

    assert "cancel-in-progress: false" in workflow
    assert "/git/ref/heads/main" in workflow
    assert "/actions/workflows/ci.yml/runs?branch=main&event=push&status=success" in workflow
    assert '.head_sha == $latest_sha and .conclusion == "success"' in workflow
    assert 'echo "source_sha=${latest_sha}"' in workflow
    assert "WORKFLOW_RUN_EVENT: ${{ github.event.workflow_run.event }}" in workflow
    assert '[ "${WORKFLOW_RUN_EVENT}" != "push" ]' in workflow
    assert '[ "${WORKFLOW_RUN_HEAD_SHA}" = "${latest_sha}" ]' in workflow
    assert '[ "${WORKFLOW_RUN_CONCLUSION}" = "success" ]' in workflow
    assert 'echo "release_mode=normal"' in workflow
    assert 'echo "release_mode=reconcile"' in workflow
    assert "deploy_backend=true" in workflow
    assert "deploy_frontend=true" in workflow
    assert 'reason="${RELEASE_MODE:-normal}-full-release"' in workflow
    assert "needs.classify_changes.outputs.deploy_backend != 'true'" in workflow
    assert "needs.deploy-backend.outputs.enabled != 'true'" in workflow
    assert "needs.deploy-backend.outputs.deployed == 'true'" in workflow
    assert "enabled: ${{ steps.optin.outputs.enabled }}" in workflow
    assert (
        "if: steps.optin.outputs.enabled == 'true' && "
        "env.STRICT_API_SMOKE == 'true'"
    ) in workflow
    assert 'echo "deployed=true"' in workflow
    assert "cloudflare/wrangler-action@v3" in workflow
    assert "--commit-hash=${{ env.SOURCE_SHA }}" in workflow
    assert "CLOUDFLARE_DEPLOY_KEY" not in workflow


def test_sealos_backend_rollout_waits_for_fastapi_readiness() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")

    assert '"maxUnavailable": 0' in workflow
    assert '"maxSurge": 1' in workflow
    assert '"startupProbe"' in workflow
    assert '"readinessProbe"' in workflow
    assert '"path": "/api/health"' in workflow
    assert "describe pod" not in workflow
