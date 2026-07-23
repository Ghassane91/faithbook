"""app/services/audit.py — le journal d'audit ecrit bien ce qu'on lui donne.

Phase 1a a etendu l'audit a des points qui en etaient completement depourvus
(connexion/deconnexion, mot de passe, cibles, abandon de connexion noVNC).
Ce test ne verifie pas ces points d'appel un par un (ce serait un test
d'integration par route) mais la garantie commune : une action enregistree
est bien lisible ensuite, et ne contient jamais le detail sensible qu'on ne
lui a pas donne.
"""

from __future__ import annotations

from app.database import session_scope
from app.models import User
from app.services import audit


def test_record_et_relecture(user):
    email, _password = user
    with session_scope() as session:
        u = session.query(User).filter_by(email=email).one()
        audit.record(session, "test.action", user=u, detail="detail sans secret", ip="1.2.3.4")

    with session_scope() as session:
        entries = audit.recent(session, limit=5)
        assert any(e.action == "test.action" and e.detail == "detail sans secret" for e in entries)


def test_record_sans_utilisateur():
    with session_scope() as session:
        audit.record(session, "test.anonyme", user=None, detail="tentative", ip="9.9.9.9")

    with session_scope() as session:
        entries = audit.recent(session, limit=5)
        entry = next(e for e in entries if e.action == "test.anonyme")
        assert entry.user_id is None
        assert entry.user_email is None
