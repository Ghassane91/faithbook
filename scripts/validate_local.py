"""Validation locale complète avant livraison ou déploiement.

Usage :
    python scripts/validate_local.py
    python scripts/validate_local.py --skip-build
    python scripts/validate_local.py --smoke
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path


def run(command: list[str], project_root: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=project_root, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    run(["docker", "compose", "config", "--quiet"], root)
    if not args.skip_build:
        run(["docker", "compose", "build"], root)
    run(
        [
            "docker",
            "compose",
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "180",
        ],
        root,
    )
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "python",
            "-m",
            "pytest",
            "tests/",
            "-q",
        ],
        root,
    )

    base = f"http://127.0.0.1:{args.port}"
    with urllib.request.urlopen(f"{base}/api/health", timeout=10) as response:
        health = json.load(response)
    if health.get("status") != "ok":
        raise RuntimeError(f"Healthcheck API invalide : {health}")
    if health.get("database_backend") != "postgresql":
        raise RuntimeError(f"PostgreSQL non actif : {health}")
    if not health.get("redis_ok") or not health.get("worker_alive"):
        raise RuntimeError(f"Redis ou worker indisponible : {health}")
    with urllib.request.urlopen(base, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Frontend indisponible : HTTP {response.status}")

    if args.smoke:
        run([sys.executable, "scripts/smoke_test.py", base], root)
    print(f"VALIDATION LOCALE OK — FaithBook {health.get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
