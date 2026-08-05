"""Apercu d'une cadence avant enregistrement.

Le navigateur ne peut pas reproduire APScheduler ni le fuseau du serveur. Un
apercu calcule en JavaScript finirait par mentir le jour ou la regle devient
subtile : cron sur plusieurs jours, changement d'heure, intervalle qui derive
apres une capture en retard. Tout est donc calcule ici, avec le declencheur
exact que le planificateur utilisera.

Ce module ne fait aucune ecriture et ne cree aucune cible : il fabrique un
objet Target en memoire, jamais ajoute a la session.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Run, Target

logger = logging.getLogger(__name__)

NB_PROCHAINES = 5
NB_RUNS_ECHANTILLON = 20
PLAFOND_OCCURRENCES = 4000  # garde-fou : 7 jours a 5 min = 2016


def _fuseau(nom: str | None) -> ZoneInfo:
    """Fuseau de la cible, sinon celui du serveur, sinon UTC."""
    candidats = [
        nom,
        getattr(settings, "timezone", None),
        getattr(settings, "timezone_name", None),
        "UTC",
    ]
    for candidat in candidats:
        if not candidat:
            continue
        try:
            return ZoneInfo(str(candidat))
        except Exception:  # noqa: BLE001
            continue
    return ZoneInfo("UTC")


def _heure(valeur: Any) -> str | None:
    """Le modele stocke l'heure en texte HH:MM et build_trigger la decoupe.

    On ne renvoie donc pas un datetime.time : on normalise vers la chaine
    attendue, en validant au passage qu'elle est lisible.
    """
    if valeur is None:
        return None
    if isinstance(valeur, time):
        return valeur.strftime("%H:%M")
    texte = str(valeur).strip()
    if not texte:
        return None
    for forme in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(texte, forme).strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(f"heure illisible : {texte}")


def _cible_provisoire(
    *,
    run_time: Any,
    cron_expression: str | None,
    interval_minutes: int | None,
    timezone_name: str | None,
) -> Target:
    """Cible en memoire, jamais persistee, juste pour interroger build_trigger."""
    cible = Target()
    cible.name = "apercu"
    cible.url = "https://exemple.invalide/"
    cible.enabled = True
    cible.run_time = _heure(run_time)
    cible.cron_expression = (cron_expression or "").strip() or None
    cible.interval_minutes = int(interval_minutes) if interval_minutes else None
    if hasattr(cible, "timezone_name"):
        cible.timezone_name = timezone_name or None
    return cible


def _declencheur(cible: Target):
    """Import local : app.scheduler importe les services, on casse le cycle."""
    from app.scheduler import build_trigger

    return build_trigger(cible)


def _occurrences(trigger, depart: datetime, fin: datetime, plafond: int) -> list[datetime]:
    """Dates de declenchement dans ]depart, fin], au plus `plafond`."""
    dates: list[datetime] = []
    precedent: datetime | None = None
    reference = depart
    while len(dates) < plafond:
        suivant = trigger.get_next_fire_time(precedent, reference)
        if suivant is None or suivant > fin:
            break
        dates.append(suivant)
        precedent = suivant
        reference = suivant + timedelta(seconds=1)
    return dates


def _octets_moyens(session: Session, target_id: int | None) -> int | None:
    """Poids moyen d'une capture reussie, mesure sur les derniers runs.

    On echantillonne au lieu d'agreger toute la table : une somme sur
    `runs.screenshot_bytes` a deja bloque une transaction pendant une heure
    et demie sur ce projet.
    """
    if not target_id:
        return None
    tailles = session.scalars(
        select(Run.screenshot_bytes)
        .where(Run.target_id == target_id, Run.screenshot_bytes.isnot(None))
        .order_by(Run.id.desc())
        .limit(NB_RUNS_ECHANTILLON)
    ).all()
    valeurs = [t for t in tailles if t and t > 0]
    if not valeurs:
        return None
    return int(sum(valeurs) / len(valeurs))


def apercu_cadence(
    session: Session,
    *,
    target_id: int | None = None,
    run_time: Any = None,
    cron_expression: str | None = None,
    interval_minutes: int | None = None,
    timezone_name: str | None = None,
) -> dict:
    """Ce que ce reglage produira reellement.

    Ne leve jamais : un reglage invalide revient dans la cle `error`, pour que
    le formulaire l'affiche a cote du champ au lieu de casser la page.
    """
    vide = {
        "next_runs": [],
        "per_day": 0.0,
        "per_week": 0,
        "avg_bytes": None,
        "bytes_per_day": None,
        "bytes_per_month": None,
        "error": None,
    }

    try:
        cible = _cible_provisoire(
            run_time=run_time,
            cron_expression=cron_expression,
            interval_minutes=interval_minutes,
            timezone_name=timezone_name,
        )
        trigger = _declencheur(cible)
    except Exception as exc:  # noqa: BLE001
        logger.info("Apercu de cadence refuse : %s", exc)
        return {**vide, "error": str(exc)}

    if trigger is None:
        return {**vide, "error": "Aucune cadence definie."}

    tz = _fuseau(timezone_name)
    maintenant = datetime.now(tz)

    try:
        prochaines = _occurrences(
            trigger, maintenant, maintenant + timedelta(days=370), NB_PROCHAINES
        )
        sur_sept_jours = _occurrences(
            trigger, maintenant, maintenant + timedelta(days=7), PLAFOND_OCCURRENCES
        )
    except Exception:  # noqa: BLE001
        logger.warning("Calcul des echeances impossible", exc_info=True)
        return {**vide, "error": "Cadence illisible par le planificateur."}

    par_semaine = len(sur_sept_jours)
    par_jour = par_semaine / 7.0

    moyen = _octets_moyens(session, target_id)
    par_jour_octets = int(moyen * par_jour) if moyen else None
    par_mois_octets = int(moyen * par_jour * 30) if moyen else None

    return {
        "next_runs": [d.isoformat() for d in prochaines],
        "per_day": round(par_jour, 2),
        "per_week": par_semaine,
        "avg_bytes": moyen,
        "bytes_per_day": par_jour_octets,
        "bytes_per_month": par_mois_octets,
        "error": None,
    }
