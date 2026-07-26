"""Non-regression v1.8.4 : le backend doit nettoyer le verrou X11 au demarrage.

Contexte : apres un docker compose restart, le conteneur garde son systeme de
fichiers. Xvfb retrouvait /tmp/.X99-lock, refusait de demarrer avec
"Server is already active for display 99", l entrypoint sortait en erreur et
le conteneur backend repartait en boucle indefiniment.

Correctif : l entrypoint supprime les verrous X11 residuels avant Xvfb.
"""

from pathlib import Path

import pytest


def _entrypoint() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidat = parent / "docker-entrypoint.sh"
        if candidat.is_file():
            return candidat
    raise AssertionError("docker-entrypoint.sh introuvable")


def _index_ligne(lignes, predicat, description):
    for i, ligne in enumerate(lignes):
        if predicat(ligne):
            return i
    raise AssertionError("Ligne introuvable dans docker-entrypoint.sh : " + description)


@pytest.fixture(scope="module")
def lignes():
    return _entrypoint().read_text(encoding="utf-8").splitlines()


def test_supprime_le_verrou_x11(lignes):
    assert any("/tmp/.X99-lock" in l for l in lignes), (
        "L entrypoint ne supprime plus /tmp/.X99-lock : le backend peut "
        "repartir en boucle apres un docker restart."
    )


def test_supprime_aussi_le_socket_x11(lignes):
    assert any("/tmp/.X11-unix/X99" in l for l in lignes), (
        "Le socket X11 residuel doit aussi etre nettoye."
    )


def test_nettoyage_avant_le_lancement_de_xvfb(lignes):
    i_rm = _index_ligne(
        lignes,
        lambda l: l.strip().startswith("rm -f") and ".X99-lock" in l,
        "suppression du verrou X99",
    )
    i_xvfb = _index_ligne(
        lignes, lambda l: l.strip().startswith("Xvfb "), "lancement de Xvfb"
    )
    assert i_rm < i_xvfb, (
        "Le nettoyage du verrou doit avoir lieu AVANT le lancement de Xvfb, "
        "sinon il ne sert a rien."
    )
