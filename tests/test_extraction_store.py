"""Conservation des extractions : table page_extractions, reprise sans appel IA."""

import json
from unittest import mock

import pytest

from app.config import settings
from app.database import session_scope
from app.models import PageExtraction, Run, RunStatus, Target, TriggerType
from app.services import extraction_store
from app.services.extraction import Extraction

PAGE = "FLEX-M $179.99 CAD, was $229.99. In stock."


@pytest.fixture
def config_gemini():
    sauve = (settings.extraction_enabled, settings.extraction_provider, settings.gemini_api_key)
    settings.extraction_enabled = True
    settings.extraction_provider = "gemini"
    settings.gemini_api_key = "AQ.factice"
    yield
    settings.extraction_enabled, settings.extraction_provider, settings.gemini_api_key = sauve


def _cible_et_run(session, tags="catalogue,marque", texte=PAGE):
    cible = Target(name="Test extraction", url="https://example.com/cat", tags=tags)
    session.add(cible)
    session.flush()
    run = _run(session, cible, texte)
    return cible, run


def _run(session, cible, texte):
    run = Run(
        target_id=cible.id, status=RunStatus.success, trigger=TriggerType.manual,
        capture_date="2026-09-25", body_text=texte, page_title="Cameras",
    )
    session.add(run)
    session.flush()
    return run


def _resultat():
    return Extraction(
        regle="catalogue",
        lignes=[{"modele": "FLEX-M", "prix": 179.99, "devise": "CAD", "prix_barre": 229.99,
                 "en_stock": True, "reference": None}],
    )


def test_extraction_enregistree(config_gemini):
    with session_scope() as s:
        cible, run = _cible_et_run(s)
        with mock.patch("app.services.extraction.extraire", return_value=_resultat()) as appel:
            pe = extraction_store.extraire_et_enregistrer(s, run, cible)
        assert appel.call_count == 1
        assert pe.regle == "catalogue" and pe.nb_lignes == 1 and not pe.reprise
        assert pe.fournisseur == "gemini"
        assert extraction_store.lignes(pe)[0]["prix_barre"] == 229.99


def test_texte_identique_sans_appel_ia(config_gemini):
    with session_scope() as s:
        cible, run1 = _cible_et_run(s)
        with mock.patch("app.services.extraction.extraire", return_value=_resultat()):
            extraction_store.extraire_et_enregistrer(s, run1, cible)
        # Meme texte, espaces differents : pas de nouvel appel.
        run2 = _run(s, cible, PAGE.replace(" ", "  "))
        with mock.patch("app.services.extraction.extraire") as appel:
            pe2 = extraction_store.extraire_et_enregistrer(s, run2, cible)
        appel.assert_not_called()
        assert pe2.reprise and pe2.lignes_json == json.dumps(_resultat().lignes, ensure_ascii=False)


def test_texte_change_nouvel_appel(config_gemini):
    with session_scope() as s:
        cible, run1 = _cible_et_run(s)
        with mock.patch("app.services.extraction.extraire", return_value=_resultat()):
            extraction_store.extraire_et_enregistrer(s, run1, cible)
        run2 = _run(s, cible, PAGE.replace("179.99", "159.99"))
        with mock.patch("app.services.extraction.extraire", return_value=_resultat()) as appel:
            pe2 = extraction_store.extraire_et_enregistrer(s, run2, cible)
        assert appel.call_count == 1 and not pe2.reprise
        assert extraction_store.precedente(s, cible.id, run2.id).run_id == run1.id


def test_rien_sans_regle_ou_desactive(config_gemini):
    with session_scope() as s:
        cible, run = _cible_et_run(s, tags="support,marque")
        with mock.patch("app.services.extraction.extraire") as appel:
            assert extraction_store.extraire_et_enregistrer(s, run, cible) is None
        appel.assert_not_called()
        settings.extraction_enabled = False
        cible2, run2 = _cible_et_run(s)
        assert extraction_store.extraire_et_enregistrer(s, run2, cible2) is None


def test_panne_ia_ne_leve_pas(config_gemini):
    with session_scope() as s:
        cible, run = _cible_et_run(s)
        with mock.patch("app.services.extraction.extraire", side_effect=RuntimeError("boom")):
            assert extraction_store.extraire_et_enregistrer(s, run, cible) is None
        with mock.patch("app.services.extraction.extraire", return_value=None):
            assert extraction_store.extraire_et_enregistrer(s, run, cible) is None
        assert s.query(PageExtraction).filter_by(run_id=run.id).count() == 0


def test_empreinte_insensible_aux_espaces():
    assert extraction_store.empreinte("a  b\n c") == extraction_store.empreinte("a b c")
    assert extraction_store.empreinte("a b") != extraction_store.empreinte("a c")


def test_version_async_et_resume(config_gemini):
    import asyncio

    with session_scope() as s:
        cible, run = _cible_et_run(s)
        with mock.patch("app.services.extraction.extraire", return_value=_resultat()):
            pe = asyncio.run(extraction_store.extraire_et_enregistrer_async(s, run, cible))
        assert pe.nb_lignes == 1
        assert "1 ligne(s)" in extraction_store.resume(pe)
        run2 = _run(s, cible, PAGE)
        pe2 = asyncio.run(extraction_store.extraire_et_enregistrer_async(s, run2, cible))
        assert "sans appel IA" in extraction_store.resume(pe2)
