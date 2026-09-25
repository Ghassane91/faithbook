"""Extraction IA d une capture et conservation du resultat.

Appele apres une capture reussie. Ne leve jamais : une panne de l IA ne doit
pas faire echouer la capture, elle laisse simplement la capture sans extraction.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PageExtraction, Run, Target
from app.services import extraction
from app.services.regles_extraction import regle_pour

logger = logging.getLogger(__name__)

_BLANCS = re.compile(r"\s+")


def empreinte(texte: str | None) -> str:
    """Empreinte du texte, insensible aux seuls ecarts d espaces."""
    normalise = _BLANCS.sub(" ", (texte or "").strip())
    return hashlib.sha256(normalise.encode("utf-8")).hexdigest()


def precedente(session: Session, target_id: int, avant_run_id: int | None = None) -> PageExtraction | None:
    """Derniere extraction de la cible, anterieure a avant_run_id si fourni."""
    requete = select(PageExtraction).where(PageExtraction.target_id == target_id)
    if avant_run_id is not None:
        requete = requete.where(PageExtraction.run_id < avant_run_id)
    return session.scalars(requete.order_by(PageExtraction.run_id.desc()).limit(1)).first()


def lignes(pe: PageExtraction | None) -> list[dict[str, Any]]:
    if pe is None:
        return []
    try:
        valeur = json.loads(pe.lignes_json or "[]")
    except ValueError:
        return []
    return valeur if isinstance(valeur, list) else []


def _modele_utilise() -> str:
    fournisseur = extraction._fournisseur()
    if fournisseur == "gemini":
        return extraction._modele_gemini()
    if fournisseur == "deepseek":
        return extraction._modele_deepseek()
    if fournisseur == "ollama":
        return extraction.settings.ollama_model
    return extraction._modele()


def _preparer(session: Session, run: Run, target: Target):
    """Decide quoi faire. Renvoie (pe_existante, regle, signature, avant).

    pe_existante non nulle : rien a appeler (deja faite ou reprise).
    regle nulle : rien a faire du tout.
    """
    if not extraction.is_configured():
        return None, None, None, None
    regle = regle_pour(target.tags)
    if regle is None or not (run.body_text or "").strip():
        return None, None, None, None
    deja = session.scalars(select(PageExtraction).where(PageExtraction.run_id == run.id)).first()
    if deja is not None:
        return deja, regle, None, None
    signature = empreinte(run.body_text)
    avant = precedente(session, target.id, run.id)
    if avant is not None and avant.texte_sha256 == signature and avant.regle == regle.nom:
        # Page identique : on reprend le resultat precedent sans appeler l IA.
        pe = PageExtraction(
            run_id=run.id, target_id=target.id, regle=regle.nom,
            fournisseur=avant.fournisseur, modele=avant.modele,
            texte_sha256=signature, lignes_json=avant.lignes_json,
            anomalies_json="[]", nb_lignes=avant.nb_lignes,
            tronque=avant.tronque, reprise=True,
        )
        session.add(pe)
        session.flush()
        return pe, regle, signature, avant
    return None, regle, signature, avant


def _enregistrer(session: Session, run: Run, target: Target, regle, signature, resultat) -> PageExtraction | None:
    if resultat is None:
        return None
    pe = PageExtraction(
        run_id=run.id, target_id=target.id, regle=regle.nom,
        fournisseur=extraction._fournisseur(), modele=_modele_utilise()[:120],
        texte_sha256=signature,
        lignes_json=json.dumps(resultat.lignes, ensure_ascii=False),
        anomalies_json=json.dumps(resultat.anomalies, ensure_ascii=False),
        nb_lignes=len(resultat.lignes), tronque=resultat.tronque, reprise=False,
    )
    session.add(pe)
    session.flush()
    return pe


def extraire_et_enregistrer(session: Session, run: Run, target: Target) -> PageExtraction | None:
    """Extrait la capture `run` et enregistre le resultat (version synchrone).

    Renvoie None quand il n y a rien a faire (extraction desactivee, cible
    sans regle, texte vide) ou en cas de panne. Ne leve jamais.
    """
    try:
        pe, regle, signature, _ = _preparer(session, run, target)
        if pe is not None or regle is None:
            return pe
        resultat = extraction.extraire(regle, run.body_text, run.page_title, run.final_url or target.url)
        return _enregistrer(session, run, target, regle, signature, resultat)
    except Exception as exc:  # noqa: BLE001 - jamais bloquant pour la capture
        logger.warning("Extraction non enregistree (run=%s) : %s", getattr(run, "id", None), exc)
        return None


async def extraire_et_enregistrer_async(session: Session, run: Run, target: Target) -> PageExtraction | None:
    """Meme chose pour le worker : seul l appel reseau part dans un thread,
    la session SQLAlchemy reste dans la boucle principale."""
    try:
        pe, regle, signature, _ = _preparer(session, run, target)
        if pe is not None or regle is None:
            return pe
        resultat = await asyncio.to_thread(
            extraction.extraire, regle, run.body_text, run.page_title, run.final_url or target.url
        )
        return _enregistrer(session, run, target, regle, signature, resultat)
    except Exception as exc:  # noqa: BLE001 - jamais bloquant pour la capture
        logger.warning("Extraction non enregistree (run=%s) : %s", getattr(run, "id", None), exc)
        return None


def resume(pe: PageExtraction) -> str:
    """Phrase courte pour le journal de l execution."""
    if pe.reprise:
        return f"Extraction {pe.regle} : page identique, {pe.nb_lignes} ligne(s) reprises sans appel IA"
    try:
        nb_anomalies = len(json.loads(pe.anomalies_json or "[]"))
    except ValueError:
        nb_anomalies = 0
    return (
        f"Extraction {pe.regle} ({pe.fournisseur}) : {pe.nb_lignes} ligne(s), "
        f"{nb_anomalies} anomalie(s)" + (", texte tronque" if pe.tronque else "")
    )
