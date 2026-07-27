"""Tests de la comparaison de contenu textuel (phase 4).

La comparaison pixel mesure des positions absolues : sur un fil social
reordonne elle signale un changement massif alors que rien n a ete publie.
La comparaison de texte doit rester insensible a l ordre.
"""

from app.services.capture import _lignes_utiles, text_change_ratio


def test_contenu_identique():
    t = "premiere publication ici\ndeuxieme publication la"
    assert text_change_ratio(t, t) == 0.0


def test_fil_reordonne_ne_compte_pas_comme_un_changement():
    avant = "premiere publication ici\ndeuxieme publication la\ntroisieme publication"
    apres = "troisieme publication\npremiere publication ici\ndeuxieme publication la"
    assert text_change_ratio(avant, apres) == 0.0


def test_publication_ajoutee_est_detectee():
    avant = "premiere publication ici\ndeuxieme publication la"
    apres = "premiere publication ici\ndeuxieme publication la\ntoute nouvelle publication"
    r = text_change_ratio(avant, apres)
    assert r is not None
    assert 0 < r < 1


def test_contenu_totalement_different():
    assert text_change_ratio("premiere publication ici", "aucun rapport avec avant") == 1.0


def test_texte_absent_retourne_none():
    assert text_change_ratio(None, "publication quelconque ici") is None
    assert text_change_ratio("publication quelconque ici", None) is None
    assert text_change_ratio("", "publication quelconque ici") is None


def test_compteurs_et_boutons_ignores():
    avant = "une publication de contenu reel\nJ aime\n12\nPartager"
    apres = "une publication de contenu reel\nJ aime\n458\nPartager"
    assert text_change_ratio(avant, apres) == 0.0


def test_espaces_et_casse_normalises():
    assert text_change_ratio("Une Publication   De Contenu", "une publication de contenu") == 0.0


def test_lignes_utiles_filtre_le_decor():
    lignes = _lignes_utiles("contenu suffisamment long\nok\n\n   \nautre ligne de contenu")
    assert lignes == {"contenu suffisamment long", "autre ligne de contenu"}