"""Chiffrement au repos : app/services/crypto.py.

Couvre le coffre de profil (comptes connectes) et le chiffrement de courtes
valeurs (storage_state legacy des cibles, Phase 1a).
"""

from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from app.services import crypto


def test_roundtrip_encrypt_decrypt():
    clair = '{"cookies": [{"name": "xs", "value": "abc"}]}'
    chiffre = crypto.encrypt_text(clair)
    assert chiffre != clair  # jamais stocke tel quel
    assert crypto.decrypt_text(chiffre) == clair


def test_decrypt_donnee_corrompue_ne_leve_pas():
    # Une cle changee ou une donnee corrompue doit degrader proprement (None),
    # jamais faire planter l'appelant (capture ou lecture d'etat de session).
    assert crypto.decrypt_text("ceci-n-est-pas-un-jeton-fernet") is None


def test_decrypt_vide_ou_none():
    assert crypto.decrypt_text(None) is None
    assert crypto.decrypt_text("") is None


def test_vault_profile_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto.settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(crypto.settings, "profile_work_dir", str(tmp_path / "work"))
    slug = "acct-test-roundtrip"

    assert not crypto.profile_exists(slug)

    work = crypto.open_profile(slug)  # coffre absent -> dossier vide
    (Path(work) / "Cookies").write_text("contenu-simule-du-profil-chromium")
    crypto.seal_profile(slug, work)
    crypto.discard_profile(work)

    assert crypto.profile_exists(slug)
    # Le coffre sur disque ne doit JAMAIS contenir le contenu en clair.
    raw_vault = crypto.vault_path(slug).read_bytes()
    assert b"contenu-simule-du-profil-chromium" not in raw_vault

    work2 = crypto.open_profile(slug)
    assert (Path(work2) / "Cookies").read_text() == "contenu-simule-du-profil-chromium"
    crypto.discard_profile(work2)

    crypto.delete_vault(slug)
    assert not crypto.profile_exists(slug)


def test_generation_concurrente_publie_une_seule_cle(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(crypto.settings, "session_encryption_key", "")
    monkeypatch.setattr(crypto.settings, "environment", "development")
    crypto._fernet = None
    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            keys = list(pool.map(lambda _: crypto._load_key(), range(24)))
        assert len(set(keys)) == 1
        assert (tmp_path / ".session_key").read_bytes().strip() == keys[0]
    finally:
        crypto._fernet = None


def test_production_refuse_de_demarrer_sans_cle(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(crypto.settings, "session_encryption_key", "")
    monkeypatch.setattr(crypto.settings, "environment", "production")
    crypto._fernet = None
    try:
        import pytest

        with pytest.raises(RuntimeError, match="obligatoire en production"):
            crypto.ensure_encryption_ready()
    finally:
        crypto._fernet = None
