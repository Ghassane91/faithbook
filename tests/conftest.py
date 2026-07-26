"""Configuration pytest partagee.

IMPORTANT : les variables d'environnement ci-dessous doivent etre fixees
AVANT le premier `import app...` du process (pydantic-settings et les
singletons `engine`/`SessionLocal` sont evalues a l'import). Elles isolent
totalement les tests de la base et des fichiers reels du conteneur
(`/data/app.db`, `/data/.session_key`, `/data/profiles/`).
"""

from __future__ import annotations

import os
import socket
import tempfile

from cryptography.fernet import Fernet

_TEST_DIR = tempfile.mkdtemp(prefix="faithbook-tests-")

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/test.db"
os.environ["DATA_DIR"] = _TEST_DIR
os.environ["SCREENSHOT_DIR"] = os.path.join(_TEST_DIR, "screenshots")
os.environ["PROFILE_WORK_DIR"] = os.path.join(_TEST_DIR, "profile-work")
os.environ["SESSION_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
os.environ["LOG_FILE"] = os.path.join(_TEST_DIR, "app.log")
# Le mode par defaut (ALLOWED_DOMAINS vide, ALLOW_PRIVATE_TARGETS=false) est
# celui qui doit etre teste : ne pas laisser un .env local le changer.
os.environ["ALLOWED_DOMAINS"] = ""
os.environ["ALLOW_PRIVATE_TARGETS"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _lifespan():
    """Declenche le vrai lifespan de l'application (comme en production) pour
    toute la session de tests : migrations Alembic (contre la base de test,
    valide au passage la migration b3d4e5f6a7c8 sur une base vierge) et
    demarrage du planificateur APScheduler.

    Necessaire : schedule_target() (appele par POST/PATCH /api/targets) lit
    next_run_time sur le job APScheduler, qui n'existe que si le scheduler
    tourne dans une boucle asyncio active — ce que seul le lifespan ASGI
    fournit (AsyncIOScheduler.start() exige `asyncio.get_running_loop()`).
    Un TestClient utilise hors `with` ne declenche PAS le lifespan ; il est
    donc garde ouvert ici pour toute la session, et reutilise nulle part
    ailleurs (chaque test cree ses propres TestClient/cookies isoles).
    """
    with TestClient(app):
        yield
    engine.dispose()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def user():
    """Cree un utilisateur de test directement en base (aucun hachage reel a
    deviner) et retourne (email, password)."""
    from app.database import session_scope
    from app.services import auth

    email = "test@example.com"
    password = "Mot2Passe-Test-Solide"
    with session_scope() as session:
        from app.models import User

        existing = session.query(User).filter_by(email=email).first()
        if existing is None:
            session.add(User(email=email, password_hash=auth.hash_password(password)))
    return email, password


@pytest.fixture()
def auth_client(client, user):
    """TestClient deja connecte (cookie de session valide)."""
    email, password = user
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture()
def public_example_dns(monkeypatch):
    """DNS deterministe : les tests ne dependent pas de l'acces Internet."""
    original = socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        if host == "example.com":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))
            ]
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
