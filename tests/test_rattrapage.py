"""Rattrapage des captures manquees pendant un arret du service.

Constate le 30/07/2026 : les cibles planifiees a 10:00 et 18:00 n avaient
produit aucune capture, la machine etant eteinte a ces heures. Au demarrage
suivant, le planificateur visait deja le lendemain.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.services.catchup import cibles_a_rattraper


def _creer(client, nom, **extra):
    charge = {
        "name": nom,
        "url": "https://example.com/",
        "run_time": "09:00",
        "enabled": True,
    }
    charge.update(extra)
    reponse = client.post("/api/targets", json=charge)
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


def _a(heure: int, minute: int = 0) -> datetime:
    """Un moment precis de la journee en cours, dans le fuseau configure."""
    fuseau = ZoneInfo(settings.timezone)
    return datetime.now(fuseau).replace(
        hour=heure, minute=minute, second=0, microsecond=0
    )


def test_echeance_passee_sans_capture(auth_client, public_example_dns):
    """Le coeur du defaut : 09:00 est passe et rien n a tourne."""
    cible = _creer(auth_client, "Rattrapage A")
    assert cible["id"] in cibles_a_rattraper(_a(12))


def test_echeance_pas_encore_atteinte(auth_client, public_example_dns):
    cible = _creer(auth_client, "Rattrapage B")
    assert cible["id"] not in cibles_a_rattraper(_a(8))


def test_cible_desactivee_ignoree(auth_client, public_example_dns):
    cible = _creer(auth_client, "Rattrapage C", enabled=False)
    assert cible["id"] not in cibles_a_rattraper(_a(12))


def test_fenetre_de_rattrapage_limitee(auth_client, public_example_dns, monkeypatch):
    """Une echeance trop ancienne n est pas rattrapee : on ne remonte pas le temps."""
    cible = _creer(auth_client, "Rattrapage D")
    monkeypatch.setattr(settings, "catchup_max_hours", 1)
    assert cible["id"] not in cibles_a_rattraper(_a(12))


@pytest.mark.asyncio
async def test_rattrapage_desactivable(monkeypatch):
    from app import scheduler as sch

    monkeypatch.setattr(settings, "catchup_missed_runs", False)
    appels = []

    def ne_doit_pas_etre_appele():
        appels.append(1)
        return []

    monkeypatch.setattr(sch, "cibles_a_rattraper", ne_doit_pas_etre_appele)
    await sch._catchup_job()
    assert appels == []

def test_programmer_une_cible_sans_planificateur_demarre(monkeypatch):
    """APScheduler ne renseigne next_run_time que s il tourne.

    Sans garde-fou, creer une cible plantait des que le planificateur etait
    arrete. Le planificateur global est remplace ici par un neuf, non demarre,
    pour ne pas perturber les autres tests.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app import scheduler as sch
    from app.models import Target

    monkeypatch.setattr(sch, "scheduler", AsyncIOScheduler(timezone=settings.timezone))
    cible = Target(
        id=999999,
        name="Sans planificateur",
        url="https://example.com/",
        run_time="09:00",
        enabled=True,
    )
    sch.schedule_target(cible)
    assert sch.next_run_for(cible.id) is None
