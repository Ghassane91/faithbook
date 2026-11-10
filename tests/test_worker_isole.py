"""Le worker execute chaque run dans un processus separe ; s'il meurt, le run
ne doit pas rester « running »."""

from __future__ import annotations

import signal
from unittest.mock import MagicMock

from app import worker
from app.database import session_scope
from app.models import Run, RunStatus, Target, TriggerType


def _run_en_cours() -> int:
    with session_scope() as session:
        target = Target(name="Cible isolee", url="https://example.com/isole")
        session.add(target)
        session.flush()
        run = Run(
            target_id=target.id,
            capture_date="2026-11-10",
            trigger=TriggerType.manual,
            status=RunStatus.running,
        )
        session.add(run)
        session.flush()
        return run.id


def test_processus_tue_marque_le_run_en_echec(monkeypatch):
    run_id = _run_en_cours()
    notifie = MagicMock()
    monkeypatch.setattr(worker, "notify_failure", notifie)

    worker._marquer_interrompu(run_id, -signal.SIGKILL)

    with session_scope() as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.failed
        assert "faute de mémoire" in run.error_message
        assert run.finished_at is not None
    notifie.assert_called_once()


def test_run_deja_termine_est_laisse_tel_quel(monkeypatch):
    run_id = _run_en_cours()
    with session_scope() as session:
        session.get(Run, run_id).status = RunStatus.success
    notifie = MagicMock()
    monkeypatch.setattr(worker, "notify_failure", notifie)

    worker._marquer_interrompu(run_id, 1)

    with session_scope() as session:
        assert session.get(Run, run_id).status == RunStatus.success
    notifie.assert_not_called()


def test_executer_isole_passe_par_un_processus_enfant(monkeypatch):
    """On ne lance pas un vrai spawn (Chromium, base...) : on verifie le
    cablage — Process(target=_executer_run), start, join, et l'appel de
    _marquer_interrompu sur un code de sortie non nul."""
    processus = MagicMock()
    processus.exitcode = 137
    contexte = MagicMock()
    contexte.Process.return_value = processus
    monkeypatch.setattr(worker.multiprocessing, "get_context", lambda *_: contexte)
    marque = MagicMock()
    monkeypatch.setattr(worker, "_marquer_interrompu", marque)

    worker.executer_isole(42, True)

    contexte.Process.assert_called_once()
    assert contexte.Process.call_args.kwargs["target"] is worker._executer_run
    assert contexte.Process.call_args.kwargs["args"] == (42, True)
    processus.start.assert_called_once()
    processus.join.assert_called_once()
    marque.assert_called_once_with(42, 137)


def test_executer_isole_sortie_normale_ne_marque_rien(monkeypatch):
    processus = MagicMock()
    processus.exitcode = 0
    contexte = MagicMock()
    contexte.Process.return_value = processus
    monkeypatch.setattr(worker.multiprocessing, "get_context", lambda *_: contexte)
    marque = MagicMock()
    monkeypatch.setattr(worker, "_marquer_interrompu", marque)

    worker.executer_isole(7, False)

    marque.assert_not_called()
