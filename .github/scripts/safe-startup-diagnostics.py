"""Read-only, scoped release diagnostics. Never prints raw pod data or logs."""
from __future__ import annotations
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rollout", ROOT / ".github/scripts/backend-rollout-strategy.py")
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)

SAFE_ERRORS = {
    "Backup encryption requires an auth secret of at least 32 characters.",
    "DATABASE_URL cannot be converted to explicit PostgreSQL backup settings.",
    "Backup authentication or content validation failed; no usable plaintext was produced.",
    "The destructive cloud migration requires S3 artifact storage for its backup.",
    "pg_dump produced an empty backup; migration has not started.",
    "Uploaded backup readback checksum mismatch; migration has not started.",
    "Uploaded backup plaintext checksum mismatch; migration has not started.",
    "Cloud database backup storage or verification failed; migration has not started.",
}
SAFE_BOOTSTRAP_MESSAGES = {
    "Waiting for the PostgreSQL cloud bootstrap lock",
    "cloud database bootstrap lock failed; verify database connectivity and permissions.",
    "cloud database bootstrap failed before migrations: cannot connect to PostgreSQL.",
    "Reason: DATABASE_URL host cannot be resolved by DNS from this runtime.",
    "Reason: PostgreSQL rejected the configured username/password.",
    "Reason: PostgreSQL is unreachable or rejected the connection. Check network, port, firewall, and DATABASE_URL.",
    "bootstrap_cloud_db requires APP_MODE=cloud.",
    "cloud database bootstrap stopped before database inspection: project settings are invalid or incompatible with this backend build.",
    "Detected a legacy PostgreSQL schema without Alembic versioning.",
}
SAFE_EXCEPTION_TYPES = {
    "ModuleNotFoundError", "ImportError", "PermissionError", "FileNotFoundError", "TimeoutError",
    "OperationalError", "ProgrammingError", "IntegrityError", "DataError", "InterfaceError",
    "UndefinedTable", "UndefinedColumn", "DuplicateColumn", "DuplicateTable", "InsufficientPrivilege",
    "InvalidPassword", "InvalidCatalogName", "ConnectionDoesNotExist", "ConnectionFailure",
    "OutOfMemory", "DiskFull", "NoSpaceLeftOnDevice", "CommandError", "ResolutionError",
    "ValidationError", "BackupError", "TypeError", "ValueError", "RuntimeError", "AttributeError",
    "NameError", "KeyError", "IndexError", "AssertionError", "SyntaxError", "IndentationError",
    "ClientError", "EndpointConnectionError", "NoCredentialsError", "PartialCredentialsError",
    "ConnectTimeoutError", "ReadTimeoutError", "SSLError", "InvalidToken", "InvalidTag",
}
SAFE_REASONS = {
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "ContainerCreating", "PodInitializing",
    "CreateContainerConfigError", "CreateContainerError", "RunContainerError", "Error", "Completed",
    "OOMKilled", "DeadlineExceeded", "Failed", "FailedMount", "FailedScheduling", "FailedCreate",
    "BackOff", "Pulling", "Pulled", "Created", "Started", "Killing", "Unhealthy", "Scheduled",
    "ProgressDeadlineExceeded", "MinimumReplicasUnavailable", "NewReplicaSetAvailable",
}
VERSION_PROBE = r'''
import contextlib, io, json, re, subprocess
out = {}
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    for binary in ("pg_dump", "pg_restore"):
        try:
            result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
            match = re.fullmatch(r"[a-z_]+ \(PostgreSQL\) ([0-9]+(?:\.[0-9]+)*)(?: [^\r\n]*)?\s*", result.stdout)
            out[binary] = match[1] if result.returncode == 0 and match else "unavailable"
        except Exception:
            out[binary] = "unavailable"
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.pool import NullPool
        from app.shared.infra.env_support import get_env
        url = make_url(get_env("DATABASE_URL") or "")
        if url.get_backend_name() != "postgresql":
            raise ValueError()
        engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '10000'"))
            server = str(conn.execute(text("SHOW server_version_num")).scalar())
            revs = list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
        engine.dispose()
        out["server_version_num"] = server if re.fullmatch(r"[0-9]{5,7}", server) else "unavailable"
        out["revision"] = revs[0] if len(revs) == 1 and re.fullmatch(r"[a-zA-Z0-9_]{1,64}", revs[0]) else "unavailable"
    except Exception:
        out["database_probe"] = "unavailable"
print(json.dumps(out))
'''

def safe_reason(value):
    return value if value in SAFE_REASONS else "unknown"

def safe_traceback_frame(line):
    match = re.fullmatch(r'\s*File "([^"\r\n]+\.py)", line ([0-9]{1,7}), in ([a-zA-Z_][a-zA-Z0-9_]*|<module>)', line)
    if not match:
        return None
    filename = match[1].replace("\\", "/")
    relative = None
    if filename.startswith("/app/"):
        relative = "backend/" + filename[len("/app/"):]
    else:
        root_text = ROOT.as_posix().rstrip("/") + "/"
        if filename.startswith(root_text):
            relative = filename[len(root_text):]
    if not relative or not re.fullmatch(r"backend/(?:app|scripts|migrations)/[a-zA-Z0-9_./-]+\.py", relative):
        return None
    parts = Path(relative).parts
    if ".." in parts or "." in parts or not (ROOT / relative).is_file():
        return None
    return {"file": relative, "line": int(match[2]), "function": match[3]}

def parse_logs(logs):
    found, exception_types, milestones, stages = set(), set(), set(), set()
    frames = []
    for line in logs.splitlines():
        frame = safe_traceback_frame(line)
        if frame:
            frames.append(frame)
        if line in SAFE_BOOTSTRAP_MESSAGES:
            milestones.add(line)
        candidate = line
        for prefix in ("BackupError: ", "scripts.backup_cloud_database.BackupError: ", "cloud database bootstrap failed: "):
            if line.startswith(prefix):
                candidate = line[len(prefix):]
                break
        if candidate in SAFE_ERRORS:
            found.add(candidate)
        pg = re.fullmatch(r"((?:pg_dump|pg_restore) (?:failed \(exit=[0-9]+\)|could not complete); database migration has not started\.)", candidate)
        if pg:
            found.add(pg[1])
        step = re.fullmatch(r"((?:prepare_cloud_db|check_cloud_db)\.py failed \(exit=[0-9]+\))", candidate)
        if step:
            found.add(step[1])
        exc = re.match(r"^(?:[a-zA-Z_][a-zA-Z0-9_]*\.)*([A-Z][a-zA-Z0-9_]+):", line)
        if exc and exc[1] in SAFE_EXCEPTION_TYPES:
            exception_types.add(exc[1])
        for exc_name in SAFE_EXCEPTION_TYPES:
            if re.match(r"^cloud database bootstrap failed(?:(?: while inspecting database)?): \((?:[a-zA-Z_][a-zA-Z0-9_]*\.)*" + exc_name + r"\)", line):
                exception_types.add(exc_name)
        if line.startswith("cloud database bootstrap failed while inspecting database:"):
            stages.add("database_inspection_failed")
        elif line.startswith("cloud database bootstrap failed:"):
            stages.add("backup_or_migration_or_postcheck_failed")
    safe, completed, backed_up = rollout.startup_evidence(logs, "20261012_0033", backup_source="20260912_0032")
    return {"safe_errors": sorted(found), "exception_types": sorted(exception_types),
            "safe_bootstrap_messages": sorted(milestones), "failed_stages": sorted(stages),
            "bootstrap_messages": safe, "bootstrap_completed": completed, "verified_backup_seen": backed_up,
            "traceback_frames": frames[-12:]}

def probe(namespace, name, container):
    try:
        data = json.loads(rollout.kubectl(namespace, "exec", "-i", name, "-c", container, "--", "python", "-", script=VERSION_PROBE))
    except Exception:
        return {"probe": "unavailable"}
    output = {}
    known = rollout.migration_parents(rollout.MIGRATIONS)
    for key in ("pg_dump", "pg_restore"):
        if isinstance(data.get(key), str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)*|unavailable", data[key]):
            output[key] = data[key]
    server = data.get("server_version_num", "unavailable")
    output["server_version_num"] = server if isinstance(server, str) and re.fullmatch(r"[0-9]{5,7}", server) else "unavailable"
    output["revision"] = data.get("revision") if data.get("revision") in known else "unavailable"
    return output

def diagnose(namespace, deployment_name, container, expected_image):
    dep = json.loads(rollout.kubectl(namespace, "get", f"deployment/{deployment_name}", "-o", "json"))
    uid = dep["metadata"]["uid"]
    selector = rollout.label_selector(dep["spec"]["selector"])
    sets = json.loads(rollout.kubectl(namespace, "get", "replicasets", "-l", selector, "-o", "json"))["items"]
    owned_sets = {rs["metadata"]["uid"] for rs in sets if rollout.controlled_by(rs, "Deployment", {uid})}
    all_pods = json.loads(rollout.kubectl(namespace, "get", "pods", "-l", selector, "-o", "json"))["items"]
    pods = [p for p in all_pods if rollout.controlled_by(p, "ReplicaSet", owned_sets)
            and any(c.get("name") == container and c.get("image") == expected_image for c in p["spec"]["containers"])]
    report = {"owned_target_pods": len(pods), "pods": []}
    for pod in pods:
        name = pod["metadata"]["name"]
        status = pod.get("status", {})
        cs = next((x for x in status.get("containerStatuses", []) if x.get("name") == container), {})
        record = {"pod": name if re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", name) else "unknown",
                  "phase": status.get("phase") if status.get("phase") in {"Pending", "Running", "Succeeded", "Failed", "Unknown"} else "unknown",
                  "ready": bool(cs.get("ready")), "restarts": int(cs.get("restartCount", 0)),
                  "terminating": bool(pod["metadata"].get("deletionTimestamp"))}
        for state_key in ("state", "lastState"):
            safe_state = {}
            for kind, values in cs.get(state_key, {}).items():
                if kind not in {"running", "waiting", "terminated"}:
                    continue
                safe_state[kind] = {"reason": safe_reason(values.get("reason"))}
                if isinstance(values.get("exitCode"), int):
                    safe_state[kind]["exitCode"] = values["exitCode"]
            record[state_key] = safe_state
        for previous in (False, True):
            label = "previous_logs" if previous else "current_logs"
            if previous and not cs.get("restartCount", 0):
                continue
            try:
                args = ["logs", name, "-c", container, "--timestamps=false", "--tail=500"]
                if previous:
                    args.append("--previous")
                record[label] = parse_logs(rollout.kubectl(namespace, *args))
            except Exception:
                record[label] = {"unavailable": True}
        if "running" in cs.get("state", {}):
            record["versions"] = probe(namespace, name, container)
        report["pods"].append(record)
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-image", required=True)
    args = parser.parse_args()
    try:
        report = diagnose(args.namespace, args.deployment, args.container, args.expected_image)
    except Exception:
        print(json.dumps({"diagnostics": "unavailable"}))
        return 1
    print(json.dumps(report, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
