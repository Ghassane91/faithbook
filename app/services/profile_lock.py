from __future__ import annotations

import asyncio

# Un coffre Chromium ne peut être ouvert que par une opération à la fois.
# Les verrous restent locaux au processus ; FaithBook exécute aujourd'hui un
# seul worker API, ce qui correspond au modèle de déploiement documenté.
_locks: dict[str, asyncio.Lock] = {}


def get_profile_lock(profile_slug: str) -> asyncio.Lock:
    lock = _locks.get(profile_slug)
    if lock is None:
        lock = asyncio.Lock()
        _locks[profile_slug] = lock
    return lock
