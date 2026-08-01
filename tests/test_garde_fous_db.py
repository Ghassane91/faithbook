"""Garde-fous PostgreSQL contre les blocages de transaction.

Constate le 01/08/2026 : deux captures gardaient leur transaction ouverte,
une troisieme attendait leur verrou sans limite de temps, et la boucle du
backend est restee figee 1 h 29.
"""

from app.config import settings
from app.database import _connect_args


def test_sqlite_garde_son_reglage():
    assert _connect_args("sqlite:///./test.db") == {"check_same_thread": False}


def test_attente_de_verrou_bornee():
    options = _connect_args("postgresql+psycopg://x")["options"]
    assert "lock_timeout=10000" in options


def test_transaction_abandonnee_supprimee():
    options = _connect_args("postgresql+psycopg://x")["options"]
    assert "idle_in_transaction_session_timeout=600000" in options


def test_les_delais_suivent_les_reglages(monkeypatch):
    monkeypatch.setattr(settings, "db_lock_timeout_ms", 4321)
    monkeypatch.setattr(settings, "db_idle_tx_timeout_ms", 7654)
    options = _connect_args("postgresql+psycopg://x")["options"]
    assert "lock_timeout=4321" in options
    assert "idle_in_transaction_session_timeout=7654" in options