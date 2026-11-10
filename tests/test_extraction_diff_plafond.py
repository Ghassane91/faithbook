"""Le plafond de lignes d une regle ne doit pas fabriquer de faux
ajouts/retraits : une liste tronquee a la limite ne dit rien sur ce qui
est sorti de la page."""

from __future__ import annotations

from app.services import extraction_diff


def _catalogue(*noms: str, prix: float = 10.0) -> list[dict]:
    return [{"modele": n, "prix": prix, "devise": "EUR", "en_stock": True} for n in noms]


def test_sans_plafond_comportement_inchange():
    evts = extraction_diff.comparer("catalogue", _catalogue("A", "B"), _catalogue("B", "C"))
    assert {e.type for e in evts} == {"ajout", "retrait"}


def test_liste_apres_pleine_ne_signale_pas_de_retrait():
    avant = _catalogue("A", "B")  # pas pleine : ce qui apparait est bien nouveau
    apres = _catalogue("B", "C", "D")  # 3 lignes = plafond : A a pu etre poussee dehors
    evts = extraction_diff.comparer("catalogue", avant, apres, plafond=3)
    assert sorted((e.type, e.ligne) for e in evts) == [("ajout", "C"), ("ajout", "D")]


def test_deux_listes_pleines_ne_signalent_que_les_prix():
    avant = _catalogue("A", "B", "C")
    apres = _catalogue("B", "C", "D")
    assert extraction_diff.comparer("catalogue", avant, apres, plafond=3) == []


def test_liste_avant_pleine_ne_signale_pas_d_ajout():
    avant = _catalogue("A", "B", "C")  # pleine
    apres = _catalogue("A", "B")
    evts = extraction_diff.comparer("catalogue", avant, apres, plafond=3)
    assert [e.type for e in evts] == ["retrait"]
    assert evts[0].ligne == "C"


def test_prix_toujours_compare_malgre_le_plafond():
    avant = _catalogue("A", "B", "C")
    apres = _catalogue("A", "B", prix=12.0) + _catalogue("D")
    evts = extraction_diff.comparer("catalogue", avant, apres, plafond=3)
    assert {e.type for e in evts} == {"prix_change"}
    assert {e.ligne for e in evts} == {"A", "B"}


def test_editorial_ignore_le_plafond():
    avant = [{"titre": "ancienne 1"}, {"titre": "ancienne 2"}]
    apres = [{"titre": "nouvelle"}, {"titre": "ancienne 1"}]
    evts = extraction_diff.comparer("editorial", avant, apres, plafond=2)
    assert [(e.type, e.ligne) for e in evts] == [("annonce", "nouvelle")]


def test_appel_du_runner_accepte_plafond_none():
    assert extraction_diff.comparer("catalogue", _catalogue("A"), _catalogue("A"), plafond=None) == []
