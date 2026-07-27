"""Tests de la route de lien vers la capture distante (phase 3d).

Aucun appel reseau : le client S3 est remplace par un double.
"""

from unittest.mock import MagicMock

from app.config import settings
from app.services.s3 import S3Client


def test_route_protegee_sans_connexion(client):
    reponse = client.get("/api/runs/1/lien")
    assert reponse.status_code in (401, 403)


def test_execution_inexistante(auth_client):
    reponse = auth_client.get("/api/runs/999999/lien")
    assert reponse.status_code == 404


def test_signed_url_transmet_bucket_cle_et_duree(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "faithbook-test")
    monkeypatch.setattr(settings, "s3_signed_url_ttl_seconds", 900)
    faux = MagicMock()
    faux.generate_presigned_url.return_value = "https://exemple/signe"
    c = S3Client()
    monkeypatch.setattr(c, "_get_client", lambda: faux)
    assert c.signed_url("2026-07-26/organization-3/capture.png") == "https://exemple/signe"
    faux.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "faithbook-test",
            "Key": "2026-07-26/organization-3/capture.png",
        },
        ExpiresIn=900,
    )


def test_signed_url_accepte_une_duree_personnalisee(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "bucket")
    faux = MagicMock()
    faux.generate_presigned_url.return_value = "url"
    c = S3Client()
    monkeypatch.setattr(c, "_get_client", lambda: faux)
    c.signed_url("cle.png", ttl_seconds=60)
    assert faux.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 60