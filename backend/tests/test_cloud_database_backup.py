from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from scripts import backup_cloud_database as backup
from scripts import bootstrap_cloud_db as bootstrap


class MemoryStore:
    def __init__(self, *, corrupt=False, fail=False):
        self.uploads = {}
        self.corrupt, self.fail = corrupt, fail

    async def write_file(self, key, path):
        if self.fail:
            raise RuntimeError("secret-s3-credential-do-not-log")
        self.uploads[key] = path.read_bytes()

    async def materialize_to_temp(self, key, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "readback.atmbak"
        value = self.uploads[key]
        path.write_bytes(value[:-1] + bytes([value[-1] ^ 1]) if self.corrupt else value)
        return path


@pytest.fixture
def backup_runtime(monkeypatch):
    values = {
        "AUTH_TOKEN_SECRET": "backup-auth-secret-version-one-" * 2,
        "DATABASE_URL": "postgresql+psycopg://testuser:p%40ssword@db.local:5433/course_db?sslmode=require",
    }
    monkeypatch.setattr(backup, "get_env", lambda key: values.get(key))
    monkeypatch.setattr(backup, "storage_is_s3", lambda: True)
    store = MemoryStore()
    monkeypatch.setattr(backup, "get_artifact_store", lambda: store)
    calls = []
    plain = b"PGDMP" + b"private-custom-question-history\n" * 100000

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        assert "p@ssword" not in " ".join(args)
        assert "postgresql" not in " ".join(args)
        if args[0] == "pg_dump":
            assert kwargs["env"]["PGPASSWORD"] == "p@ssword"
            assert kwargs["env"]["PGHOST"] == "db.local"
            assert kwargs["env"]["PGPORT"] == "5433"
            assert kwargs["env"]["PGSSLMODE"] == "require"
            Path(args[args.index("--file") + 1]).write_bytes(plain)
        else:
            assert args[:2] == ["pg_restore", "--list"]
            assert Path(args[-1]).read_bytes() == plain
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    return SimpleNamespace(values=values, store=store, calls=calls, plain=plain)


def test_backup_uploads_only_ciphertext_and_recovers_full_archive(backup_runtime, tmp_path):
    runtime = backup_runtime
    key = backup.backup_before_custom_type_removal("20260912_0032")
    assert key.startswith(backup.BACKUP_PREFIX)
    assert len(runtime.store.uploads) == 1
    ciphertext = runtime.store.uploads[key]
    assert ciphertext.startswith(backup.MAGIC)
    assert b"private-custom-question-history" not in ciphertext
    assert b"PGDMP" not in ciphertext
    assert [call[0][0] for call in runtime.calls] == ["pg_dump", "pg_restore", "pg_restore"]
    dump_temp = Path(runtime.calls[0][0][-1])
    assert not dump_temp.exists(), "Temporary unencrypted dump must be removed"
    output = tmp_path / "recovery.dump"
    backup.download_and_decrypt(key, output)
    assert output.read_bytes() == runtime.plain
    assert all("--list" in args for args, _kwargs in runtime.calls if args[0] == "pg_restore")
    with pytest.raises(backup.BackupError, match="new file"):
        backup.download_and_decrypt(key, output)
    assert output.read_bytes() == runtime.plain


@pytest.mark.parametrize("damage", ["wrong_key", "ciphertext", "header", "truncated"])
def test_recovery_rejects_tampering_without_publishing_plaintext(backup_runtime, tmp_path, damage):
    runtime = backup_runtime
    key = backup.backup_before_custom_type_removal("20260912_0032")
    raw = runtime.store.uploads[key]
    if damage == "wrong_key":
        runtime.values["AUTH_TOKEN_SECRET"] = "other-secret-value-" * 3
    elif damage == "ciphertext":
        runtime.store.uploads[key] = raw[:-20] + bytes([raw[-20] ^ 1]) + raw[-19:]
    elif damage == "header":
        runtime.store.uploads[key] = raw.replace(b"20260912_0032", b"20260912_0031", 1)
    else:
        runtime.store.uploads[key] = raw[:-8]
    output = tmp_path / "invalid.dump"
    with pytest.raises(backup.BackupError, match="authentication|validation"):
        backup.download_and_decrypt(key, output)
    assert not output.exists()


def test_rotated_auth_secret_can_use_original_secret_environment(backup_runtime, tmp_path):
    runtime = backup_runtime
    key = backup.backup_before_custom_type_removal("20260912_0032")
    runtime.values["BACKUP_ORIGINAL_AUTH_SECRET"] = runtime.values["AUTH_TOKEN_SECRET"]
    runtime.values["AUTH_TOKEN_SECRET"] = "replacement-secret-" * 3
    output = tmp_path / "old-secret.dump"
    backup.download_and_decrypt(key, output, secret_env="BACKUP_ORIGINAL_AUTH_SECRET")
    assert output.read_bytes() == runtime.plain


@pytest.mark.parametrize("failure", ["pg_dump", "pg_restore", "upload", "readback"])
def test_backup_failures_stop_without_leaking_sensitive_errors(backup_runtime, failure, monkeypatch):
    runtime = backup_runtime
    if failure in {"pg_dump", "pg_restore"}:
        original = backup.subprocess.run

        def fail_command(args, **kwargs):
            if args[0] == failure:
                return SimpleNamespace(returncode=1, stderr=b"secret-pg-password-do-not-log")
            return original(args, **kwargs)

        monkeypatch.setattr(backup.subprocess, "run", fail_command)
    elif failure == "upload":
        runtime.store.fail = True
    else:
        runtime.store.corrupt = True
    with pytest.raises(backup.BackupError) as exc:
        backup.backup_before_custom_type_removal("20260912_0032")
    assert "secret-pg" not in str(exc.value) and "secret-s3" not in str(exc.value)
    if failure in {"pg_dump", "pg_restore"}:
        assert runtime.store.uploads == {}


@pytest.mark.parametrize("failure", ["short_secret", "non_s3", "unknown_pg_query", "missing_pg_host"])
def test_invalid_backup_configuration_never_runs_dump(backup_runtime, monkeypatch, failure):
    if failure == "short_secret":
        backup_runtime.values["AUTH_TOKEN_SECRET"] = "short"
    elif failure == "non_s3":
        monkeypatch.setattr(backup, "storage_is_s3", lambda: False)
    elif failure == "missing_pg_host":
        backup_runtime.values["DATABASE_URL"] = "postgresql+psycopg://user:pass@/db"
    else:
        backup_runtime.values["DATABASE_URL"] += "&unknown_setting=value"
    with pytest.raises(backup.BackupError):
        backup.backup_before_custom_type_removal("20260912_0032")
    assert backup_runtime.calls == []


def test_pg_env_preserves_explicit_ssl_and_ignores_inherited_targets(backup_runtime, monkeypatch):
    monkeypatch.setenv("PGHOST", "wrong-host")
    monkeypatch.setenv("PGSERVICE", "wrong-service")
    backup_runtime.values["DATABASE_URL"] += "&sslrootcert=%2Fsecure%2Froot.pem&sslcert=%2Fsecure%2Fclient.pem&sslkey=%2Fsecure%2Fclient.key"
    env = backup._postgres_env()
    assert env["PGHOST"] == "db.local"
    assert "PGSERVICE" not in env
    assert env["PGSSLMODE"] == "require"
    assert env["PGSSLROOTCERT"] == "/secure/root.pem"
    assert env["PGSSLCERT"] == "/secure/client.pem"
    assert env["PGSSLKEY"] == "/secure/client.key"


def test_recovery_copy_failure_removes_partial_output(backup_runtime, monkeypatch, tmp_path):
    key = backup.backup_before_custom_type_removal("20260912_0032")

    def fail_copy(_source, target, **_kwargs):
        target.write(b"partial-plaintext")
        raise OSError("disk full")

    monkeypatch.setattr(backup.shutil, "copyfileobj", fail_copy)
    output = tmp_path / "partial.dump"
    with pytest.raises(backup.BackupError, match="recovery failed"):
        backup.download_and_decrypt(key, output)
    assert not output.exists()


def test_decrypt_failure_removes_private_partial_plaintext(backup_runtime, tmp_path):
    key = backup.backup_before_custom_type_removal("20260912_0032")
    encrypted = tmp_path / "corrupt.atmbak"
    raw = backup_runtime.store.uploads[key]
    encrypted.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    output = tmp_path / "unauthenticated.dump"
    with pytest.raises(backup.BackupError, match="authentication"):
        backup._decrypt_dump(encrypted, output, backup._backup_secret())
    assert not output.exists()


@pytest.mark.parametrize("current", ["20260912_0032", "20260907_0031"])
def test_backup_guard_follows_real_alembic_upgrade_path(monkeypatch, current):
    calls = []
    monkeypatch.setattr(backup, "backup_before_custom_type_removal", lambda revision: calls.append(revision) or "verified-key")
    bootstrap._backup_before_destructive_upgrade(current, "20261012_0033")
    assert calls == [current]


@pytest.mark.parametrize("current,expected", [(None, "20261012_0033"), ("20261012_0033", "20261012_0033"), ("20260907_0031", "20260912_0032")])
def test_backup_guard_skips_empty_already_upgraded_and_non_destructive_paths(monkeypatch, current, expected):
    monkeypatch.setattr(backup, "backup_before_custom_type_removal", lambda _revision: pytest.fail("Must skip backup"))
    bootstrap._backup_before_destructive_upgrade(current, expected)


@pytest.mark.parametrize("backup_fails", [False, True])
def test_bootstrap_never_migrates_before_backup_verification(monkeypatch, backup_fails):
    calls = []

    @contextmanager
    def fake_lock():
        calls.append("lock")
        try:
            yield
        finally:
            calls.append("unlock")

    monkeypatch.setattr(bootstrap, "_bootstrap_lock", fake_lock)
    monkeypatch.setattr(bootstrap, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(bootstrap, "collect_project_settings_config_errors", lambda: [])
    monkeypatch.setattr(bootstrap, "get_env_bool", lambda *_args: False)
    monkeypatch.setattr(bootstrap, "_inspect_database_state", lambda: ("20260912_0032", ["course"]))
    monkeypatch.setattr(bootstrap, "_get_alembic_head_revision", lambda: "20261012_0033")

    def verified_backup(_current, _expected):
        calls.append("backup")
        if backup_fails:
            raise backup.BackupError("Verification failed")

    monkeypatch.setattr(bootstrap, "_backup_before_destructive_upgrade", verified_backup)
    monkeypatch.setattr(bootstrap, "_run_alembic_upgrade_head", lambda: calls.append("upgrade"))
    monkeypatch.setattr(bootstrap, "_run_post_migration_steps", lambda: calls.append("prepare/check"))
    assert bootstrap.main([]) == (1 if backup_fails else 0)
    assert calls == (["lock", "backup", "unlock"] if backup_fails else ["lock", "backup", "upgrade", "prepare/check", "unlock"])


def test_concurrent_bootstraps_reread_revision_under_dedicated_lock(monkeypatch):
    mutex = threading.Lock()
    first_backup_started = threading.Event()
    second_lock_attempted = threading.Event()
    calls = []
    state = {"revision": "20260912_0032"}
    app_engine = SimpleNamespace(url="postgresql+psycopg://unused/unused")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append("close")

        def execute(self, query, values):
            assert values == {"key": bootstrap.BOOTSTRAP_LOCK_KEY}
            if "pg_advisory_unlock" in str(query):
                calls.append("unlock")
                mutex.release()
            else:
                if first_backup_started.is_set():
                    second_lock_attempted.set()
                mutex.acquire(timeout=5) or pytest.fail("Lock remained held")
                calls.append("lock")

    class LockEngine:
        def connect(self):
            return Connection()

        def dispose(self):
            calls.append("dispose")

    def create_lock_engine(url, **kwargs):
        assert url == app_engine.url
        assert kwargs == {"poolclass": bootstrap.NullPool, "isolation_level": "AUTOCOMMIT"}
        return LockEngine()

    def inspect():
        assert mutex.locked()
        calls.append(f"inspect:{state['revision']}")
        return state["revision"], ["course"]

    def verified_backup(revision):
        assert revision == "20260912_0032"
        assert mutex.locked()
        calls.append("backup")
        first_backup_started.set()
        assert second_lock_attempted.wait(timeout=5)
        return "verified-key"

    def upgrade():
        assert mutex.locked()
        state["revision"] = "20261012_0033"
        calls.append("upgrade")

    def prepare():
        assert mutex.locked()
        calls.append("prepare/check")

    monkeypatch.setattr(bootstrap, "get_engine", lambda: app_engine)
    monkeypatch.setattr(bootstrap, "create_engine", create_lock_engine)
    monkeypatch.setattr(bootstrap, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(bootstrap, "collect_project_settings_config_errors", lambda: [])
    monkeypatch.setattr(bootstrap, "get_env_bool", lambda *_args: False)
    monkeypatch.setattr(bootstrap, "_get_alembic_head_revision", lambda: "20261012_0033")
    monkeypatch.setattr(bootstrap, "_inspect_database_state", inspect)
    monkeypatch.setattr(backup, "backup_before_custom_type_removal", verified_backup)
    monkeypatch.setattr(bootstrap, "_run_alembic_upgrade_head", upgrade)
    monkeypatch.setattr(bootstrap, "_run_post_migration_steps", prepare)
    results = []
    first = threading.Thread(target=lambda: results.append(bootstrap.main([])))
    second = threading.Thread(target=lambda: results.append(bootstrap.main([])))
    first.start()
    try:
        assert first_backup_started.wait(timeout=5)
        second.start()
        first.join(timeout=10)
        second.join(timeout=10)
        assert not first.is_alive() and not second.is_alive()
    finally:
        second_lock_attempted.set()
        first.join(timeout=10)
        if second.ident is not None:
            second.join(timeout=10)
    assert results == [0, 0]
    assert calls.count("backup") == 1
    assert calls.count("lock") == calls.count("unlock") == calls.count("dispose") == 2
    second_lock_index = calls.index("lock", calls.index("lock") + 1)
    assert calls[second_lock_index + 1] == "inspect:20261012_0033"
