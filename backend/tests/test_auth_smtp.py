from __future__ import annotations

import socket

import pytest

from app.shared.infra.exceptions import AITeachMeError
from app.workflows.support.auth.commands import (
    _normalize_smtp_address_family,
    _resolve_smtp_target_addresses,
)


def test_normalize_smtp_address_family_accepts_supported_values() -> None:
    assert _normalize_smtp_address_family(None) == "auto"
    assert _normalize_smtp_address_family("") == "auto"
    assert _normalize_smtp_address_family("ipv4") == "ipv4"
    assert _normalize_smtp_address_family("IPv6") == "ipv6"


def test_normalize_smtp_address_family_rejects_unknown_value() -> None:
    with pytest.raises(AITeachMeError) as exc_info:
        _normalize_smtp_address_family("bogus")

    assert exc_info.value.error_code == "AUTH_SMTP_NOT_CONFIGURED"


def test_resolve_smtp_target_addresses_filters_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("220.197.33.205", 465)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("220.197.33.215", 465)),
    ]

    def fake_getaddrinfo(host: str, port: int, *, family: int, type: int):
        assert host == "smtp.163.com"
        assert port == 465
        assert family == socket.AF_INET
        assert type == socket.SOCK_STREAM
        return expected

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert (
        _resolve_smtp_target_addresses(
            "smtp.163.com",
            465,
            address_family="ipv4",
        )
        == expected
    )
