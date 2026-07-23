"""LoginManager.authorize() — jeton noVNC + isolation entre utilisateurs.

C'est le gate applicatif verifie par nginx (auth_request) avant de relayer
vers /novnc et /websockify (Phase 1a, correctif C2 : noVNC etait auparavant
accessible sans aucune verification au niveau du proxy).

On ne lance pas de vrai navigateur ici : LoginSession est un dataclass simple,
on peut en construire un a la main pour tester uniquement la logique
d'autorisation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.login_browser import LoginManager, LoginSession


def _session(token: str, user_id: int, ttl_minutes: int = 10) -> LoginSession:
    return LoginSession(
        account_id=1,
        profile_slug="acct-test",
        platform="facebook",
        work_dir=None,  # non utilise par authorize()
        pw=None,  # non utilise par authorize()
        context=None,  # non utilise par authorize()
        started_by_user_id=user_id,
        token=token,
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )


@pytest.fixture()
def manager():
    return LoginManager()


def test_refuse_sans_session_active(manager):
    assert manager.authorize("un-jeton", user_id=1) is False


def test_refuse_sans_jeton(manager):
    manager._active = _session("le-bon-jeton", user_id=1)
    assert manager.authorize(None, user_id=1) is False
    assert manager.authorize("", user_id=1) is False


def test_accepte_jeton_et_utilisateur_corrects(manager):
    manager._active = _session("le-bon-jeton", user_id=1)
    assert manager.authorize("le-bon-jeton", user_id=1) is True


def test_refuse_mauvais_jeton(manager):
    manager._active = _session("le-bon-jeton", user_id=1)
    assert manager.authorize("un-autre-jeton", user_id=1) is False


def test_refuse_utilisateur_different():
    """Coeur de l'isolation : le compte A ne doit jamais voir l'ecran de B."""
    manager = LoginManager()
    manager._active = _session("le-bon-jeton", user_id=1)
    assert manager.authorize("le-bon-jeton", user_id=2) is False


def test_refuse_jeton_expire(manager):
    manager._active = _session("le-bon-jeton", user_id=1, ttl_minutes=-1)
    assert manager.authorize("le-bon-jeton", user_id=1) is False
