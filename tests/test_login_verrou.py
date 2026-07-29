"""Anti-blocage du navigateur de connexion manuelle.

Symptome constate le 28/07/2026 : apres une premiere connexion, le bouton
Reconnecter renvoyait une erreur 504 jusqu au redemarrage du service. Cause :
la fermeture du navigateur pouvait se figer sans jamais lever d erreur, si
bien que le verrou de profil n etait jamais relache, et que l ouverture
suivante l attendait sans limite de temps.
"""

import asyncio

import pytest

from app.config import settings
from app.services import login_browser as lb


class _PwFactice:
    async def stop(self):
        return None


class _ContexteQuiSeFige:
    """Un navigateur qui ne repond plus : il ne rend jamais la main."""

    async def close(self):
        await asyncio.sleep(3600)


class _ContexteQuiEchoue:
    async def close(self):
        raise RuntimeError("navigateur deja mort")


def _session(verrou, contexte):
    return lb.LoginSession(
        account_id=1,
        profile_slug="profil-test",
        platform="facebook",
        work_dir="/tmp/faithbook-test",
        pw=_PwFactice(),
        context=contexte,
        started_by_user_id=1,
        token="jeton",
        profile_lock=verrou,
    )


@pytest.fixture
def sans_effet_de_bord(monkeypatch):
    monkeypatch.setattr(settings, "login_close_timeout_seconds", 1)
    monkeypatch.setattr(lb.crypto, "discard_profile", lambda d: None)
    monkeypatch.setattr(lb, "_tuer_chromium_residuel", lambda d: None)


@pytest.mark.asyncio
async def test_ouverture_refusee_au_lieu_d_attendre_sans_fin(monkeypatch):
    """Un verrou deja pris doit donner une erreur immediate, pas un 504."""
    verrou = asyncio.Lock()
    await verrou.acquire()
    monkeypatch.setattr(lb, "get_profile_lock", lambda slug: verrou)
    monkeypatch.setattr(settings, "login_lock_wait_seconds", 1)

    manager = lb.LoginManager()
    with pytest.raises(lb.LoginBusy):
        await manager.start(1, "profil-test", "facebook", 1)


@pytest.mark.asyncio
async def test_verrou_libere_meme_si_la_fermeture_se_fige(sans_effet_de_bord):
    """Le coeur du defaut : close() qui se fige ne doit plus tout bloquer."""
    verrou = asyncio.Lock()
    await verrou.acquire()
    manager = lb.LoginManager()
    manager._active = _session(verrou, _ContexteQuiSeFige())

    await manager._teardown(seal=False)

    assert verrou.locked() is False
    assert manager._active is None


@pytest.mark.asyncio
async def test_verrou_libere_meme_si_la_fermeture_echoue(sans_effet_de_bord):
    verrou = asyncio.Lock()
    await verrou.acquire()
    manager = lb.LoginManager()
    manager._active = _session(verrou, _ContexteQuiEchoue())

    await manager._teardown(seal=False)

    assert verrou.locked() is False


@pytest.mark.asyncio
async def test_teardown_sans_session_ne_fait_rien(sans_effet_de_bord):
    manager = lb.LoginManager()
    await manager._teardown(seal=False)
    assert manager._active is None


@pytest.mark.asyncio
async def test_fermeture_bornee_ne_propage_jamais(sans_effet_de_bord):
    """Une fermeture abandonnee se journalise, elle ne remonte pas en erreur."""
    await lb.LoginManager._fermer_sans_se_figer(
        _ContexteQuiSeFige().close(), 1, "fermeture de test"
    )
