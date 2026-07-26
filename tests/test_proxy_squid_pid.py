"""Non-regression v1.8.4 : le proxy Squid doit supprimer le PID obsolete au demarrage.

Contexte : apres un redemarrage de Docker Desktop, Squid retrouvait un fichier
/run/squid.pid perime et refusait de demarrer (FATAL: Squid is already running),
ce qui faisait boucler le conteneur faithbook-egress-proxy.

Correctif : la commande de demarrage supprime le PID avant de lancer Squid,
et utilise exec pour que Squid devienne PID 1 et recoive les signaux Docker.
"""

from pathlib import Path

import pytest


def _dockerfile_proxy() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidat = parent / "proxy" / "Dockerfile"
        if candidat.is_file():
            return candidat
    raise AssertionError("proxy/Dockerfile introuvable")


@pytest.fixture(scope="module")
def cmd_demarrage() -> str:
    contenu = _dockerfile_proxy().read_text(encoding="utf-8")
    # Les lignes non indentees uniquement : evite le CMD du HEALTHCHECK.
    lignes = [l for l in contenu.splitlines() if l.startswith("CMD")]
    assert lignes, "Aucune instruction CMD de premier niveau dans proxy/Dockerfile"
    return lignes[-1]


def test_supprime_le_pid_obsolete(cmd_demarrage):
    assert "rm -f /run/squid.pid" in cmd_demarrage, (
        "Le CMD du proxy ne supprime plus /run/squid.pid : le bug du "
        "redemarrage en boucle de Squid peut revenir."
    )


def test_squid_lance_avec_exec(cmd_demarrage):
    assert "exec squid" in cmd_demarrage, (
        "Squid doit etre lance avec exec pour devenir PID 1 et recevoir "
        "correctement les signaux d arret de Docker."
    )


def test_squid_utilise_sa_configuration(cmd_demarrage):
    assert "/etc/squid/squid.conf" in cmd_demarrage
    assert "--foreground" in cmd_demarrage
