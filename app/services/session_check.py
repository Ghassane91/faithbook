from __future__ import annotations

import json
import logging

from playwright.async_api import async_playwright

from app.config import settings
from app.models import AccountStatus
from app.services import crypto

logger = logging.getLogger(__name__)

FB_SESSION_COOKIES = {"c_user", "xs"}
HOME_URLS = {"facebook": "https://www.facebook.com/"}
# Fragments d'URL qui trahissent une session invalide / une verification.
REAUTH_MARKERS = ("login", "checkpoint", "recover", "two_factor")


async def check_account(profile_slug: str, platform: str) -> dict:
    """Ouvre le profil en headless et détermine l'état de la session.

    Retourne {status, logged_in, final_url, detail}. Rescelle le profil pour
    conserver d'éventuels cookies rafraîchis par la plateforme.
    """
    if not crypto.profile_exists(profile_slug):
        return {
            "status": AccountStatus.never,
            "logged_in": False,
            "final_url": None,
            "detail": "Aucune session enregistrée : connectez le compte.",
        }

    work = crypto.open_profile(profile_slug)
    pw = None
    context = None
    try:
        pw = await async_playwright().start()
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(work),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            locale="fr-FR",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(
            HOME_URLS.get(platform, "about:blank"),
            wait_until="domcontentloaded",
            timeout=settings.default_timeout_ms,
        )
        await page.wait_for_timeout(1500)
        final_url = page.url

        cookies = await context.cookies()
        names = {c["name"] for c in cookies if "facebook" in c.get("domain", "")}
        logged_in = FB_SESSION_COOKIES.issubset(names)
        reauth = any(m in final_url.lower() for m in REAUTH_MARKERS)

        # On rescelle : la plateforme a pu faire tourner les cookies.
        await context.close()
        context = None
        crypto.seal_profile(profile_slug, work)

        if logged_in and not reauth:
            return {
                "status": AccountStatus.connected,
                "logged_in": True,
                "final_url": final_url,
                "detail": "Session active.",
            }
        if reauth:
            return {
                "status": AccountStatus.verification_required,
                "logged_in": False,
                "final_url": final_url,
                "detail": "La plateforme demande une nouvelle vérification (connexion ou 2FA).",
            }
        return {
            "status": AccountStatus.expired,
            "logged_in": False,
            "final_url": final_url,
            "detail": "Session expirée : reconnectez le compte.",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Test de session en erreur (%s)", profile_slug, exc_info=True)
        return {
            "status": AccountStatus.error,
            "logged_in": False,
            "final_url": None,
            "detail": f"Erreur pendant le test : {exc}",
        }
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:  # noqa: BLE001
                pass
        crypto.discard_profile(work)


def encrypted_state_to_storage(encrypted: str | None) -> dict | None:
    clair = crypto.decrypt_text(encrypted)
    if not clair:
        return None
    try:
        return json.loads(clair)
    except json.JSONDecodeError:
        return None
