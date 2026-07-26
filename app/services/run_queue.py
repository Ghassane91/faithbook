from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings
from redis.exceptions import TimeoutError as RedisTimeoutError

LOCK_PREFIX = "faithbook:target-lock:"
WORKER_HEARTBEAT = "faithbook:worker-heartbeat"
PROCESSING_SUFFIX = ":processing"


@dataclass(frozen=True)
class QueuedRun:
    run_id: int
    target_id: int
    force: bool


@lru_cache
def _client():
    from redis import Redis

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        # Doit rester strictement supérieur au timeout de BRPOPLPUSH.
        # Sinon une file vide déclenche un timeout socket juste avant que
        # Redis ne rende normalement la main au worker.
        socket_timeout=15,
        health_check_interval=30,
    )


def ping() -> bool:
    try:
        return bool(_client().ping())
    except Exception:
        return False


def reserve_target(target_id: int) -> bool:
    return bool(
        _client().set(
            f"{LOCK_PREFIX}{target_id}",
            "reserved",
            nx=True,
            ex=settings.worker_lock_ttl_seconds,
        )
    )


def enqueue(item: QueuedRun) -> None:
    client = _client()
    lock_key = f"{LOCK_PREFIX}{item.target_id}"
    payload = _payload(item)
    pipe = client.pipeline(transaction=True)
    pipe.set(lock_key, str(item.run_id), xx=True, ex=settings.worker_lock_ttl_seconds)
    pipe.rpush(settings.queue_name, payload)
    updated, _ = pipe.execute()
    if not updated:
        raise RuntimeError("Réservation Redis perdue avant la mise en file.")


def release_target(target_id: int, run_id: int | None = None) -> None:
    client = _client()
    key = f"{LOCK_PREFIX}{target_id}"
    if run_id is None:
        client.delete(key)
        return
    client.eval(
        """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """,
        1,
        key,
        str(run_id),
    )


def _payload(item: QueuedRun) -> str:
    return json.dumps(
        {"run_id": item.run_id, "target_id": item.target_id, "force": item.force},
        separators=(",", ":"),
        sort_keys=True,
    )


def dequeue(timeout: int = 5) -> QueuedRun | None:
    try:
        raw = _client().brpoplpush(
            settings.queue_name,
            f"{settings.queue_name}{PROCESSING_SUFFIX}",
            timeout=timeout,
        )
    except RedisTimeoutError:
        # Une expiration de lecture pendant l'attente d'un message ne doit
        # jamais tuer le worker. Le heartbeat signale séparément une vraie
        # indisponibilité Redis.
        return None
    if not raw:
        return None
    data = json.loads(raw)
    return QueuedRun(
        run_id=int(data["run_id"]),
        target_id=int(data["target_id"]),
        force=bool(data.get("force", False)),
    )


def acknowledge(item: QueuedRun) -> None:
    _client().lrem(
        f"{settings.queue_name}{PROCESSING_SUFFIX}",
        1,
        _payload(item),
    )


def recover_processing() -> int:
    """Remet dans la file les messages réservés par un worker interrompu."""
    client = _client()
    processing = f"{settings.queue_name}{PROCESSING_SUFFIX}"
    recovered = 0
    while client.rpoplpush(processing, settings.queue_name) is not None:
        recovered += 1
    return recovered


def queued_run_ids() -> set[int]:
    client = _client()
    payloads = client.lrange(settings.queue_name, 0, -1)
    payloads += client.lrange(
        f"{settings.queue_name}{PROCESSING_SUFFIX}", 0, -1
    )
    ids: set[int] = set()
    for raw in payloads:
        try:
            ids.add(int(json.loads(raw)["run_id"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return ids


def enqueue_recovered(item: QueuedRun) -> None:
    """Réinsère un run DB orphelin sans créer de doublon de file."""
    client = _client()
    if item.run_id in queued_run_ids():
        return
    client.set(
        f"{LOCK_PREFIX}{item.target_id}",
        str(item.run_id),
        ex=settings.worker_lock_ttl_seconds,
    )
    client.rpush(settings.queue_name, _payload(item))


def heartbeat() -> None:
    _client().set(WORKER_HEARTBEAT, str(time.time()), ex=30)


def worker_alive(max_age_seconds: int = 20) -> bool:
    try:
        raw = _client().get(WORKER_HEARTBEAT)
        return bool(raw) and time.time() - float(raw) <= max_age_seconds
    except Exception:
        return False


def queue_depth() -> int:
    try:
        return int(_client().llen(settings.queue_name))
    except Exception:
        return -1
