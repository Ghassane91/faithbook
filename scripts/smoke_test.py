"""Test de bout en bout du backend : authentification, creation d'une cible,
capture manuelle, verification du statut, des logs et du PNG produit.

Usage :  python scripts/smoke_test.py [base_url] [email] [mot_de_passe]
Par defaut, utilise la cle API si API_KEY est fournie dans l'environnement.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SMOKE_EMAIL", "admin@local")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("SMOKE_PASSWORD", "")
API_KEY = os.environ.get("API_KEY", "")
TIMEOUT = 120


def authentifier(client: httpx.Client) -> None:
    """Ouvre une session. La cle API a la priorite (scripts, CI)."""
    if API_KEY:
        client.headers["X-API-Key"] = API_KEY
        print("[0] Auth             : cle API")
        return
    if not PASSWORD:
        raise SystemExit(
            "Aucun identifiant. Fournissez API_KEY, ou SMOKE_PASSWORD / l'argument mot de passe."
        )
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    print(f"[0] Auth             : session pour {EMAIL}")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30)

    # Sans authentification, l'API doit refuser.
    assert client.get("/api/targets").status_code == 401, "l'API devrait exiger une connexion"
    authentifier(client)

    health = client.get("/api/health").json()
    print(f"[1] Sante            : {health}")
    assert health["status"] == "ok"
    assert health["scheduler_running"] is True

    payload = {
        "name": "Smoke test example.com",
        "url": "https://example.com",
        "run_time": "23:59",
        "wait_until": "load",
        "wait_after_load_ms": 500,
    }
    resp = client.post("/api/targets", json=payload)
    resp.raise_for_status()
    target = resp.json()
    target_id = target["id"]
    print(f"[2] Cible creee      : #{target_id} prochaine execution {target['next_run_at']}")
    assert target["next_run_at"] is not None, "la cible doit etre planifiee"

    jobs = client.get("/api/scheduler/jobs").json()
    assert any(j["target_id"] == target_id for j in jobs), "job absent du planificateur"
    print(f"[3] Planificateur    : {len(jobs)} tache(s)")

    run_id = client.post(f"/api/targets/{target_id}/run").json()["run_id"]
    print(f"[4] Capture lancee   : run #{run_id}")

    deadline = time.time() + TIMEOUT
    run = {}
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("success", "failed", "skipped"):
            break
        time.sleep(2)

    print(f"[5] Statut final     : {run['status']} en {run['duration_ms']} ms")
    for entry in run["logs"]:
        print(f"      - [{entry['step']:<8}] {entry['message']}")
    assert run["status"] == "success", f"echec : {run.get('error_message')}"
    assert run["screenshot_bytes"] > 1000, "capture anormalement petite"
    assert run["content_sha256"], "hash de contenu manquant"

    png = client.get(f"/api/runs/{run_id}/screenshot")
    png.raise_for_status()
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n", "le fichier n'est pas un PNG"
    print(f"[6] PNG telecharge   : {len(png.content)} octets, titre='{run['page_title']}'")

    # Le fichier doit etre range dans un dossier date
    assert run["capture_date"] in run["screenshot_path"], (
        f"capture hors du dossier date : {run['screenshot_path']}"
    )
    print(f"      range dans      : {run['screenshot_path']}")

    # Deduplication : une 2e execution le meme jour doit etre ignoree
    second = client.post(f"/api/targets/{target_id}/run").json()
    print(f"[7] Doublon          : {second['status']} - {second['detail']}")
    assert second["status"] == "skipped", "la deduplication n'a pas fonctionne"

    # force=true doit passer outre
    forced = client.post(f"/api/targets/{target_id}/run", params={"force": True}).json()
    print(f"[8] force=true       : run #{forced['run_id']} {forced['status']}")
    assert forced["status"] == "pending"

    # Retry : une URL qui echoue TOUJOURS a la capture doit echouer proprement
    # apres plusieurs tentatives. Domaine reel (passe le garde anti-SSRF, actif
    # depuis la Phase 1a), port ferme (echec de connexion garanti a l'ouverture
    # de la page) : on teste le mecanisme de reessai, pas la resolution DNS.
    bad = client.post(
        "/api/targets",
        json={
            "name": "Smoke test port ferme",
            "url": "https://example.com:8443/",
            "run_time": "23:58",
            "timeout_ms": 5000,
        },
    ).json()
    bad_run = client.post(f"/api/targets/{bad['id']}/run").json()["run_id"]
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        r = client.get(f"/api/runs/{bad_run}").json()
        if r["status"] in ("success", "failed", "skipped"):
            break
        time.sleep(3)
    print(f"[9] Gestion d'erreur : {r['status']} apres {r['attempts']} tentative(s)")
    assert r["status"] == "failed"
    assert r["attempts"] >= 2, "le mecanisme de reessai ne s'est pas declenche"
    assert r["error_message"]

    # Nettoyage
    client.delete(f"/api/targets/{target_id}")
    client.delete(f"/api/targets/{bad['id']}")
    print("\nTOUS LES TESTS SONT PASSES")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\nECHEC : {exc}")
        sys.exit(1)
