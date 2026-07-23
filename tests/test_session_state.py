"""app/services/session_state.py — dechiffrement transparent (Phase 1a).

`parse_state` est le point de lecture unique du storage_state d'une cible :
la migration b3d4e5f6a7c8 chiffre les valeurs existantes, et targets.py
chiffre desormais a l'ecriture. Ce module doit lire les deux formes.
"""

from __future__ import annotations

import json

from app.services import crypto, session_state


def test_parse_state_none_ou_vide():
    assert session_state.parse_state(None) is None
    assert session_state.parse_state("") is None


def test_parse_state_dechiffre_une_valeur_chiffree():
    etat = {"cookies": [{"name": "xs", "value": "1"}]}
    chiffre = crypto.encrypt_text(json.dumps(etat))
    assert session_state.parse_state(chiffre) == etat


def test_parse_state_repli_sur_json_en_clair_legacy():
    # Donnee anterieure a la migration de chiffrement : ne doit pas planter,
    # juste etre lue telle quelle (avec avertissement journalise).
    etat = {"cookies": [{"name": "xs", "value": "1"}]}
    assert session_state.parse_state(json.dumps(etat)) == etat


def test_parse_state_donnee_illisible():
    assert session_state.parse_state("ni-fernet-ni-json") is None


def test_session_expiry_avec_cookies_facebook():
    etat = {
        "cookies": [
            {"name": "xs", "value": "1", "expires": 4102444800},  # 2100-01-01
            {"name": "autre", "value": "x", "expires": -1},
        ]
    }
    chiffre = crypto.encrypt_text(json.dumps(etat))
    count, expires = session_state.session_expiry(chiffre)
    assert count == 2
    assert expires is not None and expires.year == 2100
