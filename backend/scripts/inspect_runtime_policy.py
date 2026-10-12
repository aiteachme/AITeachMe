"""Report the deployed YAML policy fingerprint without exposing credentials.

This inspects code defaults plus the selected YAML in a fresh process. Cloud
mode uses this project policy; local UI overrides belong to the server process
and are deliberately not represented by this deployment diagnostic.
"""

from __future__ import annotations

import argparse
import hashlib
import json

from app.shared.infra.env_support import resolve_project_settings_path
from app.shared.infra.settings import get_project_settings
from app.shared.infra.settings.support import load_project_settings_values


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_runtime_policy_report() -> dict[str, object]:
    path = resolve_project_settings_path()
    values = load_project_settings_values(path)
    settings = get_project_settings()
    return {
        "yaml_path": str(path) if path is not None else None,
        "yaml_loaded": path is not None,
        "yaml_values_sha256": _fingerprint(values),
        "project_policy_sha256": _fingerprint(settings.model_dump(mode="json")),
        "text_models": {slot: getattr(settings.models, slot) for slot in ("light", "primary", "reason")},
        "reasoning_efforts": settings.llm.reasoning_efforts.model_dump(mode="json"),
        "api_mode": settings.llm.api_mode,
        "text_endpoint_fallback_enabled": settings.llm.text_endpoint_fallback_enabled,
        "parser_provider": settings.ingest.parser_provider,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-actions", action="store_true")
    args = parser.parse_args()
    report = json.dumps(build_runtime_policy_report(), ensure_ascii=True, separators=(",", ":"))
    if args.github_actions:
        message = report.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title=Backend runtime policy::{message}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
