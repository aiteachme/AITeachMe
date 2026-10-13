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


SCHEMA_REMOVAL_REVISION = "20261012_0033"
MIGRATIONS = Path(__file__).resolve().parents[2] / "backend/migrations/versions"
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


def kubectl(namespace: str, *args: str, script: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["kubectl", "-n", namespace, *args], input=script, text=True,
            capture_output=True, check=True, timeout=60,
        )
        return result.stdout
    except (subprocess.SubprocessError, OSError, ValueError):
        # Never echo raw output: deployment JSON and application logs can contain secrets.
        raise RuntimeError("Could not safely inspect the live backend") from None


def ready_backend_pods(namespace: str, deployment_name: str, container_name: str) -> tuple[dict, list[dict]]:
    deployment = json.loads(kubectl(namespace, "get", f"deployment/{deployment_name}", "-o", "json"))
    uid = deployment["metadata"]["uid"]
    selector = label_selector(deployment["spec"]["selector"])
    replicasets = json.loads(kubectl(namespace, "get", "replicasets", "-l", selector, "-o", "json"))["items"]
    owned_sets = {rs["metadata"]["uid"] for rs in replicasets if controlled_by(rs, "Deployment", {uid})}
    pods = json.loads(kubectl(namespace, "get", "pods", "-l", selector, "-o", "json"))["items"]
    ready = [pod for pod in pods
             if controlled_by(pod, "ReplicaSet", owned_sets)
             and not pod["metadata"].get("deletionTimestamp")
             and pod.get("status", {}).get("phase") == "Running"
             and any(c.get("type") == "Ready" and c.get("status") == "True"
                     for c in pod.get("status", {}).get("conditions", []))
             and any(c.get("name") == container_name and c.get("ready")
                     for c in pod.get("status", {}).get("containerStatuses", []))]
    if not ready:
        raise ValueError("No ready backend pod is available to verify the database revision")
    return deployment, ready


def inspect_revision(namespace: str, deployment_name: str, container_name: str) -> str:
    _deployment, ready = ready_backend_pods(namespace, deployment_name, container_name)
    revisions = set()
    for pod in ready:
        result = json.loads(kubectl(namespace, "exec", "-i", pod["metadata"]["name"], "-c", container_name,
                                    "--", "python", "-", script=REVISION_PROBE))
        revision = result.get("revision")
        if not isinstance(revision, str) or not revision:
            raise ValueError("The backend returned no database revision")
        revisions.add(revision)
    if len(revisions) != 1:
        raise ValueError("Ready backend pods disagree on the database revision")
    return revisions.pop()


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


def verify_startup(namespace: str, deployment_name: str, container_name: str,
                   expected_image: str, *, require_backup: bool, source_revision: str = "") -> dict:
    parents = migration_parents(MIGRATIONS)
    heads = set(parents) - {parent for ancestors in parents.values() for parent in ancestors}
    if len(heads) != 1:
        raise ValueError("Release must have a single migration head")
    expected_revision = heads.pop()
    if require_backup != (choose_strategy(source_revision, parents)["type"] == "Recreate"):
        raise ValueError("Backup evidence policy disagrees with the verified pre-upgrade revision")
    deployment, pods = ready_backend_pods(namespace, deployment_name, container_name)
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
    return {
        "source_revision": source_revision,
        "target_revision": expected_revision,
        "crosses_custom_type_removal": require_backup,
        "verified_backup_keys": [line.removeprefix("Verified encrypted cloud database backup: ")
                                 for line in safe_lines if line.startswith("Verified encrypted cloud database backup: ")],
        "ready_pod_count": len(pods),
        "lines": safe_lines,
    }


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
    args = parser.parse_args()
    if args.verify_startup:
        try:
            evidence = verify_startup(args.namespace, args.deployment, args.container,
                                      args.expected_image, require_backup=args.require_backup, source_revision=args.source_revision)
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
        revision = inspect_revision(args.namespace, args.deployment, args.container)
        strategy = choose_strategy(revision, migration_parents(MIGRATIONS))
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
