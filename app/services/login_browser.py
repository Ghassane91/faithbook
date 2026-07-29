from __future__ import annotations

import asyncio
import subprocess
import subprocess
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.async_api import BrowserContext, Playwright, async_playwright

from app.config import settings
from app.services import crypto
from app.services.profile_lock import get_profile_lock
from app.services.ssrf import playwright_proxy

logger = logging.getLogger(__name__)

# Cookies qui prouvent une session Facebook connectee.
FB_SESSION_COOKIES = {"c_user", "xs"}

LOGIN_URLS = {
    "facebook": "https://www.facebook.com/login",
}


@dataclass
class LoginSession:
    account_id: int
    profile_slug: str
    platform: str
    work_dir: Path
    pw: Playwright
    context: BrowserContext
    # Utilisateur FaithBook qui a ouvert cette connexion : seul lui peut voir
    # ou piloter l'ecran noVNC associe (empeche l'acces croise entre comptes).
    started_by_user_id: int
    # Jeton opaque exige par le proxy (nginx auth_request) pour atteindre
    # /novnc et /websockify ; regenere a chaque connexion, jamais journalise.
    token: str
    profile_lock: asyncio.Lock | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    token_expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
        + timedelta(minutes=settings.novnc_token_ttl_minutes)
    )


class LoginBusy(RuntimeError):
    """Une connexion manuelle est deja en cours (un seul ecran partage)."""


def _tuer_chromium_residuel(work_dir) -> None:
    """Dernier recours : Chromium survit parfois a une fermeture abandonnee.

    On ne vise que les processus dont le dossier de profil est celui de
    cette session. Les navigateurs de capture, qui utilisent d autres
    dossiers, ne sont jamais touches.
    """
    try:
        subprocess.run(["pkill", "-f", str(work_dir)], timeout=5, check=False)
    except Exception:  # noqa: BLE001
        logger.debug("Nettoyage des processus residuels impossible", exc_info=True)


def _tuer_chromium_residuel(work_dir) -> None:
    """Dernier recours : Chromium survit parfois a une fermeture abandonnee.

    On ne vise que les processus dont le dossier de profil est celui de
    cette session. Les navigateurs de capture, qui utilisent d autres
    dossiers, ne sont jamais touches.
    """
    try:
        subprocess.run(["pkill", "-f", str(work_dir)], timeout=5, check=False)
    except Exception:  # noqa: BLE001
        logger.debug("Nettoyage des processus residuels impossible", exc_info=True)


class LoginManager:
    """Pilote UN navigateur de connexion visible a la fois (ecran :99 unique).

    Le navigateur s'affiche via noVNC ; l'utilisateur se connecte lui-meme
    (identifiants + 2FA). A la fin, on exporte la session, on la chiffre et on
    scelle le profil. Aucun mot de passe n'est jamais lu ni stocke.
    """

    def __init__(self) -> None:
        self._active: LoginSession | None = None
        self._lock = asyncio.Lock()
        self._timeout_task: asyncio.Task | None = None

    @property
    def active_account_id(self) -> int | None:
        return self._active.account_id if self._active else None

    def status(self) -> dict:
        if not self._active:
            return {"active": False}
        return {
            "active": True,
            "account_id": self._active.account_id,
            "platform": self._active.platform,
            "started_at": self._active.started_at.isoformat(),
        }

    async def start(self, account_id: int, profile_slug: str, platform: str, started_by_user_id: int) -> str:
        """Ouvre le navigateur de connexion et retourne le jeton d'acces noVNC."""
        async with self._lock:
            if self._active is not None:
                raise LoginBusy(
                    "Une connexion manuelle est déjà en cours. Terminez-la avant d'en ouvrir une autre."
                )

            profile_lock = get_profile_lock(profile_slug)
            # Sans borne de temps, un verrou laisse pris par une session mal
            # fermee fait attendre cet appel indefiniment : nginx coupe a 120 s
            # et l utilisateur ne voit qu une erreur 504, sans explication.
            try:
                await asyncio.wait_for(
                    profile_lock.acquire(),
                    timeout=settings.login_lock_wait_seconds,
                )
            except (TimeoutError, asyncio.TimeoutError):
                raise LoginBusy(
                    "Le profil de ce compte est encore occup\u00e9 par une connexion "
                    "pr\u00e9c\u00e9dente qui ne s\u2019est pas refermee. Patientez un "
                    "instant puis r\u00e9essayez."
                ) from None
            work_dir = crypto.open_profile(profile_slug)
            pw = None
            try:
                pw = await async_playwright().start()
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(work_dir),
                    headless=False,  # visible sur DISPLAY=:99 -> noVNC
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"],
                    viewport={"width": 1600, "height": 900},
                    locale="fr-FR",
                    proxy=playwright_proxy(),
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(
                    LOGIN_URLS.get(platform, "about:blank"), wait_until="domcontentloaded"
                )
            except Exception:
                if pw is not None:
                    await pw.stop()
                crypto.discard_profile(work_dir)
                profile_lock.release()
                raise

            token = secrets.token_urlsafe(32)
            self._active = LoginSession(
                account_id=account_id,
                profile_slug=profile_slug,
                platform=platform,
                work_dir=work_dir,
                pw=pw,
                context=context,
                started_by_user_id=started_by_user_id,
                token=token,
                profile_lock=profile_lock,
            )
            logger.info("Connexion manuelle demarree pour le compte %s", account_id)

        # Filet de securite : ferme et abandonne apres le delai configure.
        self._timeout_task = asyncio.create_task(self._auto_cancel(account_id))
        return token

    def authorize(self, token: str | None, user_id: int) -> bool:
        """Le proxy noVNC (nginx auth_request) exige cette autorisation.

        Vraie seulement si une connexion est active, que le jeton correspond
        exactement, qu'il n'a pas expire, et que l'appelant est l'utilisateur
        qui a demarre cette connexion (isolation entre utilisateurs).
        """
        sess = self._active
        if sess is None or not token:
            return False
        if not secrets.compare_digest(token, sess.token):
            return False
        if datetime.now(timezone.utc) >= sess.token_expires_at:
            return False
        return sess.started_by_user_id == user_id

    async def _auto_cancel(self, account_id: int) -> None:
        await asyncio.sleep(settings.login_timeout_minutes * 60)
        if self._active and self._active.account_id == account_id:
            logger.warning("Connexion manuelle expiree (compte %s), abandon.", account_id)
            await self.cancel(account_id)

    async def probe(self, account_id: int) -> dict:
        """Etat de connexion en direct : cookies de session presents ou non."""
        if not self._active or self._active.account_id != account_id:
            return {"active": False, "logged_in": False}
        cookies = await self._active.context.cookies()
        names = {c["name"] for c in cookies if "facebook" in c.get("domain", "")}
        return {
            "active": True,
            "logged_in": FB_SESSION_COOKIES.issubset(names),
            "current_url": self._active.context.pages[0].url if self._active.context.pages else None,
        }

    async def finish(self, account_id: int) -> dict:
        """Valide la connexion : exporte + chiffre la session, scelle le profil.

        Retourne {ok, logged_in, encrypted_state}. Ne conserve la session que si
        les cookies attestent d'une connexion reussie.
        """
        if not self._active or self._active.account_id != account_id:
            raise RuntimeError("Aucune connexion en cours pour ce compte.")

        sess = self._active
        cookies = await sess.context.cookies()
        names = {c["name"] for c in cookies if "facebook" in c.get("domain", "")}
        logged_in = FB_SESSION_COOKIES.issubset(names)

        encrypted_state: str | None = None
        if logged_in:
            state = await sess.context.storage_state()
            encrypted_state = crypto.encrypt_text(json.dumps(state))

        await self._teardown(seal=logged_in)
        return {"ok": logged_in, "logged_in": logged_in, "encrypted_state": encrypted_state}

    async def cancel(self, account_id: int | None = None) -> None:
        if not self._active:
            return
        if account_id is not None and self._active.account_id != account_id:
            return
        await self._teardown(seal=False)

    @staticmethod
    async def _fermer_sans_se_figer(coro, limite: float, quoi: str) -> None:
        """Attend une fermeture sans jamais s y bloquer.

        Un navigateur qui ne repond plus ne leve pas d erreur : il ne rend
        simplement jamais la main. Ce cas, qu un try/except ne rattrape pas,
        laissait le verrou de profil pris jusqu au redemarrage suivant.
        """
        try:
            await asyncio.wait_for(coro, timeout=limite)
        except Exception:  # noqa: BLE001
            logger.warning("%s : abandon apres %s s", quoi, limite, exc_info=True)

    async def _teardown(self, seal: bool) -> None:
        sess = self._active
        if sess is None:
            return
        self._active = None
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
        limite = settings.login_close_timeout_seconds
        try:
            await self._fermer_sans_se_figer(
                sess.context.close(), limite, "Fermeture du navigateur de connexion"
            )
            await self._fermer_sans_se_figer(sess.pw.stop(), limite, "Arret de Playwright")
            if seal:
                crypto.seal_profile(sess.profile_slug, sess.work_dir)
        except Exception:  # noqa: BLE001
            logger.warning("Fin de connexion manuelle en erreur", exc_info=True)
        finally:
            # Ces trois nettoyages doivent avoir lieu quoi qu il arrive au-dessus.
            _tuer_chromium_residuel(sess.work_dir)
            crypto.discard_profile(sess.work_dir)
            if sess.profile_lock is not None and sess.profile_lock.locked():
                sess.profile_lock.release()
        logger.info(
            "Connexion manuelle terminee pour le compte %s (scelle=%s)",
            sess.account_id,
            seal,
        )


login_manager = LoginManager()
