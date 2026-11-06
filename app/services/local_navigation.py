"""Chargement local borné des enseignes, sans fournisseur externe."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from playwright.async_api import Error as BrowserError

from app.services.web_challenges import WebChallenge, assert_no_challenge, _BROWSER_REASON

DOMAINS = ("walmart.com", "academy.com", "basspro.com", "cabelas.com")


def supported(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme in ("https", "http") and any(
        host == domain or host.endswith("." + domain) for domain in DOMAINS
    )


def http2_failure(error: Exception) -> bool:
    return isinstance(error, BrowserError) and "net::ERR_HTTP2_PROTOCOL_ERROR" in str(error)


async def navigate(page, target, timeout: int, guard, grace_seconds: int):
    """Attend seulement les vérifications autonomes, jamais les CAPTCHA humains.

    Aucun rechargement pendant l'attente. La dernière réponse de navigation
    remplace le 403 initial uniquement si le site a réellement renavigué.
    """
    latest = [None]

    def record(response):
        if response.request.is_navigation_request() and response.frame == page.main_frame:
            latest[0] = response

    page.on("response", record)
    try:
        initial = await page.goto(target.url, wait_until=target.wait_until, timeout=timeout)
        deadline = asyncio.get_running_loop().time() + grace_seconds
        while True:
            guard.raise_if_blocked()
            response = latest[0] or initial
            if response is not None and response.status == 429:
                raise WebChallenge()
            try:
                await assert_no_challenge(page)
                return response
            except WebChallenge as exc:
                remaining = deadline - asyncio.get_running_loop().time()
                if exc.reason != _BROWSER_REASON or remaining <= 0:
                    raise
                await asyncio.sleep(min(1, remaining))
    finally:
        page.remove_listener("response", record)
