"""Choose a safe backend rollout from the live PostgreSQL migration revision.

Only crossing the custom-question schema removal needs an outage. Kubernetes'
Recreate controller waits for all old ReplicaSet pods to stop before starting
the new image and its startup migration. Inspection failures abort deployment.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import sys
import time


SCHEMA_REMOVAL_REVISION = "20261012_0033"
MIGRATIONS = Path(__file__).resolve().parents[2] / "backend/migrations/versions"
STARTING_POD_WAIT_SECONDS = 330
STARTING_POD_POLL_SECONDS = 5
REVISION_PROBE = """
import json
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from app.shared.infra.env_support import get_env

try:
    url = make_url(get_env("DATABASE_URL") or "")
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL required")
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 15})
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '15000'"))
        revisions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    engine.dispose()
    if len(revisions) != 1 or not revisions[0]:
        raise ValueError("Expected one migration revision")
    print(json.dumps({"revision": revisions[0]}))
except Exception:
    print("Unable to inspect the PostgreSQL migration revision.", file=sys.stderr)
    raise SystemExit(1)
"""


def migration_parents(directory: Path) -> dict[str, tuple[str, ...]]:
    parents = {}
    for path in directory.glob("*.py"):
        values = {}
        for statement in ast.parse(path.read_text(encoding="utf-8-sig")).body:
            if isinstance(statement, ast.Assign):
                names = [target.id for target in statement.targets if isinstance(target, ast.Name)]
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                names = [statement.target.id]
            else:
                continue
            for name in names:
                if name in {"revision", "down_revision"}:
                    values[name] = ast.literal_eval(statement.value)
        if "revision" in values:
            revision = values["revision"]
            previous = values["down_revision"]
            if revision in parents:
                raise ValueError("Duplicate migration revision")
            parents[revision] = (previous,) if isinstance(previous, str) else tuple(previous or ())
    return parents


def choose_strategy(revision: str, parents: dict[str, tuple[str, ...]]) -> dict:
    def ancestors(start: str) -> set[str]:
        found = set()
        pending = [start]
        while pending:
            item = pending.pop()
            if item not in parents:
                raise ValueError("Database revision is absent from the release migration history")
            if item not in found:
                found.add(item)
                pending.extend(parents[item])
        return found

    current_history = ancestors(revision)
    removal_history = ancestors(SCHEMA_REMOVAL_REVISION)
    if SCHEMA_REMOVAL_REVISION in current_history:
        return {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}}
    if revision in removal_history:
        # Strategic merge must explicitly remove the previous rolling config.
        return {"type": "Recreate", "rollingUpdate": None}
    raise ValueError("Database revision is on an incompatible migration branch")


def label_selector(selector: dict) -> str:
    parts = [f"{key}={value}" for key, value in sorted(selector.get("matchLabels", {}).items())]
    for item in selector.get("matchExpressions", []):
        key, operator = item["key"], item["operator"]
        if operator in {"In", "NotIn"} and item.get("values"):
            op = "in" if operator == "In" else "notin"
            parts.append(f"{key} {op} ({','.join(item['values'])})")
        elif operator in {"Exists", "DoesNotExist"}:
            parts.append(key if operator == "Exists" else f"!{key}")
        else:
            raise ValueError("Unsupported deployment label selector")
    if not parts:
        raise ValueError("Refusing an empty deployment label selector")
    return ",".join(parts)


def controlled_by(resource: dict, kind: str, uids: set[str]) -> bool:
    return any(owner.get("controller") and owner.get("kind") == kind and owner.get("uid") in uids
               for owner in resource.get("metadata", {}).get("ownerReferences", []))


def kubectl(namespace: str, *args: str, script: str | None = None, deadline: float | None = None) -> str:
    try:
        timeout = 60 if deadline is None else min(60, deadline - time.monotonic())
        if timeout <= 0:
            raise RuntimeError("Backend recovery inspection timed out")
        result = subprocess.run(
            ["kubectl", "-n", namespace, *args], input=script, text=True,
            capture_output=True, check=True, timeout=timeout,
        )
        return result.stdout
    except (subprocess.SubprocessError, OSError, ValueError):
        # Never echo raw output: deployment JSON and application logs can contain secrets.
        raise RuntimeError("Could not safely inspect the live backend") from None


def backend_pods(namespace: str, deployment_name: str, *, deadline: float | None = None) -> tuple[dict, list[dict]]:
    deployment = json.loads(kubectl(namespace, "get", f"deployment/{deployment_name}", "-o", "json", deadline=deadline))
    uid = deployment["metadata"]["uid"]
    selector = label_selector(deployment["spec"]["selector"])
    replicasets = json.loads(kubectl(namespace, "get", "replicasets", "-l", selector, "-o", "json", deadline=deadline))["items"]
    owned_sets = {rs["metadata"]["uid"] for rs in replicasets if controlled_by(rs, "Deployment", {uid})}
    pods = json.loads(kubectl(namespace, "get", "pods", "-l", selector, "-o", "json", deadline=deadline))["items"]
    return deployment, [pod for pod in pods if controlled_by(pod, "ReplicaSet", owned_sets)]


def _ready_pods(pods: list[dict], container_name: str) -> list[dict]:
    ready = [pod for pod in pods
             if not pod["metadata"].get("deletionTimestamp")
             and pod.get("status", {}).get("phase") == "Running"
             and any(c.get("type") == "Ready" and c.get("status") == "True"
                     for c in pod.get("status", {}).get("conditions", []))
             and any(c.get("name") == container_name and c.get("ready")
                     for c in pod.get("status", {}).get("containerStatuses", []))]
    return ready


def ready_backend_pods(namespace: str, deployment_name: str, container_name: str) -> tuple[dict, list[dict]]:
    deployment, pods = backend_pods(namespace, deployment_name)
    ready = _ready_pods(pods, container_name)
    if not ready:
        raise ValueError("No ready backend pod is available to verify the database revision")
    return deployment, ready


def _probe_revisions(namespace: str, pods: list[dict], container_name: str, *, deadline: float | None = None) -> str:
    revisions = set()
    parents = migration_parents(MIGRATIONS)
    for pod in pods:
        result = json.loads(kubectl(namespace, "exec", "-i", pod["metadata"]["name"], "-c", container_name,
                                    "--", "python", "-", script=REVISION_PROBE, deadline=deadline))
        revision = result.get("revision")
        if not isinstance(revision, str) or not revision:
            raise ValueError("The backend returned no database revision")
        choose_strategy(revision, parents)
        revisions.add(revision)
    if len(revisions) != 1:
        raise ValueError("Backend pods disagree on the database revision")
    return revisions.pop()


def _declared_image(deployment: dict, container_name: str) -> str:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    images = [c.get("image") for c in containers if c.get("name") == container_name]
    if len(images) != 1 or not images[0]:
        raise ValueError("Deployment has no unambiguous backend image")
    return images[0]


def _starting_pods(deployment: dict, pods: list[dict], container_name: str,
                   expected_uid: str, expected_image: str) -> list[dict]:
    if deployment["metadata"]["uid"] != expected_uid or _declared_image(deployment, container_name) != expected_image:
        raise ValueError("Deployment identity or image changed during recovery inspection")
    active = [pod for pod in pods if pod.get("status", {}).get("phase") not in {"Succeeded", "Failed"}]
    if not active:
        raise ValueError("No owned active backend pod is available for recovery inspection")
    for pod in active:
        if pod["metadata"].get("deletionTimestamp"):
            raise ValueError("Terminating backend pods cannot supply recovery evidence")
        images = [c.get("image") for c in pod.get("spec", {}).get("containers", []) if c.get("name") == container_name]
        if images != [expected_image]:
            raise ValueError("Active backend pod image differs from the Deployment")
        if pod.get("status", {}).get("phase") not in {"Pending", "Running"}:
            raise ValueError("Unknown backend pod state during recovery inspection")
    # 每个活跃副本都必须可查询，不能忽略仍在退避或使用其他配置的副本。
    if not all(pod["status"]["phase"] == "Running" and any(
        c.get("name") == container_name and "running" in c.get("state", {})
        for c in pod["status"].get("containerStatuses", [])
    ) for pod in active):
        return []
    return active


def _log_revision(logs: str, expected_revision: str) -> str | None:
    """Extract only the final validated revision marker from a failed pod log."""
    revision = r"[a-zA-Z0-9_]{1,64}"
    start = re.compile(rf"cloud database bootstrap starting \(current_revision=({revision}), "
                       rf"expected_revision=({revision}), existing_app_tables=[0-9]+, legacy_reset_allowed=(?:true|false)\)")
    migrated = re.compile(rf"cloud database migration completed \(current_revision=({revision}), expected_revision=({revision})\)")
    known = set(migration_parents(MIGRATIONS)) | {"missing"}
    observed = None
    for line in logs.splitlines():
        begin = start.fullmatch(line)
        if begin and begin[1] in known and begin[2] == expected_revision:
            observed = begin[1]
        done = migrated.fullmatch(line)
        if done and done[1] == done[2] == expected_revision:
            observed = expected_revision
    return observed


def _terminal_log_revision(namespace: str, pods: list[dict], container_name: str,
                           expected_image: str, expected_revision: str, *, deadline: float) -> str | None:
    """Use whitelisted markers when every owned pod has already terminated."""
    if not pods or any(pod.get("metadata", {}).get("deletionTimestamp")
                       or pod.get("status", {}).get("phase") not in {"Failed", "Unknown", "Running"}
                       for pod in pods):
        return None
    candidates = set()
    observed_pods = 0
    for pod in pods:
        images = [c.get("image") for c in pod.get("spec", {}).get("containers", []) if c.get("name") == container_name]
        if images != [expected_image]:
            raise ValueError("Terminal backend pod image differs from the Deployment")
        if any(c.get("name") == container_name and "running" in c.get("state", {})
               for c in pod.get("status", {}).get("containerStatuses", [])):
            return None
        logs = []
        for previous in (False, True):
            if previous and not any(c.get("name") == container_name and c.get("restartCount", 0) > 0
                                    for c in pod.get("status", {}).get("containerStatuses", [])):
                continue
            args = ["logs", pod["metadata"]["name"], "-c", container_name, "--timestamps=false"]
            if previous:
                args.append("--previous")
            try:
                logs.append(kubectl(namespace, *args, deadline=deadline))
            except RuntimeError:
                continue
        pod_candidates = {_log_revision(text, expected_revision) for text in logs}
        pod_candidates.discard(None)
        if len(pod_candidates) > 1:
            return None
        if pod_candidates:
            observed_pods += 1
            candidates.update(pod_candidates)
        elif any(logs):
            return None
    return candidates.pop() if len(candidates) == 1 and observed_pods else None


def inspect_revision(namespace: str, deployment_name: str, container_name: str,
                     *, allow_starting_pod: bool = False, recovery_evidence: dict | None = None) -> str:
    deadline = time.monotonic() + STARTING_POD_WAIT_SECONDS if allow_starting_pod else None
    deployment, pods = backend_pods(namespace, deployment_name, deadline=deadline)
    ready = _ready_pods(pods, container_name)
    if ready:
        return _probe_revisions(namespace, ready, container_name, deadline=deadline)
    if not allow_starting_pod:
        raise ValueError("No ready backend pod is available to verify the database revision")
    expected_uid = deployment["metadata"]["uid"]
    expected_image = _declared_image(deployment, container_name)
    print("Recovery preflight: waiting for owned backend containers for a read-only revision probe.", file=sys.stderr)
    while time.monotonic() < deadline:
        terminal_revision = _terminal_log_revision(namespace, pods, container_name, expected_image,
                                                   SCHEMA_REMOVAL_REVISION, deadline=deadline)
        if terminal_revision is not None:
            if choose_strategy(terminal_revision, migration_parents(MIGRATIONS))["type"] == "RollingUpdate":
                if recovery_evidence is None:
                    raise ValueError("Recovery after the destructive upgrade needs a retained backup evidence record")
                before_uids = {pod["metadata"]["uid"] for pod in pods}
                inherited = _recover_backup_evidence(namespace, pods, container_name, terminal_revision,
                                                     expected_uid, deadline=deadline)
                deployment, current = backend_pods(namespace, deployment_name, deadline=deadline)
                if deployment["metadata"]["uid"] != expected_uid or _declared_image(deployment, container_name) != expected_image \
                        or {pod["metadata"]["uid"] for pod in current} != before_uids \
                        or any(pod.get("metadata", {}).get("deletionTimestamp") for pod in current):
                    raise ValueError("Backend pods changed while retaining recovery backup evidence")
                recovery_evidence.update(inherited)
            return terminal_revision
        starting = _starting_pods(deployment, pods, container_name, expected_uid, expected_image)
        if starting:
            try:
                revision = _probe_revisions(namespace, starting, container_name, deadline=deadline)
            except RuntimeError:
                # 容器可能在 exec 前再次退出；重新核验归属和镜像后有限重试。
                pass
            else:
                deployment, pods = backend_pods(namespace, deployment_name, deadline=deadline)
                current = _starting_pods(deployment, pods, container_name, expected_uid, expected_image)
                if {p["metadata"]["uid"] for p in current} == {p["metadata"]["uid"] for p in starting}:
                    if choose_strategy(revision, migration_parents(MIGRATIONS))["type"] == "RollingUpdate":
                        if recovery_evidence is None:
                            raise ValueError("Recovery after the destructive upgrade needs a retained backup evidence record")
                        inherited = _recover_backup_evidence(namespace, current, container_name, revision,
                                                             expected_uid, deadline=deadline)
                        deployment, pods = backend_pods(namespace, deployment_name, deadline=deadline)
                        stable = _starting_pods(deployment, pods, container_name, expected_uid, expected_image)
                        if {p["metadata"]["uid"] for p in stable} != {p["metadata"]["uid"] for p in current}:
                            raise ValueError("Backend pods changed while retaining recovery backup evidence")
                        recovery_evidence.update(inherited)
                    return revision
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(STARTING_POD_POLL_SECONDS, remaining))
        if time.monotonic() >= deadline:
            break
        deployment, pods = backend_pods(namespace, deployment_name, deadline=deadline)
    raise ValueError("Timed out waiting for a verified backend recovery revision")


def startup_evidence(logs: str, expected_revision: str, *, backup_source: str | None = None) -> tuple[list[str], bool, bool]:
    """Whitelist complete bootstrap messages; never return arbitrary log text."""
    revision = r"[a-zA-Z0-9_]{1,64}"
    start = re.compile(rf"cloud database bootstrap starting \(current_revision=({revision}), "
                       rf"expected_revision=({revision}), existing_app_tables=[0-9]+, legacy_reset_allowed=(?:true|false)\)")
    backup = re.compile(r"Verified encrypted cloud database backup: "
                        rf"backups/postgres/{SCHEMA_REMOVAL_REVISION}/[0-9]{{8}}T[0-9]{{6}}Z-[0-9a-f]{{32}}\.atmbak")
    migrated = re.compile(rf"cloud database migration completed \(current_revision=({revision}), expected_revision=({revision})\)")
    completed = re.compile(r"cloud database bootstrap completed \(reset_db=(?:true|false), ALLOW_CLOUD_DB_RESET=(?:true|false)\)")
    known_revisions = set(migration_parents(MIGRATIONS)) | {"missing"}
    safe, started, backup_expected, has_backup, has_migration, finished = [], False, False, False, False, False
    for line in logs.splitlines():
        begin = start.fullmatch(line)
        if begin:
            started = (begin[1] in known_revisions and begin[1] in {backup_source, expected_revision}
                       and begin[2] == expected_revision)
            safe = [line] if started else []
            backup_expected = started and begin[1] == backup_source
            has_backup = has_migration = finished = False
        elif started and backup_expected and not has_migration and backup.fullmatch(line):
            safe.append(line)
            has_backup = True
        elif started and (done := migrated.fullmatch(line)):
            if done[1] == done[2] == expected_revision:
                safe.append(line)
                has_migration = True
        elif started and has_migration and completed.fullmatch(line):
            safe.append(line)
            finished = True
    return safe, finished, has_backup


def _recover_backup_evidence(namespace: str, pods: list[dict], container_name: str,
                             revision: str, deployment_uid: str, *, deadline: float) -> dict:
    """Retain the verified pre-removal backup before replacing unhealthy pods."""
    sources = migration_parents(MIGRATIONS)[SCHEMA_REMOVAL_REVISION]
    if len(sources) != 1:
        raise ValueError("The destructive migration needs one known source revision")
    backup_source = sources[0]
    migrated = f"cloud database migration completed (current_revision={revision}, expected_revision={revision})"
    keys = set()
    for pod in pods:
        statuses = pod.get("status", {}).get("containerStatuses", [])
        restarted = any(c.get("name") == container_name and c.get("restartCount", 0) > 0 for c in statuses)
        for previous in ([False, True] if restarted else [False]):
            args = ["logs", pod["metadata"]["name"], "-c", container_name, "--timestamps=false"]
            if previous:
                args.append("--previous")
            try:
                logs = kubectl(namespace, *args, deadline=deadline)
            except RuntimeError:
                continue
            safe, _completed, backed_up = startup_evidence(logs, revision, backup_source=backup_source)
            # 旧实例允许在迁移之后启动失败；新实例仍需通过完整启动验收。
            if backed_up and migrated in safe:
                keys.update(line.removeprefix("Verified encrypted cloud database backup: ")
                            for line in safe if line.startswith("Verified encrypted cloud database backup: "))
    if not keys:
        raise ValueError("Recovery stopped: no verified pre-removal backup evidence was retained")
    return {"deployment_uid": deployment_uid, "source_revision": backup_source,
            "target_revision": revision, "preflight_revision": revision, "verified_backup_keys": sorted(keys)}


def _validate_recovery_evidence(evidence: dict, deployment: dict, source_revision: str) -> dict:
    sources = migration_parents(MIGRATIONS)[SCHEMA_REMOVAL_REVISION]
    if (set(evidence) != {"deployment_uid", "source_revision", "target_revision", "preflight_revision", "verified_backup_keys"}
            or len(sources) != 1 or evidence["source_revision"] != sources[0]
            or evidence["target_revision"] != evidence["preflight_revision"] or evidence["preflight_revision"] != source_revision
            or evidence["deployment_uid"] != deployment["metadata"]["uid"]):
        raise ValueError("Inherited backup evidence does not match this recovery release")
    keys = evidence["verified_backup_keys"]
    pattern = rf"backups/postgres/{SCHEMA_REMOVAL_REVISION}/[0-9]{{8}}T[0-9]{{6}}Z-[0-9a-f]{{32}}\.atmbak"
    if not isinstance(keys, list) or not keys or any(not isinstance(key, str) or not re.fullmatch(pattern, key) for key in keys):
        raise ValueError("Inherited backup evidence contains no valid backup keys")
    return {"source_revision": evidence["source_revision"], "target_revision": evidence["target_revision"],
            "verified_backup_keys": sorted(set(keys))}


def verify_startup(namespace: str, deployment_name: str, container_name: str,
                   expected_image: str, *, require_backup: bool, source_revision: str = "",
                   recovery_evidence: dict | None = None) -> dict:
    parents = migration_parents(MIGRATIONS)
    heads = set(parents) - {parent for ancestors in parents.values() for parent in ancestors}
    if len(heads) != 1:
        raise ValueError("Release must have a single migration head")
    expected_revision = heads.pop()
    if require_backup != (choose_strategy(source_revision, parents)["type"] == "Recreate"):
        raise ValueError("Backup evidence policy disagrees with the verified pre-upgrade revision")
    deployment, pods = ready_backend_pods(namespace, deployment_name, container_name)
    inherited = None
    if recovery_evidence:
        if require_backup:
            raise ValueError("Inherited evidence cannot replace a required new migration backup")
        inherited = _validate_recovery_evidence(recovery_evidence, deployment, source_revision)
    if len(pods) != deployment["spec"].get("replicas", 1):
        raise ValueError("Not every expected backend replica is ready")
    lines, has_backup = [], False
    for pod in pods:
        images = {c["name"]: c["image"] for c in pod["spec"]["containers"]}
        if not expected_image or images.get(container_name) != expected_image:
            raise ValueError("Ready backend pod is not running the release image")
        name = pod["metadata"]["name"]
        safe, completed, backed_up = startup_evidence(
            kubectl(namespace, "logs", name, "-c", container_name, "--timestamps=false"), expected_revision,
            backup_source=source_revision,
        )
        if not completed:
            raise ValueError("Missing successful migration and bootstrap evidence")
        lines.extend(safe)
        has_backup |= backed_up
    # A container may have migrated successfully and then restarted. Its previous
    # log can prove the backup, but current-container startup still must pass above.
    if require_backup and not has_backup:
        for pod in pods:
            statuses = pod.get("status", {}).get("containerStatuses", [])
            if not any(c.get("name") == container_name and c.get("restartCount", 0) > 0 for c in statuses):
                continue
            try:
                previous = kubectl(namespace, "logs", pod["metadata"]["name"], "-c", container_name,
                                   "--previous", "--timestamps=false")
            except RuntimeError:
                continue
            safe, completed, backed_up = startup_evidence(previous, expected_revision, backup_source=source_revision)
            if completed and backed_up:
                lines.extend(safe)
                has_backup = True
    if require_backup and not has_backup:
        raise ValueError("Missing verified encrypted backup evidence for the destructive upgrade")
    safe_lines = list(dict.fromkeys(lines))
    result = {
        "source_revision": source_revision,
        "target_revision": expected_revision,
        "crosses_custom_type_removal": require_backup,
        "verified_backup_keys": [line.removeprefix("Verified encrypted cloud database backup: ")
                                 for line in safe_lines if line.startswith("Verified encrypted cloud database backup: ")],
        "ready_pod_count": len(pods),
        "lines": safe_lines,
    }
    if inherited:
        result["inherited_backup_evidence"] = inherited
        result["lines"].append(
            f"Inherited verified backup evidence from {inherited['source_revision']} to {inherited['target_revision']}: "
            + ", ".join(inherited["verified_backup_keys"])
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--verify-startup", action="store_true")
    parser.add_argument("--require-backup", action="store_true")
    parser.add_argument("--expected-image", default="")
    parser.add_argument("--source-revision", default="")
    parser.add_argument("--revision-output", type=Path)
    parser.add_argument("--allow-starting-pod", action="store_true",
                        help="Allow a bounded read-only revision probe during backend crash recovery.")
    parser.add_argument("--recovery-evidence-output", type=Path)
    parser.add_argument("--recovery-evidence-input", type=Path)
    args = parser.parse_args()
    if args.verify_startup:
        try:
            recovered = json.loads(args.recovery_evidence_input.read_text(encoding="utf-8")) if args.recovery_evidence_input else None
            if recovered is not None and not isinstance(recovered, dict):
                raise ValueError("Invalid recovery evidence record")
            evidence = verify_startup(args.namespace, args.deployment, args.container,
                                      args.expected_image, require_backup=args.require_backup, source_revision=args.source_revision,
                                      recovery_evidence=recovered)
        except Exception:
            print("Backend startup evidence is missing or could not be verified. "
                  "Release smoke checks stopped; running instances were not modified.")
            return 1
        print("Verified backend startup evidence (only validated bootstrap messages):\n")
        for line in evidence.pop("lines"):
            print(f"- {line}")
        # stderr remains visible to the Actions command processor while stdout
        # is appended to the step summary. All fields came from the whitelist.
        print("::notice title=Backend migration verification::" + json.dumps(evidence, separators=(",", ":")), file=sys.stderr)
        return 0
    try:
        recovery_evidence = {}
        revision = inspect_revision(args.namespace, args.deployment, args.container,
                                    allow_starting_pod=args.allow_starting_pod, recovery_evidence=recovery_evidence)
        strategy = choose_strategy(revision, migration_parents(MIGRATIONS))
        if recovery_evidence and not args.recovery_evidence_output:
            raise ValueError("Recovery requires an output file to preserve verified backup evidence")
        if args.recovery_evidence_output:
            args.recovery_evidence_output.write_text(json.dumps(recovery_evidence), encoding="utf-8")
        if args.revision_output:
            args.revision_output.write_text(revision, encoding="utf-8")
    except Exception:
        print("Backend rollout stopped: unable to establish a compatible database revision. "
              "Inspect deployment health and Alembic version before retrying.", file=sys.stderr)
        return 1
    print(f"Verified database revision: {revision}; rollout: {strategy['type']}", file=sys.stderr)
    print(json.dumps(strategy, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
