from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from app.shared.infra import env_support
from app.workflows.support.system.settings import _env_entry


def _crypto_key(purpose: str) -> bytes:
    return hashlib.sha256(purpose.encode("utf-8")).digest()


def _write_encrypted_env(path: Path, values: dict[str, str]) -> None:
    payload = json.dumps({"env": values}, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encryption_key = _crypto_key("AiTeachMe bundled env encryption v1")
    mac_key = _crypto_key("AiTeachMe bundled env authentication v1")
    iv = bytes(range(16))

    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(payload) + padder.finalize()
    encryptor = Cipher(algorithms.AES(encryption_key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    tag = hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest()

    path.write_text(
        json.dumps(
            {
                "version": 1,
                "algorithm": "AES-256-CBC-HMAC-SHA256",
                "key_id": "aiteachme-bundled-env-v1",
                "iv": base64.b64encode(iv).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "tag": base64.b64encode(tag).decode("ascii"),
                "keys": sorted(values),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _reset_env_support() -> None:
    env_support.load_local_dotenv.cache_clear()
    env_support._load_bundled_env_values.cache_clear()
    env_support._BUNDLED_ENV_APPLIED_KEYS.clear()
    env_support._BUNDLED_ENV_VALUES.clear()
    env_support.set_runtime_env_overrides({})


def test_bundled_env_decrypts_and_tracks_source(tmp_path, monkeypatch) -> None:
    bundle_path = tmp_path / "aiteachme_bundled_env.enc.json"
    _write_encrypted_env(
        bundle_path,
        {
            "LLM_API_KEY": "bundle-key",
            "LLM_BASE_URL": "https://bundle.example.com/v1",
        },
    )
    monkeypatch.setenv("AITEACHME_BUNDLED_ENV_PATH", str(bundle_path))
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(env_support, "_dotenv_candidates", lambda: tuple())
    _reset_env_support()

    assert env_support.get_env("LLM_API_KEY") == "bundle-key"
    assert env_support.get_env("LLM_BASE_URL") == "https://bundle.example.com/v1"
    assert env_support.get_env_source("LLM_API_KEY") == "bundled"

    env_support.set_runtime_env_overrides({"LLM_API_KEY": "override-key"})
    assert env_support.get_env("LLM_API_KEY") == "override-key"
    assert env_support.get_env_source("LLM_API_KEY") == "runtime_override"

    env_support.set_runtime_env_overrides({})
    assert env_support.get_env("LLM_API_KEY") == "bundle-key"
    assert env_support.get_env_source("LLM_API_KEY") == "bundled"


def test_bundled_secret_entry_hides_reveal_value(tmp_path, monkeypatch) -> None:
    bundle_path = tmp_path / "aiteachme_bundled_env.enc.json"
    _write_encrypted_env(bundle_path, {"LLM_API_KEY": "bundle-key"})
    monkeypatch.setenv("AITEACHME_BUNDLED_ENV_PATH", str(bundle_path))
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(env_support, "_dotenv_candidates", lambda: tuple())
    _reset_env_support()

    entry = _env_entry(
        "llm.api_key",
        "API Key",
        ("LLM_API_KEY",),
        secret=True,
        restart_required=False,
    )

    assert entry.status == "configured"
    assert entry.secret_source == "bundled"
    assert entry.reveal_value is None
    assert entry.display_value == "预绑定密钥，已加密隐藏"
    assert entry.editable is True
    assert os.environ["LLM_API_KEY"] == "bundle-key"
