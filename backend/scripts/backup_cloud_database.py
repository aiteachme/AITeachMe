"""Create and verify encrypted PostgreSQL backups before destructive migrations.

Recovery only writes an authenticated local pg_dump archive; it never restores a DB.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.env_support import get_env  # noqa: E402
from app.shared.infra.storage import get_artifact_store, run_store_sync  # noqa: E402
from app.shared.infra.storage.config import storage_is_s3  # noqa: E402

DESTRUCTIVE_REVISION = "20261012_0033"
BACKUP_PREFIX = f"backups/postgres/{DESTRUCTIVE_REVISION}/"
MAGIC = b"AITEACHME-PG-BACKUP-1\n"
KEY_CONTEXT = b"aiteachme/cloud-postgres-backup/aes-256-gcm/v1"
BLOCK_SIZE = 1024 * 1024
TAG_SIZE = 16


class BackupError(RuntimeError):
    """Safe-to-log backup failure without subprocess output or storage credentials."""


def _backup_secret(env_name: str = "AUTH_TOKEN_SECRET") -> bytes:
    secret = (get_env(env_name) or "").strip()
    if len(secret) < 32:
        raise BackupError("Backup encryption requires an auth secret of at least 32 characters.")
    return secret.encode("utf-8")


def _key(secret: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=KEY_CONTEXT).derive(secret)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _postgres_env() -> dict[str, str]:
    """Pass libpq connection settings through env, never argv or logged URLs."""

    try:
        url = make_url(get_env("DATABASE_URL") or "")
        if url.get_backend_name() != "postgresql" or not url.host or not url.database or not url.username:
            raise ValueError("Not an explicit PostgreSQL target")
        query_vars = {
            "sslmode": "PGSSLMODE", "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY",
            "sslrootcert": "PGSSLROOTCERT", "sslcrl": "PGSSLCRL",
            "sslcrldir": "PGSSLCRLDIR", "application_name": "PGAPPNAME",
            "connect_timeout": "PGCONNECT_TIMEOUT", "channel_binding": "PGCHANNELBINDING",
            "target_session_attrs": "PGTARGETSESSIONATTRS", "options": "PGOPTIONS",
            "hostaddr": "PGHOSTADDR", "gssencmode": "PGGSSENCMODE",
        }
        if any(key not in query_vars for key in url.query):
            raise ValueError("Unsupported libpq URL query")
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        env.update({
            "PGHOST": url.host, "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database, "PGUSER": url.username,
            "PGPASSWORD": url.password or "", "PGCONNECT_TIMEOUT": "30",
        })
        for key, value in url.query.items():
            if not isinstance(value, str):
                raise ValueError("Repeated libpq URL query")
            env[query_vars[key]] = value
        return env
    except Exception:
        raise BackupError("DATABASE_URL cannot be converted to explicit PostgreSQL backup settings.") from None


def _run_pg(args: list[str], *, env: dict[str, str] | None = None) -> None:
    try:
        result = subprocess.run(
            args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, check=False, timeout=3600,
        )
    except Exception:
        raise BackupError(f"{args[0]} could not complete; database migration has not started.") from None
    if result.returncode:
        raise BackupError(f"{args[0]} failed (exit={result.returncode}); database migration has not started.")


def _encrypt_dump(dump_path: Path, encrypted_path: Path, secret: bytes, source_revision: str) -> dict:
    salt, nonce = os.urandom(32), os.urandom(12)
    metadata = {
        "format": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": source_revision, "before_revision": DESTRUCTIVE_REVISION,
        "salt": salt.hex(), "nonce": nonce.hex(),
        "dump_sha256": _file_hash(dump_path), "dump_bytes": dump_path.stat().st_size,
    }
    header = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    aad = MAGIC + struct.pack(">I", len(header)) + header
    encryptor = Cipher(algorithms.AES(_key(secret, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    with dump_path.open("rb") as source, encrypted_path.open("xb") as target:
        os.chmod(encrypted_path, 0o600)
        target.write(aad)
        for block in iter(lambda: source.read(BLOCK_SIZE), b""):
            target.write(encryptor.update(block))
        target.write(encryptor.finalize())
        target.write(encryptor.tag)
    return metadata


def _decrypt_dump(encrypted_path: Path, output_path: Path, secret: bytes) -> dict:
    """Only used in private temp dirs; remove unauthenticated plaintext on failure."""

    created = False
    try:
        with encrypted_path.open("rb") as source:
            if source.read(len(MAGIC)) != MAGIC:
                raise ValueError("Unknown backup format")
            size_bytes = source.read(4)
            header_size = struct.unpack(">I", size_bytes)[0]
            if not 1 <= header_size <= 16 * 1024:
                raise ValueError("Invalid backup header")
            header = source.read(header_size)
            metadata = json.loads(header)
            if metadata.get("format") != 1:
                raise ValueError("Unknown backup format version")
            salt = bytes.fromhex(metadata["salt"])
            nonce = bytes.fromhex(metadata["nonce"])
            if len(salt) != 32 or len(nonce) != 12:
                raise ValueError("Invalid encryption parameters")
            cipher_start = source.tell()
            cipher_size = encrypted_path.stat().st_size - cipher_start - TAG_SIZE
            if cipher_size <= 0:
                raise ValueError("Empty or truncated backup")
            source.seek(-TAG_SIZE, os.SEEK_END)
            tag = source.read(TAG_SIZE)
            source.seek(cipher_start)
            decryptor = Cipher(algorithms.AES(_key(secret, salt)), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(MAGIC + size_bytes + header)
            digest, total = hashlib.sha256(), 0
            with output_path.open("xb") as target:
                created = True
                os.chmod(output_path, 0o600)
                remaining = cipher_size
                while remaining:
                    block = source.read(min(BLOCK_SIZE, remaining))
                    if not block:
                        raise ValueError("Truncated backup")
                    remaining -= len(block)
                    plain = decryptor.update(block)
                    digest.update(plain)
                    total += len(plain)
                    target.write(plain)
                final = decryptor.finalize()
                digest.update(final)
                total += len(final)
                target.write(final)
            if digest.hexdigest() != metadata["dump_sha256"] or total != metadata["dump_bytes"]:
                raise ValueError("Backup content mismatch")
            return metadata
    except Exception:
        if created:
            output_path.unlink(missing_ok=True)
        raise BackupError("Backup authentication or content validation failed; no usable plaintext was produced.") from None


def backup_before_custom_type_removal(source_revision: str) -> str:
    """Return the S3 key only after upload, download and authenticated verification."""

    if not storage_is_s3():
        raise BackupError("The destructive cloud migration requires S3 artifact storage for its backup.")
    secret = _backup_secret()
    env = _postgres_env()
    try:
        store = get_artifact_store()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        storage_key = f"{BACKUP_PREFIX}{stamp}-{uuid.uuid4().hex}.atmbak"
        with tempfile.TemporaryDirectory(prefix="aiteachme-pg-backup-") as directory:
            temp = Path(directory)
            dump_path = temp / "database.dump"
            with dump_path.open("xb"):
                os.chmod(dump_path, 0o600)
            _run_pg(["pg_dump", "--format=custom", "--no-password", "--file", str(dump_path)], env=env)
            if dump_path.stat().st_size == 0:
                raise BackupError("pg_dump produced an empty backup; migration has not started.")
            _run_pg(["pg_restore", "--list", str(dump_path)])
            encrypted_path = temp / "database.atmbak"
            metadata = _encrypt_dump(dump_path, encrypted_path, secret, source_revision)
            encrypted_hash = _file_hash(encrypted_path)
            run_store_sync(store.write_file, storage_key, encrypted_path)
            downloaded = run_store_sync(store.materialize_to_temp, storage_key, temp / "readback")
            if _file_hash(downloaded) != encrypted_hash:
                raise BackupError("Uploaded backup readback checksum mismatch; migration has not started.")
            verified_path = temp / "verified.dump"
            verified = _decrypt_dump(downloaded, verified_path, secret)
            if verified["dump_sha256"] != metadata["dump_sha256"]:
                raise BackupError("Uploaded backup plaintext checksum mismatch; migration has not started.")
            _run_pg(["pg_restore", "--list", str(verified_path)])
        return storage_key
    except BackupError:
        raise
    except Exception:
        raise BackupError("Cloud database backup storage or verification failed; migration has not started.") from None


def download_and_decrypt(storage_key: str, output_path: Path, *, secret_env: str = "AUTH_TOKEN_SECRET") -> None:
    """Download a backup to an explicit new local file, without connecting to a DB."""

    if not storage_is_s3() or not storage_key.startswith(BACKUP_PREFIX):
        raise BackupError("Recovery requires S3 storage and a database backup key.")
    if output_path.exists() or not output_path.parent.is_dir():
        raise BackupError("Recovery output must be a new file in an existing directory.")
    secret = _backup_secret(secret_env)
    output_created = False
    try:
        store = get_artifact_store()
        with tempfile.TemporaryDirectory(prefix="aiteachme-pg-recovery-") as directory:
            temp = Path(directory)
            encrypted_path = run_store_sync(store.materialize_to_temp, storage_key, temp / "download")
            verified_path = temp / "verified.dump"
            _decrypt_dump(encrypted_path, verified_path, secret)
            _run_pg(["pg_restore", "--list", str(verified_path)])
            # Do not publish unauthenticated plaintext or overwrite an existing backup.
            with output_path.open("xb") as target:
                output_created = True
                os.chmod(output_path, 0o600)
                with verified_path.open("rb") as source:
                    shutil.copyfileobj(source, target, length=BLOCK_SIZE)
    except Exception as exc:
        if output_created:
            output_path.unlink(missing_ok=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError("Backup recovery failed; no database restore was attempted.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    decrypt = commands.add_parser("decrypt", help="Download/decrypt an authenticated dump; never restores a database.")
    decrypt.add_argument("storage_key", help="Backup object key, not a signed URL.")
    decrypt.add_argument("--output", required=True, type=Path)
    decrypt.add_argument("--secret-env", default="AUTH_TOKEN_SECRET", help="Name of env var holding the auth secret from backup time.")
    args = parser.parse_args(argv)
    try:
        download_and_decrypt(args.storage_key, args.output, secret_env=args.secret_env)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Backup downloaded, authenticated and decrypted. No database restore was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
