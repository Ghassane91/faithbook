"""Tests des canaux d alerte : aucun appel reseau reel."""

from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import channels, notify


@pytest.fixture(autouse=True)
def canaux_neutres(monkeypatch):
    """Part toujours d une configuration vide.

    Sans cela, ces tests dependraient du .env de la machine : depuis que
    Telegram y est configure, ils echouaient sur un produit pourtant sain.
    """
    monkeypatch.setattr(settings, "notify_telegram_bot_token", "")
    monkeypatch.setattr(settings, "notify_telegram_chat_id", "")
    monkeypatch.setattr(settings, "notify_webhook_url", "")


@pytest.fixture
def telegram(monkeypatch, canaux_neutres):
    monkeypatch.setattr(settings, "notify_telegram_bot_token", "jeton")
    monkeypatch.setattr(settings, "notify_telegram_chat_id", "12345")


@pytest.fixture
def webhook(monkeypatch, canaux_neutres):
    monkeypatch.setattr(settings, "notify_webhook_url", "https://exemple.test/hook")


class _FausseReponse:
    def __init__(self, erreur=None):
        self._erreur = erreur

    def raise_for_status(self):
        if self._erreur:
            raise self._erreur


def _capteur(monkeypatch, erreur_pour=None):
    """Remplace httpx.post et enregistre les appels."""
    appels = []

    def faux_post(url, json=None, timeout=None):
        appels.append({"url": url, "json": json, "timeout": timeout})
        if erreur_pour and erreur_pour in url:
            return _FausseReponse(RuntimeError("service indisponible"))
        return _FausseReponse()

    monkeypatch.setattr(channels.httpx, "post", faux_post)
    return appels


def test_canaux_inactifs_par_defaut():
    assert channels.telegram_actif() is False
    assert channels.webhook_actif() is False


def test_telegram_exige_les_deux_reglages(monkeypatch):
    monkeypatch.setattr(settings, "notify_telegram_bot_token", "jeton")
    monkeypatch.setattr(settings, "notify_telegram_chat_id", "")
    assert channels.telegram_actif() is False


def test_aucun_envoi_si_rien_configure(monkeypatch):
    appels = _capteur(monkeypatch)
    assert channels.broadcast("Sujet", "Corps") == []
    assert appels == []


def test_envoi_telegram(telegram, monkeypatch):
    appels = _capteur(monkeypatch)
    assert channels.broadcast("Sujet", "Corps") == ["telegram"]
    assert len(appels) == 1
    assert "jeton" in appels[0]["url"]
    assert appels[0]["json"]["chat_id"] == "12345"
    assert appels[0]["json"]["text"] == "Sujet\n\nCorps"


def test_message_telegram_tronque(telegram, monkeypatch):
    appels = _capteur(monkeypatch)
    channels.broadcast("Sujet", "x" * 9000)
    assert len(appels[0]["json"]["text"]) == channels.TELEGRAM_MAX


def test_webhook_couvre_slack_et_discord(webhook, monkeypatch):
    appels = _capteur(monkeypatch)
    assert channels.broadcast("Sujet", "Corps") == ["webhook"]
    charge = appels[0]["json"]
    assert charge["text"] == "Sujet\n\nCorps"
    assert charge["content"] == "Sujet\n\nCorps"
    assert charge["sujet"] == "Sujet"


def test_un_canal_en_panne_ne_bloque_pas_l_autre(telegram, webhook, monkeypatch):
    appels = _capteur(monkeypatch, erreur_pour="telegram.org")
    assert channels.broadcast("Sujet", "Corps") == ["webhook"]
    assert len(appels) == 2


def test_send_diffuse_meme_sans_destinataire_mail(monkeypatch):
    monkeypatch.setattr(notify, "_recipient", lambda: None)
    recus = []
    monkeypatch.setattr(notify.channels, "broadcast", lambda s, c: recus.append(s))
    notify._send("Sujet", "Corps")
    assert recus == ["Sujet"]


def test_send_diffuse_meme_si_le_mail_echoue(monkeypatch):
    monkeypatch.setattr(notify, "_recipient", lambda: "a@b.test")

    def boum(*args, **kwargs):
        raise RuntimeError("smtp injoignable")

    monkeypatch.setattr(notify.mailer, "send_email", boum)
    recus = []
    monkeypatch.setattr(notify.channels, "broadcast", lambda s, c: recus.append(s))
    notify._send("Sujet", "Corps")
    assert recus == ["Sujet"]


def _cible_et_run(resume):
    cible = SimpleNamespace(name="Paroisse", url="https://exemple.test")
    run = SimpleNamespace(
        change_ratio=0.12, capture_date="2026-07-28", ai_summary=resume
    )
    return cible, run


def test_alerte_de_changement_contient_le_resume_ia(monkeypatch):
    envoyes = []
    monkeypatch.setattr(notify, "_send", lambda s, c: envoyes.append(c))
    cible, run = _cible_et_run("Deux nouvelles publications.")
    notify.notify_change(cible, run, run)
    assert "Deux nouvelles publications." in envoyes[0]


def test_alerte_de_changement_sans_resume(monkeypatch):
    envoyes = []
    monkeypatch.setattr(notify, "_send", lambda s, c: envoyes.append(c))
    cible, run = _cible_et_run(None)
    notify.notify_change(cible, run, run)
    mot = "R" + chr(233) + "sum" + chr(233)
    assert mot not in envoyes[0]
    assert "12.0 %" in envoyes[0]
