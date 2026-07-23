"""Anti-SSRF : app/services/ssrf.py.

Couvre la Phase 1a — le garde n'etait auparavant jamais appele (branche a la
creation/modification de cible et juste avant chaque capture).
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.ssrf import UrlRejected, check_url


def test_rejette_schema_non_http():
    with pytest.raises(UrlRejected):
        check_url("ftp://example.com/fichier")


def test_rejette_localhost():
    with pytest.raises(UrlRejected):
        check_url("http://localhost:8020/api/health")


def test_rejette_boucle_locale():
    with pytest.raises(UrlRejected):
        check_url("http://127.0.0.1/")


def test_rejette_metadata_cloud():
    # 169.254.169.254 : metadata AWS/GCP/Azure — la cible classique du SSRF.
    with pytest.raises(UrlRejected):
        check_url("http://169.254.169.254/latest/meta-data/")


def test_rejette_suffixe_internal():
    with pytest.raises(UrlRejected):
        check_url("http://backend.internal/")


def test_rejette_reseau_prive_10():
    with pytest.raises(UrlRejected):
        check_url("http://10.0.0.5/")


def test_rejette_reseau_prive_192_168():
    with pytest.raises(UrlRejected):
        check_url("http://192.168.1.1/")


def test_accepte_domaine_public():
    # example.com est un domaine IANA stable, jamais interne.
    check_url("https://example.com/")  # ne doit lever aucune exception


def test_liste_blanche_domaines():
    settings.allowed_domains = "example.com"
    try:
        check_url("https://example.com/")  # autorise
        with pytest.raises(UrlRejected):
            check_url("https://iana.org/")  # hors liste -> refuse
    finally:
        settings.allowed_domains = ""


def test_allow_private_targets_contourne_le_garde(monkeypatch):
    settings.allow_private_targets = True
    try:
        check_url("http://127.0.0.1/")  # ne doit pas lever, c'est le but du flag
    finally:
        settings.allow_private_targets = False


def test_url_sans_hote():
    with pytest.raises(UrlRejected):
        check_url("http:///chemin-sans-hote")
