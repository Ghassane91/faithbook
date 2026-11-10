from __future__ import annotations

import asyncio
import logging
import multiprocessing
import signal
import threading
import time

from app.config import settings
from app.database import init_db
from app.models import Run, RunStatus, Target, utcnow
from sqlalchemy import select
from app.database import session_scope
from app.services import run_queue
from app.services.notify import notify_failure
from app.services.runner import execute_run, log_step

logger = logging.getLogger("faithbook.worker")
_stopping = False


def _stop(_signum, _frame) -> None:
    global _stopping
    _stopping = True


def _heartbeat_loop() -> None:
    while not _stopping:
        try:
            run_queue.heartbeat()
        except Exception:
            logger.exception("Heartbeat Redis impossible")
        time.sleep(10)


def _configurer_journal() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )


def _executer_run(run_id: int, force: bool) -> None:
    """Point d'entree du processus enfant : une capture, puis on quitte."""
    _configurer_journal()
    asyncio.run(execute_run(run_id, force=force))


def _marquer_interrompu(run_id: int, code: int) -> None:
    """Le processus enfant est mort sans terminer le run (crash, manque de
    memoire) : sans cela le run resterait « running » jusqu'au prochain
    redemarrage du worker."""
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None or run.status not in (RunStatus.pending, RunStatus.running):
            return
        cause = " (probablement tué faute de mémoire)" if code == -signal.SIGKILL else ""
        run.status = RunStatus.failed
        run.error_message = f"Processus de capture interrompu, code {code}{cause}"
        run.finished_at = utcnow()
        session.commit()
        log_step(session, run, "failed", run.error_message, level="ERROR")
        target = session.get(Target, run.target_id)
        if target is not None:
            notify_failure(target, run)


def executer_isole(run_id: int, force: bool) -> None:
    """Execute un run dans un processus separe, qui se termine a la fin.

    Une capture pleine page manipule des images de plusieurs centaines de Mo.
    Python libere cette memoire mais la garde pour lui (fragmentation de
    l'allocateur) : un worker de longue duree finissait a ~1,5 Go au repos.
    Un processus qui se termine rend tout au systeme. « spawn » plutot que
    « fork » : l'enfant repart d'un interpreteur neuf, sans heriter des
    connexions SQL/Redis ni du thread de heartbeat du parent.
    """
    processus = multiprocessing.get_context("spawn").Process(
        target=_executer_run, args=(run_id, force), name=f"faithbook-run-{run_id}"
    )
    processus.start()
    processus.join()
    if processus.exitcode:
        logger.error("Processus du run %s termine avec le code %s", run_id, processus.exitcode)
        _marquer_interrompu(run_id, processus.exitcode)


def main() -> int:
    _configurer_journal()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    init_db()
    recovered = run_queue.recover_processing()
    queued_ids = run_queue.queued_run_ids()
    with session_scope() as session:
        orphaned = session.scalars(
            select(Run).where(Run.status.in_([RunStatus.pending, RunStatus.running]))
        ).all()
        for run in orphaned:
            # Paid provider reservations must never be requeued as Chrome captures.
            if (run.idempotency_key or '').startswith('brightdata:'):
                continue
            if run.id not in queued_ids:
                run.status = RunStatus.pending
                run_queue.enqueue_recovered(
                    run_queue.QueuedRun(
                        run_id=run.id,
                        target_id=run.target_id,
                        force=False,
                    )
                )
                recovered += 1
    logger.info("Worker démarré, file=%s", settings.queue_name)
    if recovered:
        logger.warning("%s message(s) interrompu(s) remis en file", recovered)
    threading.Thread(target=_heartbeat_loop, daemon=True).start()

    while not _stopping:
        item = run_queue.dequeue(timeout=5)
        if item is None:
            continue
        try:
            with session_scope() as session:
                run = session.get(Run, item.run_id)
                if run is None or run.status not in (
                    RunStatus.pending,
                    RunStatus.running,
                ):
                    logger.warning(
                        "Run %s absent ou non pending, message ignoré", item.run_id
                    )
                    continue
            executer_isole(item.run_id, item.force)
        except Exception:
            logger.exception("Échec non géré du run %s", item.run_id)
        finally:
            run_queue.acknowledge(item)
            run_queue.release_target(item.target_id, item.run_id)

    logger.info("Worker arrêté")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
