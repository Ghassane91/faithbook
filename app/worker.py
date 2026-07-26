from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time

from app.config import settings
from app.database import init_db
from app.models import Run, RunStatus
from sqlalchemy import select
from app.database import session_scope
from app.services import run_queue
from app.services.runner import execute_run

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


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
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
            asyncio.run(execute_run(item.run_id, force=item.force))
        except Exception:
            logger.exception("Échec non géré du run %s", item.run_id)
        finally:
            run_queue.acknowledge(item)
            run_queue.release_target(item.target_id, item.run_id)

    logger.info("Worker arrêté")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
