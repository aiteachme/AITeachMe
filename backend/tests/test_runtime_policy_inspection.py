import json

from app.shared.infra.settings import Settings, merge_default_settings
from scripts import inspect_runtime_policy


def test_policy_inspection_compares_yaml_values_without_disclosing_secrets(monkeypatch, tmp_path):
    first = tmp_path / "settings.private.yaml"
    second = tmp_path / "mounted.yaml"
    first.write_text("models:\n  light: gpt-6-luna\nprivate_note: secret-sentinel\n", encoding="utf-8")
    second.write_text("# Mounted copy\nprivate_note: secret-sentinel\nmodels: {light: gpt-6-luna}\n", encoding="utf-8")
    settings = Settings.model_validate(merge_default_settings({"models": {"light": "gpt-6-luna"}}))
    monkeypatch.setattr(inspect_runtime_policy, "get_project_settings", lambda: settings)
    monkeypatch.setattr(inspect_runtime_policy, "resolve_project_settings_path", lambda: first)
    report = inspect_runtime_policy.build_runtime_policy_report()
    monkeypatch.setattr(inspect_runtime_policy, "resolve_project_settings_path", lambda: second)
    mounted = inspect_runtime_policy.build_runtime_policy_report()

    assert report["yaml_loaded"] is True
    assert report["yaml_values_sha256"] == mounted["yaml_values_sha256"]
    assert report["project_policy_sha256"] == mounted["project_policy_sha256"]
    assert "secret-sentinel" not in json.dumps(report)
    assert report["text_models"]["light"] == "gpt-6-luna"


def test_policy_inspection_distinguishes_yaml_changes_and_missing_yaml(monkeypatch, tmp_path):
    path = tmp_path / "settings.private.yaml"
    path.write_text("models: {light: gpt-6-luna}\n", encoding="utf-8")
    settings = Settings.model_validate(merge_default_settings({}))
    monkeypatch.setattr(inspect_runtime_policy, "get_project_settings", lambda: settings)
    monkeypatch.setattr(inspect_runtime_policy, "resolve_project_settings_path", lambda: path)
    report = inspect_runtime_policy.build_runtime_policy_report()
    path.write_text("models: {light: gpt-6.1-sol}\n", encoding="utf-8")
    changed = inspect_runtime_policy.build_runtime_policy_report()
    monkeypatch.setattr(inspect_runtime_policy, "resolve_project_settings_path", lambda: None)
    monkeypatch.setattr(inspect_runtime_policy, "load_project_settings_values", lambda _: {})
    missing = inspect_runtime_policy.build_runtime_policy_report()

    assert changed["yaml_values_sha256"] != report["yaml_values_sha256"]
    assert missing["yaml_loaded"] is False and missing["yaml_path"] is None
