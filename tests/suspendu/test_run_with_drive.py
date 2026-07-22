"""Chaine complete avec STORAGE_BACKEND=google_drive, contre une API Drive simulee.

Verifie que capture -> dossier date -> sous-dossier -> upload -> journalisation
fonctionne de bout en bout, et que la deduplication evite un second envoi.

Usage :  docker exec -w /app capture-backend python3 tests/test_run_with_drive.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Base et captures isolees : ce test ne touche pas aux donnees reelles.
_TMP = tempfile.mkdtemp(prefix="drive-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SCREENSHOT_DIR"] = f"{_TMP}/screenshots"
os.environ["STORAGE_BACKEND"] = "google_drive"

from app.config import settings  # noqa: E402
from app.database import create_all_for_tests as init_db  # noqa: E402
from app.database import session_scope  # noqa: E402
from app.models import Run, RunStatus, Target, TriggerType  # noqa: E402
from app.services import drive as drive_module  # noqa: E402
from app.services.runner import execute_run, local_now  # noqa: E402
from test_drive import FakeFiles, FakeService  # noqa: E402

CHECKS: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{label} : {detail}")
    print(f"  OK  {label}")
    CHECKS.append(label)


async def main() -> int:
    print("\n=== Chaine complete capture -> Drive (API simulee) ===\n")

    settings.google_drive_parent_folder_id = "PARENT"
    settings.storage_backend = "google_drive"

    fake = FakeFiles()
    drive_module.drive_client._service = FakeService(fake)
    drive_module.drive_client.is_configured = lambda: True  # court-circuite les credentials

    init_db()

    with session_scope() as session:
        target = Target(
            name="Test Drive",
            url="https://example.com",
            run_time="09:00",
            wait_until="load",
            wait_after_load_ms=300,
            subfolder="rapports",
        )
        session.add(target)
        session.commit()
        session.refresh(target)
        target_id = target.id
        today = local_now(target).strftime(settings.folder_date_format)

        run = Run(
            target_id=target_id,
            trigger=TriggerType.manual,
            capture_date=local_now(target).strftime("%Y-%m-%d"),
            status=RunStatus.pending,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    await execute_run(run_id)

    with session_scope() as session:
        run = session.get(Run, run_id)
        logs = [(entry.step, entry.message) for entry in run.logs]

        check("Execution reussie", run.status == RunStatus.success, str(run.error_message))
        check("Capture produite", (run.screenshot_bytes or 0) > 1000, str(run.screenshot_bytes))
        check("Identifiant de fichier Drive enregistre", bool(run.drive_file_id), "vide")
        check("Lien Drive enregistre", bool(run.drive_file_link), "vide")
        check("Dossier Drive enregistre", bool(run.drive_folder_id), "vide")

        folders = {f["name"]: fid for fid, f in fake.store.items() if f["mimeType"].endswith("folder")}
        check(
            f"Dossier date '{today}' cree",
            today in folders,
            f"dossiers presents : {list(folders)}",
        )
        check("Sous-dossier 'rapports' cree", "rapports" in folders, str(list(folders)))
        check(
            "Sous-dossier place dans le dossier date",
            fake.store[folders["rapports"]]["parents"] == [folders[today]],
            str(fake.store[folders["rapports"]]["parents"]),
        )
        check(
            "Capture placee dans le sous-dossier",
            run.drive_folder_id == folders["rapports"],
            f"{run.drive_folder_id} != {folders['rapports']}",
        )

        png = [f for f in fake.store.values() if f["mimeType"] == "image/png"]
        check("Un seul fichier envoye", len(png) == 1, f"{len(png)} fichiers")
        check(
            "Nom de fichier date et lisible",
            png[0]["name"].startswith(run.capture_date) and png[0]["name"].endswith(".png"),
            png[0]["name"],
        )
        check(
            "Etapes journalisees",
            {"start", "capture", "drive", "upload", "done"} <= {s for s, _ in logs},
            str([s for s, _ in logs]),
        )

    # Deuxieme execution le meme jour : deduplication, aucun nouvel envoi
    with session_scope() as session:
        target = session.get(Target, target_id)
        run2 = Run(
            target_id=target_id,
            trigger=TriggerType.manual,
            capture_date=local_now(target).strftime("%Y-%m-%d"),
            status=RunStatus.pending,
        )
        session.add(run2)
        session.commit()
        session.refresh(run2)
        run2_id = run2.id

    await execute_run(run2_id)

    with session_scope() as session:
        run2 = session.get(Run, run2_id)
        png = [f for f in fake.store.values() if f["mimeType"] == "image/png"]
        check("Seconde execution ignoree", run2.status == RunStatus.skipped, str(run2.status))
        check("Motif d'exclusion renseigne", bool(run2.skipped_reason), "vide")
        check("Toujours un seul fichier sur Drive", len(png) == 1, f"{len(png)} fichiers")
        check(
            "Lien Drive repris de la premiere execution",
            bool(run2.drive_file_link),
            "le frontend n'aurait aucun lien a afficher",
        )

    print(f"\nTOUS LES TESTS PASSES ({len(CHECKS)} verifications)\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as exc:
        print(f"\nECHEC : {exc}\n")
        sys.exit(1)
