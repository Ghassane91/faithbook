from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import settings


class UrlRejected(ValueError):
    """L'URL vise une ressource interdite (interne) ou hors liste blanche."""


def _is_internal_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # illisible => on refuse par prudence
    # Adresses privees, loopback, lien-local, et surtout la metadata cloud
    # 169.254.169.254 (couverte par is_link_local).
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def check_url(url: str) -> None:
    """Valide une URL avant toute navigation. Lève UrlRejected si interdite.

    Protège contre le SSRF : sans ce garde, une cible « http://169.254.169.254 »
    ou « http://localhost:8020 » ferait accéder le moteur de capture à des
    services internes ou aux métadonnées du cloud.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlRejected("Seuls http et https sont autorisés.")

    host = parsed.hostname
    if not host:
        raise UrlRejected("URL sans nom d'hôte.")

    host_l = host.lower()

    # Liste blanche de domaines, si configurée.
    autorises = settings.allowed_domain_list
    if autorises:
        ok = any(host_l == d or host_l.endswith("." + d) for d in autorises)
        if not ok:
            raise UrlRejected(
                f"Le domaine « {host} » n'est pas dans la liste des domaines autorisés."
            )

    if settings.allow_private_targets:
        return

    # Noms internes evidents.
    if host_l in ("localhost",) or host_l.endswith(".local") or host_l.endswith(".internal"):
        raise UrlRejected("Les adresses internes ne sont pas autorisées.")

    # Résolution DNS : on refuse si une seule des IP est interne (protège d'un
    # DNS qui renverrait une IP privée).
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UrlRejected(f"Nom d'hôte introuvable : {host}") from exc

    for info in infos:
        ip = info[4][0]
        if _is_internal_ip(ip):
            raise UrlRejected(
                f"« {host} » pointe vers une adresse interne ({ip}) : accès refusé."
            )
