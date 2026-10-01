"""Capture des fiches produit liees depuis un tableau (ex. HuntX > Cameras).

Chaque ligne du tableau HuntX est un produit (marque + modele) et chaque
colonne marketplace contient un lien vers la fiche produit chez ce marchand.
Apres la capture du tableau, FaithBook ouvre chacun de ces liens et range la
capture sur Drive, par marketplace :

    <dossier parent>/HuntX - fiches produit/<date>/<Marketplace>/<Marque - Modele>.jpg

Le traitement dure longtemps (plusieurs centaines de pages) : il tourne dans
un processus separe, lance par le runner, pour ne pas bloquer les autres
captures. Les pages sont ouvertes sans aucune session : les fiches produit
sont publiques, et les cookies HuntX ne doivent jamais partir chez un marchand.

Execution directe : python -m app.services.fiches_liens <fichier.json>
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings
from app.services.web_challenges import WebChallenge, detect_challenge

logger = logging.getLogger(__name__)

DOSSIER_RACINE = "HuntX - fiches produit"
DOSSIER_LIGNES = "HuntX - lignes par camera"

# Lit le tableau : une entree par lien externe, avec la colonne d'origine.
JS_LIENS = r"""
() => {
  const table = [...document.querySelectorAll('table')]
    .find(t => t.querySelector('tbody tr[data-id]'));
  if (!table) return [];
  const heads = [...table.querySelectorAll('thead tr:last-child th')]
    .map(th => th.innerText.replace(/[▲▼↑↓]/g, '').trim());
  const sortie = [];
  for (const tr of table.querySelectorAll('tbody tr[data-id]')) {
    const cells = [...tr.children];
    const marque = (cells[0]?.innerText || '').trim();
    const modele = (cells[1]?.innerText || '').trim().split('\n')[0];
    cells.forEach((td, i) => {
      const a = td.querySelector('a[href^="http"]');
      if (!a || a.hostname === location.hostname) return;
      sortie.push({id: tr.dataset.id, marque, modele, colonne: heads[i] || '', url: a.href});
    });
  }
  return sortie;
}
"""

# Libelles lisibles pour les dossiers Drive.
NOMS_MARKETPLACE = {
    "BRAND": "Site de la marque",
    "ACADEMY": "Academy",
    "BASSPRO/CAB": "Bass Pro - Cabela's",
    "WALMART": "Walmart",
    "AMAZON": "Amazon",
}

# Domaine -> marketplace (l'ordre compte : premier fragment trouve).
MARKETPLACES_PAR_DOMAINE = (
    ("amazon.", "Amazon"),
    ("walmart.", "Walmart"),
    ("academy.com", "Academy"),
    ("basspro.", "Bass Pro - Cabela's"),
    ("cabelas.", "Bass Pro - Cabela's"),
)

@dataclass(frozen=True)
class Lien:
    marque: str
    modele: str
    colonne: str
    url: str

    @property
    def marketplace(self) -> str:
        # L'adresse fait foi, pas la colonne : HuntX contient des liens saisis
        # a la main, parfois dans la mauvaise colonne (un lien Bass Pro dans
        # la colonne Amazon). La colonne ne sert qu'en dernier recours.
        hote = (urlparse(self.url).hostname or "").lower()
        for fragment, nom in MARKETPLACES_PAR_DOMAINE:
            if fragment in hote:
                return nom
        cle = self.colonne.strip().upper()
        if cle == "BRAND" or not cle:
            return "Site de la marque"
        return NOMS_MARKETPLACE.get(cle) or self.colonne.strip().title()

    @property
    def nom_fichier(self) -> str:
        return nettoyer(f"{self.marque} - {self.modele}") + ".jpg"


def nettoyer(texte: str, limite: int = 120) -> str:
    """Nom de fichier sur : sans caracteres interdits, espaces normalises."""
    texte = unicodedata.normalize("NFKC", texte or "")
    texte = re.sub(r'[\\/:*?"<>|\t\r\n]+', " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip(" .")
    return texte[:limite] or "sans-nom"


def depuis_json(donnees: list[dict]) -> list[Lien]:
    """Liens valides et dedoublonnes (meme marketplace + meme fichier)."""
    vus: set[tuple[str, str]] = set()
    urls: set[str] = set()
    liens: list[Lien] = []
    for d in donnees or []:
        url = str(d.get("url") or "")
        if urlparse(url).scheme not in ("http", "https"):
            continue
        lien = Lien(
            marque=str(d.get("marque") or ""), modele=str(d.get("modele") or ""),
            colonne=str(d.get("colonne") or ""), url=url,
        )
        cle = (lien.marketplace, lien.nom_fichier)
        if cle in vus or url in urls:  # meme page listee deux fois : une capture suffit
            continue
        vus.add(cle)
        urls.add(url)
        liens.append(lien)
    return liens


def marketplaces_ignorees() -> set[str]:
    brut = getattr(settings, "fiches_marketplaces_ignorees", "") or ""
    return {m.strip().casefold() for m in brut.split(",") if m.strip()}


def est_bloquee(texte: str | None) -> bool:
    contenu = texte or ""
    if len(contenu.strip()) < 300:
        return True
    # Une notice reCAPTCHA dans le pied de page n'est pas un interstitiel.
    return detect_challenge("", contenu) is not None


async def capturer_lignes(page, dossier: Path) -> list[dict]:
    """Une image par ligne du tableau : en-tete des colonnes + la ligne.

    Les prix de chaque marketplace sont ceux affiches par HuntX : aucune
    visite chez les marchands, donc aucun blocage possible. Ne leve jamais.
    """
    from io import BytesIO

    from PIL import Image

    lignes: list[dict] = []
    try:
        table = page.locator("table:has(tbody tr[data-id])").first
        if await table.count() == 0:
            return lignes
        dossier.mkdir(parents=True, exist_ok=True)
        entete = Image.open(BytesIO(await table.locator("thead").screenshot(type="png"))).convert("RGB")
        vus: set[str] = set()
        rangees = table.locator("tbody tr[data-id]")
        for i in range(await rangees.count()):
            rangee = rangees.nth(i)
            cellules = rangee.locator("td")
            marque = (await cellules.nth(0).inner_text()).strip()
            modele = (await cellules.nth(1).inner_text()).strip().split("\n")[0]
            nom = nettoyer(f"{marque} - {modele}") + ".jpg"
            if nom in vus:
                continue
            vus.add(nom)
            await rangee.scroll_into_view_if_needed()
            image = Image.open(BytesIO(await rangee.screenshot(type="png"))).convert("RGB")
            largeur = max(entete.width, image.width)
            composee = Image.new("RGB", (largeur, entete.height + image.height), (0, 0, 0))
            composee.paste(entete, (0, 0))
            composee.paste(image, (0, entete.height))
            chemin = dossier / f"ligne-{i:04d}.jpg"
            composee.save(chemin, "JPEG", quality=85)
            lignes.append({"fichier": str(chemin), "nom": nom})
    except Exception:  # noqa: BLE001 - la capture principale reste valable
        logger.warning("Images par ligne impossibles (%d faites)", len(lignes), exc_info=True)
    return lignes


def envoyer_lignes(lignes: list[dict], capture_date: str, run_id: int | None = None) -> int:
    """Envoie les images de lignes sur Drive, puis les efface du disque."""
    from app.services.drive import drive_client

    if not lignes or not drive_client.is_configured():
        return 0
    racine = drive_client.ensure_folder(DOSSIER_LIGNES, settings.google_drive_parent_folder_id or None)
    jour = drive_client.ensure_folder(capture_date, racine)
    envoyees = 0
    for ligne in lignes:
        chemin = Path(ligne["fichier"])
        try:
            if chemin.is_file():
                drive_client.upload(chemin, jour, ligne["nom"])
                envoyees += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ligne %s non envoyee : %s", ligne["nom"], exc)
        finally:
            chemin.unlink(missing_ok=True)
    _journaliser(run_id, f"Lignes par caméra : {envoyees}/{len(lignes)} image(s) envoyée(s) "
                         f"sur Drive ({DOSSIER_LIGNES}/{capture_date}/).")
    return envoyees


def lancer_en_arriere_plan(liens: list[dict], capture_date: str, run_id: int,
                           lignes: list[dict] | None = None) -> Path | None:
    """Ecrit la liste et lance le processus separe. Ne bloque jamais le runner."""
    if not liens and not lignes:
        return None
    dossier = Path(settings.data_dir) / "fiches-liens"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / f"{capture_date}_run{run_id}.json"
    fichier.write_text(
        json.dumps({"date": capture_date, "run_id": run_id, "liens": liens, "lignes": lignes or []},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    journal = open(dossier / f"{capture_date}_run{run_id}.log", "ab")  # noqa: SIM115
    subprocess.Popen(  # noqa: S603 - commande fixe, aucun argument venant du web
        [sys.executable, "-m", "app.services.fiches_liens", str(fichier)],
        stdout=journal, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return fichier


def _cible_temporaire(url: str):
    """Target non enregistree en base, pour reutiliser capture_page."""
    from app.models import CaptureMode, Target

    return Target(
        name="fiche", url=url, enabled=True, full_page=True,
        wait_until="domcontentloaded", wait_after_load_ms=3000,
        timeout_ms=45000, capture_mode=CaptureMode.desktop,
        expand_scroll_areas=False,
    )


def _journaliser(run_id: int | None, message: str, niveau: str = "INFO") -> None:
    if not run_id:
        return
    try:
        from app.database import session_scope
        from app.models import RunLog

        with session_scope() as s:
            s.add(RunLog(run_id=run_id, level=niveau, step="fiches", message=message[:2000]))
    except Exception:  # noqa: BLE001
        logger.warning("Journal de l'execution %s impossible", run_id, exc_info=True)


async def capturer_tout(liens: list[Lien], capture_date: str, run_id: int | None = None,
                        pause_s: float = 2.0) -> dict:
    """Capture chaque fiche puis l'envoie sur Drive. Ne leve jamais."""
    from app.services.capture import capture_page
    from app.services.drive import drive_client

    bilan = {"total": len(liens), "ok": 0, "bloquees": 0, "erreurs": 0}
    if not drive_client.is_configured():
        _journaliser(run_id, "Fiches produit : Drive non configuré, rien n'est envoyé.", "ERROR")
        return bilan

    travail = Path(settings.screenshot_dir) / "fiches-liens" / capture_date
    travail.mkdir(parents=True, exist_ok=True)
    dossiers: dict[str, str] = {}
    racine = drive_client.ensure_folder(DOSSIER_RACINE, settings.google_drive_parent_folder_id or None)
    jour = drive_client.ensure_folder(capture_date, racine)
    debut = time.monotonic()
    _journaliser(run_id, f"Fiches produit : {len(liens)} page(s) à capturer, rangées par marketplace.")

    for n, lien in enumerate(liens, start=1):
        fichier_local = travail / f"{n:04d}.jpg"
        try:
            resultat = await capture_page(_cible_temporaire(lien.url), fichier_local)
            if est_bloquee(resultat.body_text):
                # Page anti-robot a la place de la fiche : rien d'utile, rien sur Drive.
                bilan["bloquees"] += 1
                logger.info("Fiche %s (%s) : page anti-robot, non envoyee", lien.url, lien.marketplace)
            else:
                if lien.marketplace not in dossiers:
                    dossiers[lien.marketplace] = drive_client.ensure_folder(lien.marketplace, jour)
                await asyncio.to_thread(drive_client.upload, fichier_local,
                                        dossiers[lien.marketplace], lien.nom_fichier)
                bilan["ok"] += 1
        except Exception as exc:  # noqa: BLE001 - une fiche en echec n'arrete pas les autres
            texte = str(exc)
            if (isinstance(exc, WebChallenge) or "HTTP 403" in texte or "HTTP 429" in texte
                    or "ERR_HTTP2_PROTOCOL_ERROR" in texte):
                bilan["bloquees"] += 1  # le marchand refuse les robots : rien a capturer
            else:
                bilan["erreurs"] += 1
            logger.warning("Fiche %s (%s) : %s", lien.url, lien.marketplace, texte.splitlines()[0][:200])
        finally:
            fichier_local.unlink(missing_ok=True)
        if n % 25 == 0:
            logger.info("Fiches produit : %d/%d", n, len(liens))
        await asyncio.sleep(pause_s)

    minutes = (time.monotonic() - debut) / 60
    _journaliser(
        run_id,
        f"Fiches produit terminées en {minutes:.0f} min : {bilan['ok']} capturée(s), "
        f"{bilan['bloquees']} bloquée(s) par un anti-robot, {bilan['erreurs']} erreur(s). "
        f"Drive : {DOSSIER_RACINE}/{capture_date}/<marketplace>/",
    )
    return bilan


def main(chemin: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    # D'abord les lignes HuntX : rapides et jamais bloquees.
    envoyer_lignes(donnees.get("lignes") or [], donnees["date"], donnees.get("run_id"))
    liens = depuis_json(donnees.get("liens") or [])
    ignorees = marketplaces_ignorees()
    exclus = [l for l in liens if l.marketplace.casefold() in ignorees]
    liens = [l for l in liens if l.marketplace.casefold() not in ignorees]
    if exclus:
        logger.info("%d lien(s) ignore(s) (marketplaces exclues : %s)", len(exclus), ", ".join(sorted(ignorees)))
    bilan = asyncio.run(capturer_tout(liens, donnees["date"], donnees.get("run_id")))
    logger.info("Bilan : %s", bilan)
    Path(chemin).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
