"""Rattrapage des captures manquees pendant un arret du service.

La tolerance aux retards d APScheduler (misfire_grace_time) ne couvre pas ce
cas : elle ne s applique qu aux taches deja enregistrees au moment ou l
echeance passe. Apres un arret complet de la machine, les taches sont
recreees au demarrage et leur prochaine echeance est calculee dans le futur
— la journee manquee serait simplement perdue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import session_scope
from app.models import Run, Target

logger = logging.getLogger(__name__)


def cibles_a_rattraper(maintenant: datetime | None = None) -> list[int]:
    """Cibles dont une echeance recente est passee sans aucune capture.

    Une seule reprise par cible et par jour, meme si l horaire prevoit
    plusieurs passages : mieux vaut en manquer une que d en declencher dix
    d un coup au demarrage.
    """
    # Import local : app.scheduler importe ce module, on evite le cycle.
    from app.scheduler import build_trigger

    fenetre = max(1, settings.catchup_max_hours)
    manquees: list[int] = []
    with session_scope() as session:
        cibles = session.scalars(select(Target).where(Target.enabled.is_(True))).all()
        for cible in cibles:
            if not (cible.run_time or cible.cron_expression):
                continue
            fuseau = ZoneInfo(cible.timezone_name or settings.timezone)
            now = (maintenant or datetime.now(fuseau)).astimezone(fuseau)
            debut = now - timedelta(hours=fenetre)
            try:
                echeance = build_trigger(cible).get_next_fire_time(None, debut)
            except Exception:  # noqa: BLE001 - un horaire illisible ne bloque rien
                logger.exception("Horaire illisible pour la cible %s", cible.id)
                continue
            if echeance is None or echeance > now:
                continue
            jour = echeance.astimezone(fuseau).strftime("%Y-%m-%d")
            deja = session.scalars(
                select(Run)
                .where(Run.target_id == cible.id, Run.capture_date == jour)
                .limit(1)
            ).first()
            if deja is not None:
                continue
            manquees.append(cible.id)
            logger.info(
                "Cible %s : capture du %s a %s manquee, rattrapage prevu",
                cible.id,
                jour,
                echeance.strftime("%H:%M"),
            )
    return manquees