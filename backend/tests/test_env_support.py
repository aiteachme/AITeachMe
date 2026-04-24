from __future__ import annotations

from app.shared.infra.env_support import get_env_list


def test_get_env_list_splits_comma_and_strips_spaces(monkeypatch) -> None:
    monkeypatch.setenv("UNIT_TEST_API_KEYS", "key-a, key-b ,key-c")

    assert get_env_list("UNIT_TEST_API_KEYS") == ["key-a", "key-b", "key-c"]


def test_get_env_list_keeps_semicolon_and_newline_inside_values(monkeypatch) -> None:
    monkeypatch.setenv("UNIT_TEST_API_KEYS", "key-a;key-b\nkey-c, key-d")

    assert get_env_list("UNIT_TEST_API_KEYS") == ["key-a;key-b\nkey-c", "key-d"]


def test_get_env_list_dedupes_after_trim(monkeypatch) -> None:
    monkeypatch.setenv("UNIT_TEST_API_KEYS", " key-a, key-a , ,key-b")

    assert get_env_list("UNIT_TEST_API_KEYS") == ["key-a", "key-b"]
