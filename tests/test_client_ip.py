from starlette.requests import Request

from app.config import settings
from app.services.request_ip import client_ip


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("test", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_ip_transmise_par_nginx_de_confiance(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "172.16.0.0/12")
    assert client_ip(_request("172.18.0.3", "203.0.113.25")) == "203.0.113.25"


def test_entete_forge_ignore_depuis_client_non_fiable(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "172.16.0.0/12")
    assert client_ip(_request("198.51.100.10", "1.2.3.4")) == "198.51.100.10"


def test_entete_invalide_ignore(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "172.16.0.0/12")
    assert client_ip(_request("172.18.0.3", "pas-une-ip")) == "172.18.0.3"
