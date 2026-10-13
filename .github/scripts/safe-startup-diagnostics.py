"""Read-only, scoped release diagnostics. Never prints raw pod data or logs."""
from __future__ import annotations
import argparse
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rollout", ROOT / ".github/scripts/backend-rollout-strategy.py")
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)

def model_table_names():
    names = set()
    for path in (ROOT / "backend/app/models").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in node.targets):
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__tablename__":
                value = node.value
            else:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", value.value):
                names.add(value.value)
    return names

KNOWN_TABLES = model_table_names()

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
    "ConnectTimeoutError", "ReadTimeoutError", "SSLError", "InvalidToken", "InvalidTag", "TimeoutExpired",
}
SAFE_REASONS = {
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "ContainerCreating", "PodInitializing",
    "CreateContainerConfigError", "CreateContainerError", "RunContainerError", "Error", "Completed",
    "OOMKilled", "DeadlineExceeded", "Failed", "FailedMount", "FailedScheduling", "FailedCreate",
    "BackOff", "Pulling", "Pulled", "Created", "Started", "Killing", "Unhealthy", "Scheduled",
    "ProgressDeadlineExceeded", "MinimumReplicasUnavailable", "NewReplicaSetAvailable",
}
VERSION_PROBE = r'''
import contextlib, io, json, os, re, subprocess, sys
out = {}
safe_output = sys.stdout
def emit_progress():
    print(json.dumps(out), file=safe_output, flush=True)
def classify(exc):
    message = str(exc).lower()
    categories = {
        "too many clients": "connection_limit", "remaining connection slots": "connection_limit",
        "too many connections": "connection_limit",
        "connection refused": "connection_refused", "connection timed out": "connection_timeout",
        "timeout expired": "connection_timeout", "could not translate host name": "dns",
        "name or service not known": "dns", "password authentication failed": "authentication",
        "no pg_hba.conf entry": "pg_hba", "certificate verify failed": "tls_certificate",
        "ssl error": "tls", "database system is starting up": "database_starting",
        "database system is in recovery": "database_recovery", "permission denied": "permission",
        "does not exist": "missing_database_or_role", "no such file": "missing_file",
        "version mismatch": "client_version", "cannot be converted": "backup_settings",
        "server closed the connection": "connection_closed", "could not connect": "connection_failed",
        "unrecognized configuration parameter": "unsupported_parameter",
        "no password supplied": "missing_password", "timed out": "command_timeout",
        "lock timeout": "lock_timeout",
        "row-level security policy": "row_security",
        "statement timeout": "statement_timeout", "idle-session timeout": "session_timeout",
        "idle-in-transaction timeout": "session_timeout", "administrator command": "server_termination",
        "database system is shutting down": "server_termination", "crash of another server process": "server_crash",
        "connection reset by peer": "connection_closed", "unexpected eof": "connection_closed",
        "could not receive data from server": "connection_closed", "pqgetcopydata": "copy_read_failed",
        "invalid page": "data_corruption", "missing chunk": "data_corruption",
        "could not write": "output_write_failed", "no space left": "storage_full",
        "out of memory": "memory_exhausted", "must be loaded via shared_preload_libraries": "extension_not_loaded",
        "syntax error": "sql_syntax", "server sent data": "protocol_error",
    }
    original = getattr(exc, "orig", exc)
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return {"category": next((v for k,v in categories.items() if k in message), "unclassified"),
            "exception_type": type(exc).__name__, "driver_exception_type": type(original).__name__,
            "sqlstate": code if isinstance(code,str) and re.fullmatch(r"[0-9A-Z]{5}",code) else "unavailable"}
def dump_failure(stderr, exit_code):
    message = stderr.decode("utf-8", "replace")
    flags = {key: marker in message.lower() for key, marker in {
        "server_query_failed": "query failed", "copy_read_failed": "pqgetcopydata",
        "server_termination": "terminating connection", "server_closed": "server closed",
        "data_read_failed": "dumping the contents of table", "output_write_failed": "could not write",
        "row_security": "row-level security", "fatal_reported": "fatal:",
    }.items()}
    known_table = "unknown"
    try:
        known = __KNOWN_TABLE_NAMES__
        for match in re.finditer(r'(?:table |COPY (?:public\.)?)(?:"([^"\r\n]+)"|([a-zA-Z_][a-zA-Z0-9_]*))', message):
            candidate = match[1] or match[2]
            if candidate in known:
                known_table = candidate
                break
    except Exception:
        pass
    return {"exit_code":exit_code, **classify(RuntimeError(message)), "flags":flags, "known_table":known_table}
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    for binary in ("pg_dump", "pg_restore"):
        try:
            result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
            match = re.fullmatch(r"[a-z_]+ \(PostgreSQL\) ([0-9]+(?:\.[0-9]+)*)(?: [^\r\n]*)?\s*", result.stdout)
            out[binary] = match[1] if result.returncode == 0 and match else "unavailable"
        except Exception:
            out[binary] = "unavailable"
    emit_progress()
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.pool import NullPool
        from app.shared.infra.env_support import get_env
        url = make_url(get_env("DATABASE_URL") or "")
        out["backup_auth_sources"] = {"url_password_present":bool(url.password),
                                      "inherited_pgpassword_present":bool(os.environ.get("PGPASSWORD")),
                                      "inherited_pgpassfile_present":bool(os.environ.get("PGPASSFILE"))}
        if url.get_backend_name() != "postgresql":
            raise ValueError()
        for label,kw in (("regular_connection",{}),("bootstrap_connection",{"isolation_level":"AUTOCOMMIT"})):
            engine = create_engine(url,poolclass=NullPool,connect_args={"connect_timeout":6},**kw)
            stage, connected = "connect", False
            try:
                with engine.connect() as conn:
                    connected, stage = True, "session_limits"
                    if not kw:
                        conn.execute(text("SET TRANSACTION READ ONLY"))
                        conn.execute(text("SET LOCAL statement_timeout = '6000'"))
                    else:
                        conn.execute(text("SET default_transaction_read_only = on"))
                        conn.execute(text("SET statement_timeout = '6000'"))
                    stage = "server_version"
                    server = str(conn.execute(text("SHOW server_version_num")).scalar())
                    limit = conn.execute(text("SELECT rolconnlimit FROM pg_roles WHERE rolname = current_user")).scalar()
                    out["role_connection_limit"] = limit if isinstance(limit,int) else None
                    limits = {}
                    for setting in ("max_connections", "idle_session_timeout", "idle_in_transaction_session_timeout"):
                        value = str(conn.execute(text("SHOW " + setting)).scalar())
                        if re.fullmatch(r"[0-9]+(?:ms|s|min|h|d)?", value):
                            limits[setting] = value
                    out["server_limits"] = limits
                    started = conn.execute(text("SELECT pg_postmaster_start_time()")).scalar()
                    out["server_started_at"] = started.isoformat()
                    stage = "revision"
                    revs = list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
                out[label] = {"connected":True,"success":True}
                out["server_version_num"] = server if re.fullmatch(r"[0-9]{5,7}",server) else "unavailable"
                out["revision"] = revs[0] if len(revs)==1 and isinstance(revs[0],str) and re.fullmatch(r"[a-zA-Z0-9_]{1,64}",revs[0]) else "unavailable"
            except Exception as exc:
                out[label] = {"connected":connected,"stage":stage,**classify(exc)}
            finally:
                engine.dispose()
            emit_progress()
    except Exception as exc:
        out["database_probe"] = classify(exc)
    emit_progress()
    try:
        from scripts.backup_cloud_database import _postgres_env
        pg_env = _postgres_env()
        pg_env["PGOPTIONS"] = (pg_env.get("PGOPTIONS", "") + " -c default_transaction_read_only=on").strip()
        dumped = subprocess.run(["pg_dump","--format=custom","--schema-only","--no-password","--lock-wait-timeout=5000"],
                                env=pg_env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=20)
        out["pg_dump_schema_probe"] = {"success":True} if dumped.returncode==0 else dump_failure(dumped.stderr, dumped.returncode)
    except Exception as exc:
        out["pg_dump_schema_probe"] = classify(exc)
    emit_progress()
    if out.get("pg_dump_schema_probe", {}).get("success") is True:
        try:
            full = subprocess.run(["pg_dump","--format=custom","--no-password","--lock-wait-timeout=5000"],
                                  env=pg_env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=50)
            out["pg_dump_full_probe"] = {"success":True} if full.returncode==0 else dump_failure(full.stderr, full.returncode)
        except Exception as exc:
            out["pg_dump_full_probe"] = classify(exc)
print(json.dumps(out))
'''.replace("__KNOWN_TABLE_NAMES__", repr(KNOWN_TABLES))

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
        result = subprocess.run(
            ["kubectl", "-n", namespace, "exec", "-i", name, "-c", container, "--", "python", "-"],
            input=VERSION_PROBE, capture_output=True, text=True, timeout=150,
        )
        raw_output, completed = result.stdout, result.returncode == 0
    except subprocess.TimeoutExpired as exc:
        raw_output, completed = exc.stdout or "", False
    except Exception:
        return {"probe": "unavailable"}
    if isinstance(raw_output, bytes):
        raw_output = raw_output.decode("utf-8", "replace")
    data = {}
    for line in raw_output.splitlines():
        try:
            part = json.loads(line)
        except ValueError:
            continue
        if isinstance(part, dict):
            data.update(part)
    if not data:
        return {"probe": "unavailable"}
    output = {"probe_completed": completed}
    known = rollout.migration_parents(rollout.MIGRATIONS)
    for key in ("pg_dump", "pg_restore"):
        if isinstance(data.get(key), str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)*|unavailable", data[key]):
            output[key] = data[key]
    server = data.get("server_version_num", "unavailable")
    output["server_version_num"] = server if isinstance(server, str) and re.fullmatch(r"[0-9]{5,7}", server) else "unavailable"
    output["revision"] = data.get("revision") if data.get("revision") in known else "unavailable"
    if isinstance(data.get("role_connection_limit"),int):
        output["role_connection_limit"] = data["role_connection_limit"]
    limits = data.get("server_limits")
    if isinstance(limits, dict):
        output["server_limits"] = {key:limits[key] for key in (
            "max_connections", "idle_session_timeout", "idle_in_transaction_session_timeout")
            if isinstance(limits.get(key), str) and re.fullmatch(r"[0-9]+(?:ms|s|min|h|d)?", limits[key])}
    started = data.get("server_started_at")
    if isinstance(started, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+[+-][0-9]{2}:[0-9]{2}", started):
        output["server_started_at"] = started
    auth_sources = data.get("backup_auth_sources")
    if isinstance(auth_sources, dict):
        output["backup_auth_sources"] = {key:auth_sources.get(key) is True for key in (
            "url_password_present", "inherited_pgpassword_present", "inherited_pgpassfile_present")}
    for key in ("regular_connection", "bootstrap_connection", "database_probe", "pg_dump_schema_probe", "pg_dump_full_probe"):
        result = data.get(key)
        if not isinstance(result, dict):
            continue
        output[key] = {"success": True} if result.get("success") is True else {
            "connected": result.get("connected") is True,
            "stage": result.get("stage") if result.get("stage") in {"connect", "session_limits", "server_version", "revision"} else "unknown",
            "category": result.get("category") if result.get("category") in {
                "connection_limit", "connection_refused", "connection_timeout", "dns", "authentication",
                "pg_hba", "tls_certificate", "tls", "database_starting", "database_recovery",
                "permission", "missing_database_or_role", "missing_file", "unclassified"
                , "client_version", "backup_settings", "connection_closed", "connection_failed", "unsupported_parameter",
                "missing_password", "command_timeout", "lock_timeout"
                , "row_security", "statement_timeout", "session_timeout", "server_termination", "server_crash",
                "copy_read_failed", "data_corruption", "output_write_failed", "storage_full", "memory_exhausted",
                "extension_not_loaded", "sql_syntax", "protocol_error"
            } else "unknown",
            "exception_type": result.get("exception_type") if result.get("exception_type") in SAFE_EXCEPTION_TYPES else "unknown",
            "driver_exception_type": result.get("driver_exception_type") if result.get("driver_exception_type") in SAFE_EXCEPTION_TYPES else "unknown",
            "sqlstate": result.get("sqlstate") if isinstance(result.get("sqlstate"), str) and re.fullmatch(r"[0-9A-Z]{5}", result["sqlstate"]) else "unavailable",
        }
        if isinstance(result.get("exit_code"), int):
            output[key]["exit_code"] = result["exit_code"]
        if isinstance(result.get("flags"), dict):
            output[key]["flags"] = {flag:result["flags"].get(flag) is True for flag in (
                "server_query_failed", "copy_read_failed", "server_termination", "server_closed",
                "data_read_failed", "output_write_failed", "row_security", "fatal_reported")}
        if result.get("known_table") in KNOWN_TABLES:
            output[key]["known_table"] = result["known_table"]
    return output

def diagnose(namespace, deployment_name, container, expected_image, *, skip_dump_probe=False):
    dep = json.loads(rollout.kubectl(namespace, "get", f"deployment/{deployment_name}", "-o", "json"))
    uid = dep["metadata"]["uid"]
    selector = rollout.label_selector(dep["spec"]["selector"])
    sets = json.loads(rollout.kubectl(namespace, "get", "replicasets", "-l", selector, "-o", "json"))["items"]
    owned_sets = {rs["metadata"]["uid"] for rs in sets if rollout.controlled_by(rs, "Deployment", {uid})}
    all_pods = json.loads(rollout.kubectl(namespace, "get", "pods", "-l", selector, "-o", "json"))["items"]
    pods = [p for p in all_pods if rollout.controlled_by(p, "ReplicaSet", owned_sets)
            and any(c.get("name") == container and c.get("image") == expected_image for c in p["spec"]["containers"])]
    report = {"owned_target_pods": len(pods), "pods": []}
    if skip_dump_probe and pods:
        database_spec = importlib.util.spec_from_file_location("database_diagnostics", ROOT / ".github/scripts/safe-database-pod-diagnostics.py")
        database = importlib.util.module_from_spec(database_spec)
        database_spec.loader.exec_module(database)
        report["database"] = database.diagnose_database_pods(rollout.kubectl, namespace=namespace)
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
        if skip_dump_probe:
            report["pods"].append(record)
            continue
        deadline = time.monotonic() + 330
        while time.monotonic() < deadline:
            refreshed = json.loads(rollout.kubectl(namespace, "get", "pod", name, "-o", "json"))
            if (refreshed["metadata"]["uid"] != pod["metadata"]["uid"]
                or refreshed["metadata"].get("deletionTimestamp")
                or not rollout.controlled_by(refreshed, "ReplicaSet", owned_sets)
                or not any(c.get("name") == container and c.get("image") == expected_image for c in refreshed["spec"]["containers"])):
                break
            fresh_status = next((x for x in refreshed.get("status", {}).get("containerStatuses", []) if x.get("name") == container), {})
            if "running" in fresh_status.get("state", {}):
                result = probe(namespace, name, container)
                if result.get("probe") != "unavailable":
                    record["versions"] = result
                    if "regular_connection" in result or "database_probe" in result:
                        break
            time.sleep(2)
        report["pods"].append(record)
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--skip-dump-probe", action="store_true")
    args = parser.parse_args()
    try:
        report = diagnose(args.namespace, args.deployment, args.container, args.expected_image,
                          skip_dump_probe=args.skip_dump_probe)
    except Exception:
        print(json.dumps({"diagnostics": "unavailable"}))
        return 1
    print(json.dumps(report, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
