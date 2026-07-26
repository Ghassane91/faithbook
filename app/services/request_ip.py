from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import settings


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """Retourne l'IP reelle sans faire confiance aux en-tetes d'un client.

    X-Forwarded-For n'est accepte que si le pair TCP direct appartient a un
    relais explicitement approuve. nginx remplace cet en-tete par $remote_addr.
    """
    peer = _valid_ip(request.client.host if request.client else None)
    if peer is None:
        return request.client.host if request.client else None

    peer_addr = ipaddress.ip_address(peer)
    if not any(peer_addr in network for network in settings.trusted_proxy_networks):
        return peer

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0]
    return _valid_ip(forwarded) or peer
