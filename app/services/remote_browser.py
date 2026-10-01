"""Connexion CDP optionnelle : pages publiques, contexte neuf, erreurs expurgees."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit

from app.config import settings
from app.services import ssrf

logger = logging.getLogger(__name__)


class RemoteBrowserError(RuntimeError):
    """Echec distant sans retry automatique ni secret dans le message."""


def domain_allowed(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    domains = [d.strip().lower().rstrip(".") for d in settings.remote_browser_domains.split(",") if d.strip()]
    return parsed.scheme in ("http", "https") and any(
        host == domain or host.endswith("." + domain) for domain in domains
    )


def selected(target, *, account_storage=None, account_profile_slug=None, identifiants=None) -> bool:
    # Ne jamais transmettre de session HuntX/Facebook au fournisseur.
    if settings.remote_browser_provider == "disabled":
        return False
    if (account_storage is not None or account_profile_slug or identifiants is not None
            or target.account_id or target.session_profile or target.storage_state_json):
        return False
    return domain_allowed(target.url)


def endpoint() -> str:
    value = settings.remote_browser_cdp_url.get_secret_value().strip()
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme == "wss" and bool(parsed.hostname) and not parsed.fragment
        if settings.remote_browser_provider == "brightdata":
            valid = valid and parsed.hostname == "brd.superproxy.io"
    except ValueError:
        valid = False
    if not valid:
        raise RemoteBrowserError("Configurer REMOTE_BROWSER_CDP_URL avec l'endpoint WSS du fournisseur.")
    if settings.allow_private_targets:
        raise RemoteBrowserError("Le navigateur distant exige ALLOW_PRIVATE_TARGETS=false.")
    return value


async def close_safely(resource) -> None:
    if resource is not None:
        try:
            await asyncio.wait_for(resource.close(), timeout=5)
        except Exception:
            # Une erreur CDP peut inclure le mot de passe dans son URL.
            logger.warning("Fermeture du navigateur distant incomplete.")


async def connect(pw, context_kwargs: dict):
    browser = await pw.chromium.connect_over_cdp(
        endpoint(), timeout=settings.remote_browser_timeout_seconds * 1000
    )
    try:
        # Le contexte CDP par defaut peut etre partage : toujours en creer un.
        context = await browser.new_context(**{**context_kwargs, "ignore_https_errors": False})
    except BaseException:
        await close_safely(browser)
        raise
    return browser, context


class RemoteRequestGuard(ssrf.BrowserRequestGuard):
    async def handle(self, route, request) -> None:
        if request.is_navigation_request() and request.frame.parent_frame is None:
            parsed = urlsplit(request.url)
            if parsed.username or parsed.password or not domain_allowed(request.url):
                self.blocked = ssrf.UrlRejected("Redirection distante hors des domaines autorises.")
                # Pas d'URL susceptible de contenir un jeton dans le journal.
                self.blocked_url = "[navigation distante]"
                await route.abort("blockedbyclient")
                return
        await super().handle(route, request)


async def install_guard(context):
    guard = RemoteRequestGuard()
    await context.route("**/*", guard.handle)
    return guard


async def navigate(page, context, target, timeout: int, guard):
    # Une verification peut remplacer la reponse 403 initiale par une page 200.
    latest = [None]

    def record(response):
        if response.request.is_navigation_request() and response.frame == page.main_frame:
            latest[0] = response

    page.on("response", record)
    client = None
    try:
        if settings.remote_browser_provider == "brightdata":
            client = await context.new_cdp_session(page)
        initial = await page.goto(target.url, wait_until=target.wait_until, timeout=timeout)
        guard.raise_if_blocked()
        if client is not None:
            # Commande documentee par Bright Data ; le delai total est borne
            # par capture_page, y compris une resolution qui ne se termine pas.
            result = await client.send("Captcha.waitForSolve", {"detectTimeout": 10_000})
            if result.get("status") in ("failed", "error"):
                from app.services.web_challenges import WebChallenge
                raise WebChallenge("La verification du fournisseur n'a pas abouti.")
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
        guard.raise_if_blocked()
        return latest[0] or initial
    finally:
        page.remove_listener("response", record)
        # La fermeture du contexte termine aussi la session CDP.
