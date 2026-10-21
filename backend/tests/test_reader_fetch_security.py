"""Protect the public reader boundary from SSRF and DNS rebinding."""

import asyncio
import socket

import httpx
import pytest

from app.shared.infra.search.readers import common


def _dns(monkeypatch, answers):
    calls = []

    def resolve(host, port, *args, **kwargs):
        calls.append(host)
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in answers[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return calls


def _http(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(common.httpx, "AsyncClient", client)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://localhost/",
    "http://localhost./",
    "http://sub.localhost/",
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "https://user:password@reader.test/",
])
def test_reader_rejects_unsafe_urls_before_network(monkeypatch, url):
    def unexpected_request(request):
        pytest.fail(f"Unsafe URL reached the HTTP transport: {request.url}")

    _http(monkeypatch, unexpected_request)
    with pytest.raises(ValueError):
        asyncio.run(common.fetch_url(url))


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"],
    ["10.0.0.1"],
    ["169.254.169.254"],
    ["::1"],
    ["93.184.216.34", "127.0.0.1"],
    [],
])
def test_reader_rejects_private_and_mixed_dns_answers(monkeypatch, addresses):
    _dns(monkeypatch, {"reader.test": addresses})

    def unexpected_request(request):
        pytest.fail(f"Private DNS answer reached the HTTP transport: {request.url}")

    _http(monkeypatch, unexpected_request)
    with pytest.raises(ValueError, match="non-public"):
        asyncio.run(common.fetch_url("http://reader.test/private"))


def test_reader_pins_dns_preserves_https_host_and_public_response_url(monkeypatch):
    dns_calls = _dns(monkeypatch, {"reader.test": ["93.184.216.34"]})

    def handle(request):
        assert request.url == httpx.URL("https://93.184.216.34:8443/article?q=1")
        assert request.headers["Host"] == "reader.test:8443"
        assert request.extensions["sni_hostname"] == "reader.test"
        assert request.headers["Authorization"] == "Bearer reader-key"
        return httpx.Response(200, text="public article")

    _http(monkeypatch, handle)
    response = asyncio.run(common.fetch_url(
        "https://reader.test:8443/article?q=1", headers={"Authorization": "Bearer reader-key"}
    ))
    assert response.text == "public article"
    assert str(response.url) == "https://reader.test:8443/article?q=1"
    assert dns_calls == ["reader.test"]


def test_reader_revalidates_dns_before_following_redirects(monkeypatch):
    _dns(monkeypatch, {"reader.test": ["93.184.216.34"], "internal.test": ["127.0.0.1"]})
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://internal.test/private"})

    _http(monkeypatch, handle)
    with pytest.raises(ValueError, match="non-public"):
        asyncio.run(common.fetch_url("https://reader.test/article"))
    assert len(requests) == 1


def test_reader_keeps_relative_redirects_and_strips_credentials_on_origin_change(monkeypatch):
    _dns(monkeypatch, {"reader.test": ["93.184.216.34"], "other.test": ["1.1.1.1"]})
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": "/next", "Set-Cookie": "private=value"})
        if len(requests) == 2:
            assert request.headers["Host"] == "reader.test"
            assert request.headers["Authorization"] == "Bearer reader-key"
            assert "Cookie" not in request.headers
            return httpx.Response(302, headers={"Location": "https://other.test/final"})
        assert request.headers["Host"] == "other.test"
        assert "Authorization" not in request.headers
        return httpx.Response(200, text="final")

    _http(monkeypatch, handle)
    response = asyncio.run(common.fetch_url(
        "https://reader.test/start", headers={"Authorization": "Bearer reader-key"}
    ))
    assert str(response.url) == "https://other.test/final"
    assert response.text == "final"
    assert len(requests) == 3


def test_reader_tries_other_validated_addresses_after_connection_failure(monkeypatch):
    _dns(monkeypatch, {"reader.test": ["93.184.216.34", "1.1.1.1"]})
    hosts = []

    def handle(request):
        hosts.append(request.url.host)
        if len(hosts) == 1:
            raise httpx.ConnectError("first address is unavailable", request=request)
        return httpx.Response(200, text="article")

    _http(monkeypatch, handle)
    assert asyncio.run(common.fetch_url("https://reader.test/article")).text == "article"
    assert hosts == ["93.184.216.34", "1.1.1.1"]
