"""Planche du jour : un document PDF par journee de veille.

Jusqu'ici, la planche etait une *vue* : le navigateur allait chercher les
captures du jour et les affichait cote a cote. Rien ne pouvait etre archive,
envoye a un client, ni relu dans six mois. Ce module en fait un fichier.

Deux choix expliquent tout le reste :

1. Le PDF est imprime par le Chromium deja installe pour les captures. Aucune
   dependance nouvelle, et la mise en page se retouche en CSS plutot qu'en
   code.

2. La planche montre les echecs autant que les reussites. Un document qui
   n'afficherait que les captures abouties laisserait croire que tout va bien
   un jour ou trois cibles n'ont rien pris. Pour un outil de veille, c'est le
   pire des defauts : on croit surveiller, et on ne surveille pas.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from html import escape
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Run, RunStatus, Target
from app.services.capture import make_thumbnail, thumb_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Donnees
# ---------------------------------------------------------------------------


def runs_du_jour(session: Session, capture_date: str, organization_id: int) -> list[Run]:
    """Executions de la journee pour une organisation, cible par cible."""
    return list(
        session.scalars(
            select(Run)
            .join(Target, Target.id == Run.target_id)
            .where(
                Run.capture_date == capture_date,
                Target.organization_id == organization_id,
            )
            .order_by(Target.name, Run.id)
        ).all()
    )


def _vignette_base64(run: Run) -> str | None:
    """Vignette JPEG encodee, ou None si la capture n'a pas laisse d'image.

    On tente de la fabriquer si elle manque : une capture ancienne peut
    preceder l'arrivee des vignettes. Un echec ici n'empeche jamais la planche
    d'etre produite — le bloc s'affichera sans image.
    """
    if not run.screenshot_path:
        return None
    capture = Path(run.screenshot_path)
    vignette = thumb_path(capture)
    if not vignette.is_file():
        if not capture.is_file():
            return None
        vignette = make_thumbnail(capture) or Path("")
    try:
        donnees = vignette.read_bytes()
    except Exception:  # noqa: BLE001
        logger.warning("Vignette illisible pour le run %s", run.id, exc_info=True)
        return None
    return base64.b64encode(donnees).decode("ascii")


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------

FEUILLE = """
@page { size: A4; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: #1a1a1a; margin: 0; font-size: 10pt; line-height: 1.4;
}
.garde { border-bottom: 2px solid #a33a2d; padding-bottom: 8mm; margin-bottom: 8mm; }
.eyebrow {
  font-family: "SFMono-Regular", Consolas, monospace; font-size: 7pt;
  letter-spacing: 0.18em; text-transform: uppercase; color: #8b8a84; margin: 0 0 3mm;
}
h1 { font-size: 20pt; margin: 0 0 2mm; letter-spacing: -0.02em; }
.sous-titre { color: #55534e; margin: 0; }
.chiffres { display: flex; gap: 10mm; margin-top: 6mm; }
.chiffre b { display: block; font-size: 17pt; line-height: 1.1; }
.chiffre span {
  font-family: "SFMono-Regular", Consolas, monospace; font-size: 7pt;
  letter-spacing: 0.14em; text-transform: uppercase; color: #8b8a84;
}
/* Un bloc ne doit jamais etre coupe entre deux pages : une vignette orpheline
   sans son titre rend le document illisible. */
.cible { page-break-inside: avoid; margin-bottom: 7mm; padding-bottom: 5mm;
         border-bottom: 1px solid #e0ddd6; display: flex; gap: 6mm; }
.cible:last-child { border-bottom: 0; }
.image { width: 62mm; flex: 0 0 62mm; }
.image img { width: 100%; border: 1px solid #d8d5cd; display: block; }
.vide {
  width: 100%; height: 40mm; border: 1px dashed #c9c5bb; color: #8b8a84;
  display: flex; align-items: center; justify-content: center; font-size: 8pt;
}
.details { flex: 1; min-width: 0; }
.details h2 { font-size: 12pt; margin: 0 0 1mm; }
.url { font-family: "SFMono-Regular", Consolas, monospace; font-size: 7.5pt;
       color: #55534e; word-break: break-all; margin: 0 0 3mm; }
.etat { margin: 0 0 3mm; font-size: 8.5pt; }
.pastille { display: inline-block; padding: 0.6mm 2mm; border-radius: 2mm;
            font-size: 7.5pt; font-weight: 600; }
.ok { background: #e6efe6; color: #2f6b3a; }
.change { background: #e2eff2; color: #0e6e82; }
.echec { background: #f6e7ef; color: #8e2b62; }
.resume { background: #f4f2ee; border-left: 2px solid #a33a2d;
          padding: 2mm 3mm; margin: 0 0 3mm; font-size: 9pt; }
.pied { margin-top: 8mm; padding-top: 3mm; border-top: 1px solid #e0ddd6;
        font-size: 7.5pt; color: #8b8a84; }
"""


def _pastille(run: Run) -> str:
    if run.status != RunStatus.success:
        return '<span class="pastille echec">echec</span>'
    if run.changed:
        ratio = f" · {run.change_ratio:.1%}" if run.change_ratio else ""
        return f'<span class="pastille change">page modifiee{ratio}</span>'
    return '<span class="pastille ok">inchangee</span>'


def _bloc_cible(run: Run, target: Target) -> str:
    vignette = _vignette_base64(run)
    if vignette:
        image = f'<img src="data:image/jpeg;base64,{vignette}" alt="">'
    else:
        image = '<div class="vide">aucune image</div>'

    heure = run.started_at.strftime("%H:%M") if run.started_at else "-"
    morceaux = [
        '<section class="cible">',
        f'<div class="image">{image}</div>',
        '<div class="details">',
        f"<h2>{escape(target.name.strip() or 'Sans nom')}</h2>",
        f'<p class="url">{escape(target.url)}</p>',
        f'<p class="etat">{_pastille(run)} &nbsp; capture de {heure}</p>',
    ]

    if run.status != RunStatus.success and run.error_message:
        morceaux.append(f'<p class="resume">{escape(run.error_message[:400])}</p>')

    if run.ai_summary:
        morceaux.append(f'<p class="resume">{escape(run.ai_summary)}</p>')

    morceaux.append("</div></section>")
    return "".join(morceaux)


def construire_html(
    session: Session,
    capture_date: str,
    organization_id: int,
    organisation_nom: str = "",
) -> str:
    """Page HTML complete de la planche, vignettes incluses en base64."""
    runs = runs_du_jour(session, capture_date, organization_id)
    cibles = {
        t.id: t
        for t in session.scalars(
            select(Target).where(Target.organization_id == organization_id)
        ).all()
    }

    reussies = sum(1 for r in runs if r.status == RunStatus.success)
    changees = sum(1 for r in runs if r.status == RunStatus.success and r.changed)
    echecs = len(runs) - reussies

    blocs = [_bloc_cible(r, cibles[r.target_id]) for r in runs if r.target_id in cibles]
    if not blocs:
        blocs = ['<p class="vide">Aucune execution ce jour-la.</p>']

    genere = datetime.now().strftime("%d/%m/%Y a %H:%M")
    titre = escape(organisation_nom) if organisation_nom else "Veille visuelle"

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>Planche du {capture_date}</title>
<style>{FEUILLE}</style></head>
<body>
<header class="garde">
  <p class="eyebrow">FaithBook &middot; planche du jour</p>
  <h1>{capture_date}</h1>
  <p class="sous-titre">{titre}</p>
  <div class="chiffres">
    <div class="chiffre"><b>{len(runs)}</b><span>executions</span></div>
    <div class="chiffre"><b>{reussies}</b><span>captures</span></div>
    <div class="chiffre"><b>{changees}</b><span>changements</span></div>
    <div class="chiffre"><b>{echecs}</b><span>echecs</span></div>
  </div>
</header>
{''.join(blocs)}
<p class="pied">Document genere le {genere} par FaithBook. Les captures
d'origine restent archivees en pleine resolution ; les images ci-dessus en
sont des reductions.</p>
</body></html>"""


# ---------------------------------------------------------------------------
# Rendu et depot
# ---------------------------------------------------------------------------


async def rendre_pdf(html: str) -> bytes:
    """Imprime la page avec le Chromium deja present pour les captures."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        navigateur = await p.chromium.launch(args=["--no-sandbox"])
        try:
            page = await navigateur.new_page()
            await page.set_content(html, wait_until="load")
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            await navigateur.close()


def chemin_local(organization_id: int, capture_date: str) -> Path:
    dossier = Path(settings.screenshot_dir) / f"organization-{organization_id}" / "planches"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / f"planche_{capture_date}.pdf"


def deposer_distant(fichier: Path, organization_id: int, capture_date: str) -> str | None:
    """Envoie la planche dans AAAA-MM-JJ/organization-N/ si un stockage distant existe.

    La planche se place au-dessus des dossiers par site : elle les couvre tous.
    Renvoie le lien, ou None si le stockage est local.
    """
    if settings.storage_backend == "s3":
        from app.services.s3 import s3_client as client
    elif settings.storage_backend == "google_drive":
        from app.services.drive import drive_client as client
    else:
        return None

    if not client.is_configured():
        logger.warning("Stockage distant declare mais non configure : planche gardee en local.")
        return None

    from app.services.drive_sync import date_folder_name

    parent = client.ensure_folder(date_folder_name(capture_date), None)
    parent = client.ensure_folder(f"organization-{organization_id}", parent)
    envoi = client.upload(fichier, parent, fichier.name)
    return envoi.web_link or None


async def exporter(
    session: Session,
    capture_date: str,
    organization_id: int,
    organisation_nom: str = "",
) -> Path:
    """Produit la planche du jour et la range. Retourne le chemin local."""
    html = construire_html(session, capture_date, organization_id, organisation_nom)
    pdf = await rendre_pdf(html)
    fichier = chemin_local(organization_id, capture_date)
    fichier.write_bytes(pdf)
    logger.info("Planche %s ecrite : %s (%s octets)", capture_date, fichier, len(pdf))

    try:
        lien = deposer_distant(fichier, organization_id, capture_date)
        if lien:
            logger.info("Planche %s deposee : %s", capture_date, lien)
    except Exception:  # noqa: BLE001
        # Le depot distant ne doit jamais faire perdre le document : il est
        # deja ecrit sur le disque, et une reprise reste possible.
        logger.error("Depot distant de la planche impossible", exc_info=True)

    return fichier
