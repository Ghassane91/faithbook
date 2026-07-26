from __future__ import annotations

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError
from app.config import settings
from app.database import session_scope
from app.models import Run, RunStatus, Target, TriggerType
from app.services import run_queue, runner


@pytest.mark.asyncio
async def test_redis_met_le_run_en_file_sans_executer_dans_api(monkeypatch):
    with session_scope() as session:
        target = Target(
            name="Cible worker",
            url="https://example.com/",
            enabled=False,
            run_time="09:00",
        )
        session.add(target)
        session.commit()
        target_id = target.id

    queued: list[run_queue.QueuedRun] = []
    monkeypatch.setattr(settings, "queue_backend", "redis")
    monkeypatch.setattr(run_queue, "reserve_target", lambda _target_id: True)
    monkeypatch.setattr(run_queue, "enqueue", queued.append)

    run_id, status, detail = await runner.trigger_target(
        target_id, TriggerType.manual, force=True
    )

    assert status == RunStatus.pending
    assert "worker" in detail
    assert queued == [
        run_queue.QueuedRun(run_id=run_id, target_id=target_id, force=True)
    ]
    with session_scope() as session:
        assert session.get(Run, run_id).status == RunStatus.pending


@pytest.mark.asyncio
async def test_redis_refuse_deux_runs_simultanes(monkeypatch):
    with session_scope() as session:
        target = Target(
            name="Cible verrou Redis",
            url="https://example.com/",
            enabled=False,
            run_time="09:00",
        )
        session.add(target)
        session.commit()
        target_id = target.id

    monkeypatch.setattr(settings, "queue_backend", "redis")
    monkeypatch.setattr(run_queue, "reserve_target", lambda _target_id: False)

    with pytest.raises(RuntimeError, match="déjà en cours"):
        await runner.trigger_target(target_id, TriggerType.manual, force=True)


def test_worker_survit_a_un_timeout_redis_pendant_file_vide(monkeypatch):
    class TimedOutRedis:
        def brpoplpush(self, *_args, **_kwargs):
            raise RedisTimeoutError("Timeout reading from socket")

    monkeypatch.setattr(run_queue, "_client", lambda: TimedOutRedis())

    assert run_queue.dequeue(timeout=5) is None
