"""The destructive 0033 upgrade must never overlap an old backend pod."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/backend-rollout-strategy.py"
spec = importlib.util.spec_from_file_location("backend_rollout_strategy", SCRIPT)
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)
PARENTS = {
    "0031": (), "0032": ("0031",),
    rollout.SCHEMA_REMOVAL_REVISION: ("0032",),
    "0034": (rollout.SCHEMA_REMOVAL_REVISION,),
    "other_branch": ("0031",),
}


@pytest.mark.parametrize("revision", ["0031", "0032"])
def test_pre_removal_revision_requires_recreate_and_clears_old_strategy(revision):
    assert rollout.choose_strategy(revision, PARENTS) == {"type": "Recreate", "rollingUpdate": None}


@pytest.mark.parametrize("revision", [rollout.SCHEMA_REMOVAL_REVISION, "0034"])
def test_post_removal_revision_keeps_zero_unavailable_rolling_update(revision):
    assert rollout.choose_strategy(revision, PARENTS) == {
        "type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
    }


@pytest.mark.parametrize("revision", ["", "unknown", "other_branch"])
def test_missing_unknown_and_divergent_revisions_abort(revision):
    with pytest.raises(ValueError):
        rollout.choose_strategy(revision, PARENTS)


def test_release_migration_graph_recognizes_actual_upgrade_boundary():
    parents = rollout.migration_parents(rollout.MIGRATIONS)
    assert rollout.choose_strategy("20260912_0032", parents)["type"] == "Recreate"
    assert rollout.choose_strategy("20261012_0033", parents)["type"] == "RollingUpdate"


def test_label_selector_includes_expressions_and_rejects_empty():
    assert rollout.label_selector({
        "matchLabels": {"app": "backend"},
        "matchExpressions": [
            {"key": "tier", "operator": "In", "values": ["api", "worker"]},
            {"key": "excluded", "operator": "DoesNotExist"},
        ],
    }) == "app=backend,tier in (api,worker),!excluded"
    with pytest.raises(ValueError):
        rollout.label_selector({})


def pod(name, *, owner="backend-rs", ready=True, deleting=False, image="registry.example/backend:release", running=True, phase="Running"):
    return {
        "metadata": {"name": name, "uid": f"uid-{name}", "deletionTimestamp": "now" if deleting else None,
                     "ownerReferences": [{"kind": "ReplicaSet", "uid": owner, "controller": True}]},
        "spec": {"containers": [{"name": "backend", "image": image}]},
        "status": {"phase": phase, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                   "containerStatuses": [{"name": "backend", "ready": ready,
                                          "state": {"running": {}} if running else {"waiting": {"reason": "CrashLoopBackOff"}}}]},
    }


def fake_kubectl(monkeypatch, pods, *, revisions=None, fail_probe=False,
                 deployment_image="registry.example/backend:release", rs_owner="deployment-uid",
                 logs=None, previous_logs=None):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[:3] == ["kubectl", "-n", "test-namespace"]
        if args[3:5] == ["get", "deployment/backend"]:
            image = deployment_image() if callable(deployment_image) else deployment_image
            output = {"metadata": {"uid": "deployment-uid"}, "spec": {
                "selector": {"matchLabels": {"app": "backend"}},
                "template": {"spec": {"containers": [{"name": "backend", "image": image}]}}
            }}
        elif args[3:5] == ["get", "replicasets"]:
            assert args[5:7] == ["-l", "app=backend"]
            output = {"items": [{"metadata": {
                "uid": "backend-rs",
                "ownerReferences": [{"kind": "Deployment", "uid": rs_owner, "controller": True}],
            }}]}
        elif args[3:5] == ["get", "pods"]:
            assert args[5:7] == ["-l", "app=backend"]
            output = {"items": pods() if callable(pods) else pods}
        elif args[3] == "logs":
            content = (previous_logs if "--previous" in args else logs) or {}
            return subprocess.CompletedProcess(args, 0, stdout=content.get(args[4], ""), stderr="")
        else:
            assert args[3:5] == ["exec", "-i"]
            assert args[6:] == ["-c", "backend", "--", "python", "-"]
            assert "SET TRANSACTION READ ONLY" in kwargs["input"]
            assert "SELECT version_num FROM alembic_version" in kwargs["input"]
            if fail_probe:
                raise subprocess.CalledProcessError(1, args, output="secret-database-url", stderr="secret-password")
            output = {"revision": (revisions or {}).get(args[5], "20260912_0032")}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(output), stderr="")

    monkeypatch.setattr(rollout.subprocess, "run", run)
    return calls


def test_only_ready_owned_pods_are_probed_even_with_nonready_or_foreign_matches(monkeypatch):
    calls = fake_kubectl(monkeypatch, [
        pod("backend-1"), pod("backend-2"), pod("not-ready", ready=False),
        pod("terminating", deleting=True), pod("foreign", owner="foreign-rs"),
    ])
    assert rollout.inspect_revision("test-namespace", "backend", "backend") == "20260912_0032"
    assert [args[5] for args, _ in calls if args[3] == "exec"] == ["backend-1", "backend-2"]


def test_no_ready_pod_aborts_instead_of_defaulting_to_rolling(monkeypatch):
    fake_kubectl(monkeypatch, [pod("not-ready", ready=False)])
    with pytest.raises(ValueError, match="No ready backend pod"):
        rollout.inspect_revision("test-namespace", "backend", "backend")


def test_disagreement_between_pods_aborts(monkeypatch):
    fake_kubectl(monkeypatch, [pod("one"), pod("two")], revisions={"two": "20261012_0033"})
    with pytest.raises(ValueError, match="disagree"):
        rollout.inspect_revision("test-namespace", "backend", "backend")


def test_probe_failure_never_echoes_credentials(monkeypatch, capsys):
    fake_kubectl(monkeypatch, [pod("one")], fail_probe=True)
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--namespace", "test-namespace",
                                    "--deployment", "backend", "--container", "backend"])
    assert rollout.main() == 1
    output = capsys.readouterr()
    assert not output.out
    assert "rollout stopped" in output.err
    assert "secret" not in output.err


def test_workflow_selects_strategy_before_mutating_backend():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    backend = workflow.split("  deploy-backend:", 1)[1]
    assert backend.index("backend-rollout-strategy.py") < backend.index('"strategy": ${backend_rollout_strategy}')
    assert backend.index('"strategy": ${backend_rollout_strategy}') < backend.index('"deployment/${SEALOS_BACKEND_DEPLOYMENT}" \\\n            --type=strategic')


BACKUP_KEY = "backups/postgres/20261012_0033/20261013T150000Z-" + "a" * 32 + ".atmbak"
IMAGE = "registry.example/backend:release"


def bootstrap_logs(*, source="20260912_0032", backup=True, complete=True):
    lines = [
        "do-not-publish-secret-connection-string",
        f"cloud database bootstrap starting (current_revision={source}, expected_revision=20261012_0033, existing_app_tables=50, legacy_reset_allowed=false)",
    ]
    if backup:
        lines.append(f"Verified encrypted cloud database backup: {BACKUP_KEY}")
    if complete:
        lines.extend([
            "cloud database migration completed (current_revision=20261012_0033, expected_revision=20261012_0033)",
            "cloud database bootstrap completed (reset_db=false, ALLOW_CLOUD_DB_RESET=false)",
        ])
    return "\n".join(lines)


def test_startup_evidence_only_emits_strict_safe_lines():
    logs = bootstrap_logs() + "\nVerified encrypted cloud database backup: https://secret-url"
    safe, completed, backed_up = rollout.startup_evidence(logs, "20261012_0033", backup_source="20260912_0032")
    assert len(safe) == 4 and completed and backed_up
    assert "secret" not in "\n".join(safe)
    assert BACKUP_KEY in "\n".join(safe)


@pytest.mark.parametrize("reset_requested", ["true", "false"])
def test_versioned_database_startup_accepts_configured_legacy_reset_permission(reset_requested):
    logs = bootstrap_logs().replace("legacy_reset_allowed=false", "legacy_reset_allowed=true")
    logs = logs.replace("ALLOW_CLOUD_DB_RESET=false", "ALLOW_CLOUD_DB_RESET=true")
    logs = logs.replace("reset_db=false", f"reset_db={reset_requested}")
    safe, completed, backed_up = rollout.startup_evidence(logs, "20261012_0033", backup_source="20260912_0032")
    assert len(safe) == 4 and completed and backed_up
    assert "ALLOW_CLOUD_DB_RESET=true" in safe[-1]


@pytest.mark.parametrize("change", ["bad-key", "wrong-source", "wrong-head", "unfinished"])
def test_startup_evidence_rejects_unproven_upgrade(change):
    logs = bootstrap_logs()
    if change == "bad-key":
        logs = logs.replace(BACKUP_KEY, "backups/postgres/20261012_0033/unknown-key")
    elif change == "wrong-source":
        logs = logs.replace("current_revision=20260912_0032", "current_revision=20260907_0031")
    elif change == "wrong-head":
        logs = logs.replace("20261012_0033", "20260912_0032")
    else:
        logs = bootstrap_logs(complete=False)
    _safe, complete, backed_up = rollout.startup_evidence(logs, "20261012_0033", backup_source="20260912_0032")
    assert not (complete and backed_up)


def setup_startup(monkeypatch, logs, *, previous=None, images=None):
    pods = [pod(name) for name in logs]
    for item in pods:
        name = item["metadata"]["name"]
        item["spec"] = {"containers": [{"name": "backend", "image": (images or {}).get(name, IMAGE)}]}
        item["status"]["containerStatuses"][0]["restartCount"] = int(name in (previous or {}))
    monkeypatch.setattr(rollout, "ready_backend_pods", lambda *_args: ({"metadata": {"uid": "deployment-uid"}, "spec": {"replicas": len(pods)}}, pods))
    calls = []

    def kubectl(namespace, *args, **kwargs):
        calls.append(args)
        assert namespace == "test-namespace" and args[0] == "logs"
        assert args[2:4] == ("-c", "backend")
        return (previous if "--previous" in args else logs)[args[1]]

    monkeypatch.setattr(rollout, "kubectl", kubectl)
    return calls


def verify(*, require_backup=True):
    return rollout.verify_startup("test-namespace", "backend", "backend", IMAGE,
                                  require_backup=require_backup,
                                  source_revision="20260912_0032" if require_backup else "20261012_0033")


def test_all_replicas_must_boot_but_only_one_needs_to_create_backup(monkeypatch):
    setup_startup(monkeypatch, {"one": bootstrap_logs(), "two": bootstrap_logs(source="20261012_0033", backup=False)})
    evidence = verify()
    assert evidence["verified_backup_keys"] == [BACKUP_KEY]
    assert evidence["ready_pod_count"] == 2


def test_replica_with_unexpected_preupgrade_revision_cannot_supply_evidence(monkeypatch):
    setup_startup(monkeypatch, {"one": bootstrap_logs(), "two": bootstrap_logs(source="20260907_0031")})
    with pytest.raises(ValueError, match="Missing successful migration"):
        verify()


def test_ordinary_release_does_not_require_another_backup(monkeypatch):
    setup_startup(monkeypatch, {"one": bootstrap_logs(source="20261012_0033", backup=False)})
    assert verify(require_backup=False)["verified_backup_keys"] == []
    with pytest.raises(ValueError, match="Missing verified encrypted backup"):
        verify()


def test_wrong_release_image_cannot_supply_startup_evidence(monkeypatch):
    calls = setup_startup(monkeypatch, {"one": bootstrap_logs()}, images={"one": "old-image"})
    with pytest.raises(ValueError, match="release image"):
        verify()
    assert not calls


def test_restart_can_use_previous_verified_backup_after_current_boot_succeeds(monkeypatch):
    setup_startup(monkeypatch, {"one": bootstrap_logs(source="20261012_0033", backup=False)},
                  previous={"one": bootstrap_logs()})
    assert verify()["verified_backup_keys"] == [BACKUP_KEY]


def test_previous_success_cannot_mask_incomplete_current_startup(monkeypatch):
    setup_startup(monkeypatch, {"one": bootstrap_logs(complete=False)}, previous={"one": bootstrap_logs()})
    with pytest.raises(ValueError, match="Missing successful migration"):
        verify()


def test_startup_cli_failure_is_safe_and_never_mutates_instances(monkeypatch, capsys):
    def failure(*_args, **_kwargs):
        raise RuntimeError("secret-raw-kubectl-log")

    monkeypatch.setattr(rollout, "verify_startup", failure)
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--namespace", "test-namespace", "--deployment", "backend",
                                    "--container", "backend", "--verify-startup", "--expected-image", IMAGE])
    assert rollout.main() == 1
    output = capsys.readouterr()
    assert "evidence is missing" in output.out
    assert "instances were not modified" in output.out
    assert "secret" not in output.out + output.err


def test_successful_preflight_persists_only_validated_source_revision(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rollout, "inspect_revision", lambda *_args, **_kwargs: "20260912_0032")
    output = tmp_path / "revision"
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--namespace", "test-namespace", "--deployment", "backend",
                                    "--container", "backend", "--revision-output", str(output)])
    assert rollout.main() == 0
    assert output.read_text() == "20260912_0032"
    assert json.loads(capsys.readouterr().out)["type"] == "Recreate"


def test_startup_notice_contains_only_validated_evidence(monkeypatch, capsys):
    setup_startup(monkeypatch, {"one": bootstrap_logs()})
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--namespace", "test-namespace", "--deployment", "backend",
                                    "--container", "backend", "--verify-startup", "--expected-image", IMAGE,
                                    "--require-backup", "--source-revision", "20260912_0032"])
    assert rollout.main() == 0
    output = capsys.readouterr()
    prefix = "::notice title=Backend migration verification::"
    assert output.err.startswith(prefix)
    assert json.loads(output.err.removeprefix(prefix)) == {
        "source_revision": "20260912_0032", "target_revision": "20261012_0033",
        "crosses_custom_type_removal": True, "verified_backup_keys": [BACKUP_KEY], "ready_pod_count": 1,
    }
    assert "secret" not in output.out + output.err


def test_startup_evidence_precedes_smoke_and_raw_backend_logs_are_not_published():
    backend = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8").split("  deploy-backend:", 1)[1]
    assert backend.index("Verify backend bootstrap evidence") < backend.index("Smoke test backend in cluster")
    assert '--source-revision "$(cat' in backend
    assert '"${backup_args[@]}" >> "$GITHUB_STEP_SUMMARY"' in backend
    assert 'logs "' not in backend


def fake_clock(monkeypatch, on_sleep=None):
    clock = SimpleNamespace(now=0, waits=[])

    def sleep(seconds):
        clock.now += seconds
        clock.waits.append(seconds)
        if on_sleep:
            on_sleep()

    monkeypatch.setattr(rollout, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    return clock


def test_explicit_recovery_probes_every_owned_starting_container_readonly(monkeypatch):
    calls = fake_kubectl(monkeypatch, [pod("one", ready=False), pod("two", ready=False), pod("foreign", owner="other", ready=False)])
    assert rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True) == "20260912_0032"
    execs = [(args, kwargs) for args, kwargs in calls if args[3] == "exec"]
    assert [args[5] for args, _kwargs in execs] == ["one", "two"]
    assert all(kwargs["input"] == rollout.REVISION_PROBE for _args, kwargs in execs)
    assert all(0 < kwargs["timeout"] <= 60 for _args, kwargs in execs)


@pytest.mark.parametrize("invalid", ["wrong_image", "pod_owner", "rs_owner", "terminating", "unknown_state"])
def test_recovery_refuses_unproven_pod_identity_or_state(monkeypatch, invalid):
    candidate = pod("one", ready=False)
    options = {}
    if invalid == "wrong_image":
        candidate["spec"]["containers"][0]["image"] = "other-image"
    elif invalid == "pod_owner":
        candidate["metadata"]["ownerReferences"][0]["uid"] = "foreign-rs"
    elif invalid == "rs_owner":
        options["rs_owner"] = "foreign-deployment"
    elif invalid == "terminating":
        candidate["metadata"]["deletionTimestamp"] = "now"
    else:
        candidate["status"]["phase"] = "Unknown"
    calls = fake_kubectl(monkeypatch, [candidate], **options)
    with pytest.raises(ValueError):
        rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True)
    assert not any(args[3] == "exec" for args, _kwargs in calls)


def test_recovery_waits_until_all_active_containers_are_running(monkeypatch):
    candidates = [pod("one", ready=False), pod("two", ready=False, running=False)]
    clock = fake_clock(monkeypatch, lambda: candidates[1]["status"]["containerStatuses"][0].update(state={"running": {}}))
    calls = fake_kubectl(monkeypatch, candidates)
    assert rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True) == "20260912_0032"
    assert clock.waits == [5]
    assert [args[5] for args, _kwargs in calls if args[3] == "exec"] == ["one", "two"]


def test_recovery_waiting_is_bounded_to_330_seconds(monkeypatch):
    clock = fake_clock(monkeypatch)
    calls = fake_kubectl(monkeypatch, [pod("waiting", ready=False, running=False)])
    with pytest.raises(ValueError, match="Timed out"):
        rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True)
    assert clock.now == 330 and len(clock.waits) == 66
    assert not any(args[3] == "exec" for args, _kwargs in calls)


def test_recovery_exec_failure_retries_without_logging_sensitive_output(monkeypatch, capsys):
    clock = fake_clock(monkeypatch)
    fake_kubectl(monkeypatch, [pod("restarting", ready=False)], fail_probe=True)
    with pytest.raises(ValueError, match="Timed out"):
        rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True)
    assert clock.now == 330
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err


def test_recovery_aborts_if_deployment_image_changes_while_waiting(monkeypatch):
    image = {"value": IMAGE}
    fake_clock(monkeypatch, lambda: image.update(value="different-image"))
    calls = fake_kubectl(monkeypatch, [pod("one", ready=False, running=False)], deployment_image=lambda: image["value"])
    with pytest.raises(ValueError, match="image changed"):
        rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True)
    assert not any(args[3] == "exec" for args, _kwargs in calls)


@pytest.mark.parametrize("revisions", [{"one": "unknown"}, {"one": "20260912_0032", "two": "20261012_0033"}])
def test_recovery_never_accepts_unknown_or_disagreeing_revisions(monkeypatch, revisions):
    fake_kubectl(monkeypatch, [pod(name, ready=False) for name in revisions], revisions=revisions)
    with pytest.raises(ValueError):
        rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True)


def test_recovery_cli_still_requires_recreate_for_pre_removal_database(monkeypatch, tmp_path, capsys):
    fake_kubectl(monkeypatch, [pod("starting", ready=False)])
    revision_file = tmp_path / "source-revision"
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--namespace", "test-namespace", "--deployment", "backend",
                                    "--container", "backend", "--allow-starting-pod", "--revision-output", str(revision_file)])
    assert rollout.main() == 0
    assert revision_file.read_text() == "20260912_0032"
    assert json.loads(capsys.readouterr().out) == {"type": "Recreate", "rollingUpdate": None}


def test_recovery_uses_final_safe_marker_from_terminal_old_pods(monkeypatch):
    candidate = pod("failed", ready=False, phase="Failed", running=False)
    logs = {"failed": bootstrap_logs(backup=False, complete=False)}
    calls = fake_kubectl(monkeypatch, [candidate], logs=logs)
    assert rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True) == "20260912_0032"
    assert any(args[3] == "logs" for args, _kwargs in calls)
    assert not any(args[3] == "exec" for args, _kwargs in calls)


def test_recovery_reads_safe_markers_when_failed_and_unknown_pods_are_mixed(monkeypatch):
    failed = pod("failed", ready=False, phase="Failed", running=False)
    unknown = pod("unknown", ready=False, phase="Unknown", running=False)
    logs = {"failed": bootstrap_logs(backup=False, complete=False), "unknown": bootstrap_logs(backup=False, complete=False)}
    calls = fake_kubectl(monkeypatch, [failed, unknown], logs=logs)
    assert rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True) == "20260912_0032"
    assert len([args for args, _kwargs in calls if args[3] == "logs"]) == 2


def inherited_record():
    return {"deployment_uid": "deployment-uid", "source_revision": "20260912_0032",
            "target_revision": "20261012_0033", "preflight_revision": "20261012_0033",
            "verified_backup_keys": [BACKUP_KEY]}


@pytest.mark.parametrize("previous", [False, True])
def test_head_recovery_retains_verified_backup_before_replacing_unready_pod(monkeypatch, previous):
    candidate = pod("recovering", ready=False)
    candidate["status"]["containerStatuses"][0]["restartCount"] = int(previous)
    # 旧容器在 migration 后 prepare/check 失败，也必须先保留原备份证据。
    migrated = bootstrap_logs().rsplit("\n", 1)[0]
    logs = {"recovering": bootstrap_logs(source="20261012_0033", backup=False) if previous else migrated}
    calls = fake_kubectl(monkeypatch, [candidate], revisions={"recovering": "20261012_0033"},
                         logs=logs, previous_logs={"recovering": migrated})
    evidence = {}
    assert rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True,
                                    recovery_evidence=evidence) == "20261012_0033"
    assert evidence == inherited_record()
    assert any(args[3] == "logs" for args, _kwargs in calls)
    assert all(args[3] in {"get", "exec", "logs"} for args, _kwargs in calls)


@pytest.mark.parametrize("problem", ["no_backup", "wrong_source", "no_migration", "late_backup"])
def test_head_recovery_without_original_verified_backup_cannot_replace_pods(monkeypatch, problem):
    logs = bootstrap_logs()
    if problem == "no_backup":
        logs = bootstrap_logs(source="20261012_0033", backup=False)
    elif problem == "wrong_source":
        logs = bootstrap_logs(source="20260907_0031")
    elif problem == "no_migration":
        logs = bootstrap_logs(complete=False)
    else:
        line = f"Verified encrypted cloud database backup: {BACKUP_KEY}"
        logs = logs.replace(line + "\n", "") + "\n" + line
    fake_kubectl(monkeypatch, [pod("recovering", ready=False)], revisions={"recovering": "20261012_0033"},
                 logs={"recovering": logs})
    evidence = {}
    with pytest.raises(ValueError, match="no verified pre-removal backup"):
        rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True,
                                  recovery_evidence=evidence)
    assert evidence == {}


def test_ready_head_release_does_not_read_or_require_original_backup(monkeypatch):
    calls = fake_kubectl(monkeypatch, [pod("healthy")], revisions={"healthy": "20261012_0033"})
    evidence = {}
    assert rollout.inspect_revision("test-namespace", "backend", "backend", allow_starting_pod=True,
                                    recovery_evidence=evidence) == "20261012_0033"
    assert evidence == {} and not any(args[3] == "logs" for args, _kwargs in calls)


def test_new_image_startup_reports_inherited_backup_separately_from_new_source(monkeypatch):
    setup_startup(monkeypatch, {"new-pod": bootstrap_logs(source="20261012_0033", backup=False)})
    result = rollout.verify_startup("test-namespace", "backend", "backend", IMAGE, require_backup=False,
                                    source_revision="20261012_0033", recovery_evidence=inherited_record())
    assert result["source_revision"] == "20261012_0033"
    assert result["verified_backup_keys"] == []
    assert result["inherited_backup_evidence"] == {
        "source_revision": "20260912_0032", "target_revision": "20261012_0033", "verified_backup_keys": [BACKUP_KEY],
    }
    assert any(line.startswith("Inherited verified backup evidence") for line in result["lines"])


@pytest.mark.parametrize("problem", ["new_startup_incomplete", "wrong_deployment", "wrong_source", "bad_key", "wrong_image"])
def test_inherited_backup_never_bypasses_new_image_or_identity_checks(monkeypatch, problem):
    evidence = inherited_record()
    logs = bootstrap_logs(source="20261012_0033", backup=False, complete=problem != "new_startup_incomplete")
    setup_startup(monkeypatch, {"new-pod": logs}, images={"new-pod": "old-image"} if problem == "wrong_image" else None)
    if problem == "wrong_deployment":
        evidence["deployment_uid"] = "foreign"
    elif problem == "wrong_source":
        evidence["source_revision"] = "20260907_0031"
    elif problem == "bad_key":
        evidence["verified_backup_keys"] = ["https://secret"]
    with pytest.raises(ValueError):
        rollout.verify_startup("test-namespace", "backend", "backend", IMAGE, require_backup=False,
                                source_revision="20261012_0033", recovery_evidence=evidence)


def test_recovery_cli_persists_old_backup_and_new_startup_notice_keeps_provenance(monkeypatch, tmp_path, capsys):
    fake_kubectl(monkeypatch, [pod("old-pod", ready=False)], revisions={"old-pod": "20261012_0033"},
                 logs={"old-pod": bootstrap_logs()})
    output = tmp_path / "recovery.json"
    base = [str(SCRIPT), "--namespace", "test-namespace", "--deployment", "backend", "--container", "backend"]
    monkeypatch.setattr("sys.argv", base + ["--allow-starting-pod", "--recovery-evidence-output", str(output)])
    assert rollout.main() == 0
    assert json.loads(output.read_text()) == inherited_record()
    assert json.loads(capsys.readouterr().out)["type"] == "RollingUpdate"
    setup_startup(monkeypatch, {"new-pod": bootstrap_logs(source="20261012_0033", backup=False)})
    monkeypatch.setattr("sys.argv", base + ["--verify-startup", "--expected-image", IMAGE,
                                           "--source-revision", "20261012_0033", "--recovery-evidence-input", str(output)])
    assert rollout.main() == 0
    notice = capsys.readouterr()
    parsed = json.loads(notice.err.removeprefix("::notice title=Backend migration verification::"))
    assert parsed["source_revision"] == "20261012_0033"
    assert parsed["inherited_backup_evidence"]["source_revision"] == "20260912_0032"
    assert parsed["inherited_backup_evidence"]["verified_backup_keys"] == [BACKUP_KEY]


def test_recovery_workflow_passes_retained_evidence_across_image_update():
    backend = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8").split("  deploy-backend:", 1)[1]
    assert backend.index("--recovery-evidence-output") < backend.index('"image": "${{ steps.image.outputs.image }}"')
    assert backend.index("--recovery-evidence-input") > backend.index("rollout status")
