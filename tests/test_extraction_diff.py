"""Comparaison d extractions successives et message d alerte regroupe."""

import asyncio
from unittest import mock

from app.config import settings
from app.database import session_scope
from app.models import PageExtraction, Run, RunStatus, Target, TriggerType
from app.services import runner
from app.services.extraction_diff import comparer


def P(modele, prix=None, barre=None, stock=None, devise="CAD"):
    return {"modele": modele, "prix": prix, "prix_barre": barre, "en_stock": stock,
            "devise": devise, "reference": None}


def types(evts):
    return sorted(e.type for e in evts)


def test_rien_ne_change():
    lignes = [P("FLEX-M", 179.99), P("LINK", 99.99)]
    assert comparer("catalogue", lignes, lignes) == []


def test_toute_variation_de_prix_meme_minime():
    evts = comparer("catalogue", [P("FLEX-M", 179.99)], [P("FLEX-M", 179.98)])
    assert types(evts) == ["prix_change"]
    assert "179.99 CAD -> 179.98 CAD" in evts[0].detail


def test_devise_d_origine_conservee():
    evts = comparer("catalogue", [P("A", 10, devise="EUR")], [P("A", 12, devise="EUR")])
    assert "EUR" in evts[0].detail and "+20.0 %" in evts[0].detail


def test_prix_barre_suivi_separement():
    debut = comparer("catalogue", [P("A", 229.99)], [P("A", 179.99, barre=229.99)])
    assert types(debut) == ["prix_change", "promo_debut"]
    fin = comparer("catalogue", [P("A", 179.99, barre=229.99)], [P("A", 179.99)])
    assert types(fin) == ["promo_fin"]
    change = comparer("catalogue", [P("A", 150, barre=200)], [P("A", 150, barre=210)])
    assert types(change) == ["prix_barre_change"]


def test_prix_illisible_n_est_pas_une_variation():
    assert comparer("catalogue", [P("A", 100)], [P("A", None)]) == []
    # Barre disparu mais prix courant illisible : pas de « fin de promotion ».
    assert comparer("catalogue", [P("A", 80, barre=100)], [P("A", None)]) == []


def test_ajout_retrait_et_stock():
    avant = [P("A", 10, stock=True), P("B", 20), P("C", 30), P("D", 40)]
    apres = [P("A", 10, stock=False), P("B", 20), P("C", 30), P("E", 50)]
    assert types(comparer("catalogue", avant, apres)) == ["ajout", "retrait", "rupture"]


def test_cle_insensible_casse_et_accents():
    assert comparer("catalogue", [P("Caméra FLEX-M", 10)], [P("camera flex m", 10)]) == []


def test_disparition_massive_signalee_une_fois():
    avant = [P(f"M{i}", 10) for i in range(10)]
    evts = comparer("catalogue", avant, [])
    assert types(evts) == ["lecture_suspecte"]


def test_tarifs():
    avant = [{"forfait": "Standard", "prix_mensuel": 5.99, "devise": "USD"}]
    apres = [{"forfait": "Standard", "prix_mensuel": 6.99, "devise": "USD"},
             {"forfait": "Premium", "prix_mensuel": 9.99, "devise": "USD"}]
    assert types(comparer("tarifs", avant, apres)) == ["ajout", "prix_change"]


def test_editorial_seulement_les_nouvelles():
    avant = [{"titre": "Ancienne"}, {"titre": "Partie"}]
    apres = [{"titre": "Ancienne"}, {"titre": "Nouvelle camera 4K"}]
    evts = comparer("editorial", avant, apres)
    assert types(evts) == ["annonce"] and evts[0].ligne == "Nouvelle camera 4K"


# ------------------------------------------------ branchement dans le runner

def _pe(s, cible, lignes_json, reprise=False):
    run = Run(target_id=cible.id, status=RunStatus.success, trigger=TriggerType.manual,
              capture_date="2026-09-25", body_text="x")
    s.add(run)
    s.flush()
    pe = PageExtraction(run_id=run.id, target_id=cible.id, regle="catalogue",
                        texte_sha256="h" + str(run.id), lignes_json=lignes_json,
                        anomalies_json="[]", nb_lignes=1, tronque=False, reprise=reprise)
    s.add(pe)
    s.flush()
    return run, pe


def test_un_seul_message_par_capture():
    sauve = settings.extraction_alerts_enabled
    settings.extraction_alerts_enabled = True
    try:
        with session_scope() as s:
            cible = Target(name="Alerte", url="https://example.com/a", tags="catalogue,marque")
            s.add(cible)
            s.flush()
            _pe(s, cible, '[{"modele": "A", "prix": 10, "devise": "CAD"}, {"modele": "B", "prix": 20, "devise": "CAD"}]')
            run2, pe2 = _pe(s, cible, '[{"modele": "A", "prix": 11, "devise": "CAD"}, {"modele": "B", "prix": 21, "devise": "CAD"}]')
            with mock.patch("app.services.notify._send") as envoi:
                asyncio.run(runner._alertes_extraction(s, run2, cible, pe2, 1))
            assert envoi.call_count == 1
            sujet, corps = envoi.call_args.args
            assert "2 changement(s)" in sujet
            assert "10.00 CAD -> 11.00 CAD" in corps and "20.00 CAD -> 21.00 CAD" in corps
    finally:
        settings.extraction_alerts_enabled = sauve


def test_premiere_extraction_et_reprise_sans_alerte():
    with session_scope() as s:
        cible = Target(name="Reference", url="https://example.com/r", tags="catalogue,marque")
        s.add(cible)
        s.flush()
        run1, pe1 = _pe(s, cible, '[{"modele": "A", "prix": 10}]')
        run2, pe2 = _pe(s, cible, '[{"modele": "A", "prix": 99}]', reprise=True)
        with mock.patch("app.services.notify._send") as envoi:
            asyncio.run(runner._alertes_extraction(s, run1, cible, pe1, 1))
            asyncio.run(runner._alertes_extraction(s, run2, cible, pe2, 1))
        envoi.assert_not_called()
