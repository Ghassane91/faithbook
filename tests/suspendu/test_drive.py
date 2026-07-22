"""Valide toute la logique Google Drive contre une API simulee.

Ce test ne demande aucun credential : il verifie que les bonnes requetes sont
envoyees a l'API Drive (creation du dossier date, reutilisation d'un dossier
existant, sous-dossier, anti-doublon, Drive partage, echappement des noms).
Seule l'authentification reelle reste a valider avec un vrai compte de service.

Usage :  docker exec -w /app capture-backend python3 tests/test_drive.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import settings  # noqa: E402
from app.services.drive import FOLDER_MIME, DriveClient  # noqa: E402

# L'alternative echappee doit etre testee AVANT [^'], sinon l'antislash est
# consomme par [^'] et l'apostrophe suivante ferme la valeur trop tot.
NAME_RE = re.compile(r"name = '((?:\\.|[^'\\])*)'")
PARENT_RE = re.compile(r"'([^']+)' in parents")


def _unescape(value: str) -> str:
    """Inverse de escape_query_value : \\' -> ' et \\\\ -> \\."""
    return value.replace("\\\\", "\x00").replace("\\'", "'").replace("\x00", "\\")


class FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeFiles:
    """Reproduit la partie de l'API Drive utilisee par DriveClient."""

    def __init__(self):
        self.store: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self._next_id = 1

    def _new_id(self) -> str:
        fid = f"id-{self._next_id}"
        self._next_id += 1
        return fid

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        q = kwargs.get("q", "")
        name_match = NAME_RE.search(q)
        parent_match = PARENT_RE.search(q)
        name = _unescape(name_match.group(1)) if name_match else None
        parent = parent_match.group(1) if parent_match else None
        want_folder = FOLDER_MIME in q

        hits = [
            {"id": fid, "name": f["name"], "webViewLink": f.get("webViewLink", "")}
            for fid, f in self.store.items()
            if f["name"] == name
            and parent in f["parents"]
            and (f["mimeType"] == FOLDER_MIME) == want_folder
        ]
        return FakeExecute({"files": hits})

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        body = kwargs["body"]
        fid = self._new_id()
        self.store[fid] = {
            "name": body["name"],
            "parents": body.get("parents", []),
            "mimeType": body.get("mimeType", "image/png"),
            "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
        }
        return FakeExecute({"id": fid, "webViewLink": self.store[fid]["webViewLink"]})

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        fid = kwargs["fileId"]
        if fid not in self.store:
            raise RuntimeError(f"File not found: {fid}")
        f = self.store[fid]
        return FakeExecute({"id": fid, "name": f["name"], "mimeType": f["mimeType"]})


class FakeService:
    def __init__(self, files: FakeFiles):
        self._files = files

    def files(self):
        return self._files


def build_client(shared_drive: str = "") -> tuple[DriveClient, FakeFiles]:
    settings.google_drive_parent_folder_id = "PARENT"
    settings.google_drive_shared_drive_id = shared_drive
    fake = FakeFiles()
    client = DriveClient()
    client._service = FakeService(fake)  # court-circuite l'authentification
    return client, fake


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{label} : {detail}")
    print(f"  OK  {label}")


def main() -> int:
    print("\n=== Logique Google Drive (API simulee) ===\n")

    # 1. Creation du dossier date
    client, fake = build_client()
    folder_id = client.ensure_folder("2026-07-20")
    created = [c for c in fake.calls if c[0] == "create"]
    check("Dossier du jour cree", len(created) == 1, f"{len(created)} creations")
    check(
        "Cree comme dossier sous le parent configure",
        created[0][1]["body"]["mimeType"] == FOLDER_MIME
        and created[0][1]["body"]["parents"] == ["PARENT"],
        str(created[0][1]["body"]),
    )

    # 2. Deuxieme appel : le dossier existant est reutilise, pas recree
    again = client.ensure_folder("2026-07-20")
    check("Meme dossier reutilise le lendemain", again == folder_id, f"{again} != {folder_id}")
    check(
        "Aucun dossier duplique",
        len([c for c in fake.calls if c[0] == "create"]) == 1,
        "un second dossier a ete cree",
    )

    # 3. Sous-dossier par cible
    sub_id = client.ensure_folder("rapports", folder_id)
    check("Sous-dossier cree dans le dossier du jour", sub_id != folder_id)
    sub_create = [c for c in fake.calls if c[0] == "create"][-1]
    check(
        "Sous-dossier rattache au bon parent",
        sub_create[1]["body"]["parents"] == [folder_id],
        str(sub_create[1]["body"]["parents"]),
    )

    # 4. Upload d'une capture
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "2026-07-20_page_090012.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 512)

        result = client.upload(png, folder_id)
        check("Capture televersee", result.file_id.startswith("id-"), result.file_id)
        check("Lien de partage retourne", result.web_link.startswith("https://"), result.web_link)
        check("Premier envoi non marque comme doublon", result.deduplicated is False)

        upload_call = [c for c in fake.calls if c[0] == "create"][-1]
        check(
            "Fichier place dans le dossier du jour",
            upload_call[1]["body"]["parents"] == [folder_id],
            str(upload_call[1]["body"]["parents"]),
        )
        check(
            "supportsAllDrives transmis",
            upload_call[1].get("supportsAllDrives") is True,
            "parametre absent : echouerait sur un Drive partage",
        )

        # 5. Anti-doublon : meme nom, meme dossier
        before = len([c for c in fake.calls if c[0] == "create"])
        second = client.upload(png, folder_id)
        after = len([c for c in fake.calls if c[0] == "create"])
        check("Doublon detecte", second.deduplicated is True)
        check("Aucun second envoi", before == after, f"{after - before} envoi(s) en trop")
        check("Fichier existant reutilise", second.file_id == result.file_id)

        # 6. Meme nom mais autre jour : ce n'est pas un doublon
        other_day = client.ensure_folder("2026-07-21")
        third = client.upload(png, other_day)
        check("Capture du lendemain envoyee normalement", third.deduplicated is False)
        check("Identifiant different du jour precedent", third.file_id != result.file_id)

        # 7. Noms contenant une apostrophe (ex. sous-dossier "L'agence")
        client2, fake2 = build_client()
        quoted = client2.ensure_folder("L'agence")
        check("Nom avec apostrophe accepte", quoted.startswith("id-"), quoted)
        reused = client2.ensure_folder("L'agence")
        check(
            "Nom avec apostrophe correctement echappe",
            reused == quoted,
            "un doublon serait cree a chaque execution",
        )

        # 7bis. Nom contenant un antislash (doit etre echappe avant l'apostrophe)
        tricky = client2.ensure_folder("dossier\\test")
        check("Nom avec antislash accepte", tricky.startswith("id-"), tricky)
        check(
            "Nom avec antislash correctement echappe",
            client2.ensure_folder("dossier\\test") == tricky,
            "un doublon serait cree a chaque execution",
        )

        # 8. Drive partage
        client3, fake3 = build_client(shared_drive="DRIVE123")
        client3.ensure_folder("2026-07-20")
        list_call = next(c for c in fake3.calls if c[0] == "list")
        check(
            "Drive partage : corpora et driveId transmis",
            list_call[1].get("corpora") == "drive"
            and list_call[1].get("driveId") == "DRIVE123",
            str(list_call[1]),
        )
        check(
            "Drive partage : includeItemsFromAllDrives actif",
            list_call[1].get("includeItemsFromAllDrives") is True,
            str(list_call[1]),
        )

    # 9. Verification d'acces au dossier parent
    client4, fake4 = build_client()
    fake4.store["PARENT"] = {
        "name": "Captures",
        "parents": [],
        "mimeType": FOLDER_MIME,
        "webViewLink": "",
    }
    meta = client4.check_access()
    check("check_access retourne le dossier parent", meta["name"] == "Captures", str(meta))

    print("\nTOUS LES TESTS DRIVE SONT PASSES")
    print("Reste a valider avec de vrais identifiants : authentification et permissions.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\nECHEC : {exc}\n")
        sys.exit(1)
