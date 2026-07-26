from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Request, Route

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


def playwright_proxy() -> dict[str, str] | None:
    """Configuration proxy commune a tous les navigateurs Playwright."""
    value = settings.browser_proxy_url.strip()
    return {"server": value} if value else None


@dataclass
class BrowserRequestGuard:
    """Revalide chaque requete, y compris redirections et sous-ressources.

    Le proxy sortant configure dans Compose constitue la barriere reseau contre
    le DNS rebinding ; ce garde ajoute une validation applicative explicite et
    un message d'erreur exploitable dans les journaux.
    """

    blocked: UrlRejected | None = None
    blocked_url: str | None = None

    async def handle(self, route: Route, request: Request) -> None:
        if self.blocked is not None:
            await route.abort("blockedbyclient")
            return
        try:
            await asyncio.to_thread(check_url, request.url)
        except UrlRejected as exc:
            self.blocked = exc
            self.blocked_url = request.url
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    def raise_if_blocked(self) -> None:
        if self.blocked is not None:
            raise UrlRejected(
                f"Requete navigateur bloquee ({self.blocked_url}) : {self.blocked}"
            ) from self.blocked


async def install_browser_guard(context: BrowserContext) -> BrowserRequestGuard:
    guard = BrowserRequestGuard()
    await context.route("**/*", guard.handle)
    return guard
