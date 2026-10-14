"""Exercise the release patch with kubectl's real, offline strategic merge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


@pytest.mark.parametrize("existing_handler", [None, "exec", "httpGet"])
def test_frontend_release_patch_installs_readiness_and_drain(tmp_path, existing_handler) -> None:
    kubectl = shutil.which("kubectl")
    if not kubectl:
        pytest.skip("kubectl is required for the offline deployment merge check")
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    step = next(
        step for job in workflow["jobs"].values() for step in job.get("steps", [])
        if step.get("name") == "Update Sealos frontend deployment"
    )
    shell = step["run"]
    start = shell.index('deployment_patch="$(jq -n')
    end = shell.index('\n\nkubectl', start)
    patch_shell = shell[start:end].replace("${{ steps.image.outputs.image }}", "nginx:test")
    patch_shell += '\nprintf "%s" "$deployment_patch"\n'
    env_values = {
        "frontend_container_name": "frontend", "SEALOS_IMAGE_PULL_SECRET": "fixture-secret",
        "AITEACHME_API_UPSTREAM": "http://fixture-backend:9020",
        "FRONTEND_PUBLIC_URL": "https://example.test",
        "AITEACHME_NGINX_IMPORT_CLIENT_MAX_BODY_SIZE": "260m",
        "FRONTEND_ROLLOUT_TIMEOUT_SECONDS": "300",
    }
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if os.name == "nt":
        wsl = shutil.which("wsl")
        if not wsl:
            pytest.skip("WSL with bash and jq is required on Windows")
        command = [wsl, "-e", "env", *(f"{key}={value}" for key, value in env_values.items()), "bash", "-c", patch_shell]
    else:
        if not shutil.which("bash") or not shutil.which("jq"):
            pytest.skip("bash and jq are required for the release-shell check")
        command = ["bash", "-c", patch_shell]
    generated = subprocess.run(command, env={**os.environ, **env_values}, text=True,
        capture_output=True, timeout=30, creationflags=flags, check=True)
    patch_path = tmp_path / "patch.json"
    patch_path.write_text(generated.stdout, encoding="utf-8")
    app = {"name": "frontend", "image": "nginx:old", "env": [
        {"name": "KEEP_EXISTING", "value": "unchanged"},
        {"name": "AITEACHME_API_UPSTREAM", "valueFrom": {"secretKeyRef": {"name": "old", "key": "upstream"}}},
    ]}
    if existing_handler:
        handler = {"command": ["old-readiness"]} if existing_handler == "exec" else {"path": "/old", "port": 8080}
        app["readinessProbe"] = {existing_handler: handler}
        app["lifecycle"] = {"preStop": {existing_handler: handler}}
    sidecar = {"name": "istio-proxy", "image": "mesh:unchanged"}
    fixture = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "fixture"},
        "spec": {"selector": {"matchLabels": {"app": "fixture"}}, "template": {
            "metadata": {"labels": {"app": "fixture"}}, "spec": {"containers": [sidecar, app]}}}}
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    # --local never contacts a cluster or reads production credentials.
    merged = subprocess.run([kubectl, "patch", "--local", "--type=strategic", "-f", str(fixture_path),
        "--patch-file", str(patch_path), "-o", "json"], text=True, capture_output=True,
        timeout=30, creationflags=flags, check=True)
    spec = json.loads(merged.stdout)["spec"]
    assert spec["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert spec["minReadySeconds"] >= 5
    containers = spec["template"]["spec"]["containers"]
    assert next(value for value in containers if value["name"] == "istio-proxy") == sidecar
    deployed = next(value for value in containers if value["name"] == "frontend")
    assert deployed["image"] == "nginx:test"
    probe = deployed["readinessProbe"]
    assert probe["httpGet"]["path"] == "/" and probe["httpGet"]["port"] == 80
    assert "exec" not in probe and "tcpSocket" not in probe and "grpc" not in probe
    hook = deployed["lifecycle"]["preStop"]
    assert hook == {"exec": {"command": ["/bin/sh", "-c", "sleep 8"]}}
    environment = {value["name"]: value for value in deployed["env"]}
    assert environment["KEEP_EXISTING"]["value"] == "unchanged"
    assert environment["AITEACHME_API_UPSTREAM"] == {"name": "AITEACHME_API_UPSTREAM", "value": "http://fixture-backend:9020"}
