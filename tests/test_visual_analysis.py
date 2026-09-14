import copy
import io
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

from app.config import settings
from app.services import visual_analysis as vision
from app.api import visual
from app.database import session_scope
from app.models import VisualAnalysis


def png():
    out = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(out, "PNG")
    return out.getvalue()


def result(price="129.90", **kwargs):
    item = dict(image=1, name="Caméra test", brand="TEST", reference="CAM-1",
                price=price, currency="EUR", tax="TTC", pack=1,
                evidence="CAM-1 129,90 EUR TTC", zone="Centre", needs_review=False,
                availability="En stock")
    item.update(kwargs)
    return dict(summary="Caméra visible dans l'image 1.", items=[item], limitations=[])


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(settings, "visual_analysis_enabled", True)
    monkeypatch.setattr(settings, "visual_analysis_provider", "anthropic")
    monkeypatch.setattr(settings, "visual_analysis_model", "test-vision-model")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-only")
    monkeypatch.setattr(settings, "visual_analysis_daily_limit", 1000)
    monkeypatch.setattr(vision, "extract", lambda question, images: result())


def create(client, source="catalogue"):
    return client.post("/api/visual", data={"question": "Quel prix ?", "source": source},
                       files=[("images", ("capture.png", png(), "image/png"))])


def test_real_image_decoding_and_invalid_files():
    encoded, ext = vision.prepare_image(png())
    assert ext == "png"
    assert Image.open(io.BytesIO(encoded)).format == "JPEG"
    for data in [b"", b"not an image", b"x" * (vision.MAX_BYTES + 1)]:
        with pytest.raises(ValueError):
            vision.prepare_image(data)


def test_long_capture_requires_crop():
    out = io.BytesIO()
    Image.new("RGB", (100, 3100)).save(out, "PNG")
    with pytest.raises(ValueError, match="Recadrez"):
        vision.prepare_image(out.getvalue())


@pytest.mark.parametrize("price", ["1,299.90", "1299 EUR", "-1", "NaN", "1e3"])
def test_ambiguous_prices_rejected(price):
    with pytest.raises(ValueError):
        vision.Extraction.model_validate(result(price))


def test_precise_comparison_and_missing_observation():
    changes = vision.compare(result("100.00"), result("120.01"))
    assert changes[0]["delta"] == "20.01"
    assert changes[0]["percent"] == "20.01"
    assert vision.compare(result(), dict(items=[]))[0]["kind"] == "not_observed"
    assert vision.compare(dict(items=[]), result())[0]["kind"] == "newly_observed"


@pytest.mark.parametrize("field,value", [("currency", "MAD"), ("tax", None), ("pack", 2),
                                        ("needs_review", True), ("price", None)])
def test_different_basis_not_comparable(field, value):
    other = result()
    other["items"][0][field] = value
    assert vision.compare(result("100"), other)[0]["kind"] == "not_comparable"


def test_duplicate_identity_is_ambiguous():
    other = result()
    other["items"].append(copy.deepcopy(other["items"][0]))
    assert vision.compare(result(), other)[0]["kind"] == "ambiguous"


def test_formula_safe_export():
    data = result(name=" =HYPERLINK(test)")
    assert "' =HYPERLINK(test)" in vision.csv_export(data)


def test_authenticated_upload_history_exports_and_isolation(auth_client, client, ready):
    anonymous = TestClient(app)
    assert anonymous.get("/api/visual").status_code == 401
    created = create(auth_client)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["status"] == "success"
    assert row["result"]["items"][0]["price"] == "129.90"
    assert auth_client.get(f'/api/visual/{row["id"]}/image/1').content == png()
    for fmt in ("json", "csv", "md"):
        assert auth_client.get(f'/api/visual/{row["id"]}/export?format={fmt}').status_code == 200
    org = auth_client.post("/api/organizations", json={"name": "Visual isolated"}).json()
    headers = {"X-Organization-ID": str(org["id"])}
    assert auth_client.get(f'/api/visual/{row["id"]}', headers=headers).status_code == 404
    assert auth_client.post(f'/api/visual/{row["id"]}/archive', headers=headers).status_code == 404
    assert auth_client.delete(f'/api/visual/{row["id"]}', headers=headers).status_code == 404


def test_bad_image_and_model_failure(auth_client, ready, monkeypatch):
    bad = auth_client.post("/api/visual", data={"question": "x", "source": "y"},
                           files={"images": ("x.png", b"bad", "image/png")})
    assert bad.status_code == 422
    def fail(*args):
        raise RuntimeError("secret provider detail")
    monkeypatch.setattr(vision, "extract", fail)
    row = create(auth_client).json()
    assert row["status"] == "failed"
    assert "secret provider detail" not in json.dumps(row)
    assert auth_client.post(f'/api/visual/{row["id"]}/archive').status_code == 409


def test_disabled_provider_fails_closed(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "visual_analysis_enabled", False)
    assert create(auth_client).status_code == 503


def test_comparison_requires_same_source(auth_client, ready):
    first = create(auth_client, "a").json()
    second = create(auth_client, "b").json()
    assert auth_client.get(f'/api/visual/{second["id"]}/compare/{first["id"]}').status_code == 422


def test_archive_partial_retry_does_not_rerun_ai(auth_client, ready, monkeypatch):
    calls, folders = [], []
    monkeypatch.setattr(visual.drive_client, "is_configured", lambda: True)
    monkeypatch.setattr(visual.drive_client, "check_access", lambda: {})
    monkeypatch.setattr(visual.drive_client, "ensure_folder",
                        lambda name, parent_id=None: folders.append(name) or name)
    failing = [True]
    def upload(path, folder, filename=None, *, mimetype):
        calls.append((path.name, mimetype))
        if path.name == "resultats.csv" and failing[0]:
            raise RuntimeError("temporary")
        return SimpleNamespace(file_id=uuid.uuid4().hex)
    monkeypatch.setattr(visual.drive_client, "upload", upload)
    row = create(auth_client).json()
    url = f'/api/visual/{row["id"]}/archive'
    failed = auth_client.post(url).json()
    assert failed["archive_status"] == "failed"
    assert len(failed["archive"]["files"]) == 2
    failing[0] = False
    final = auth_client.post(url).json()
    assert final["archive_status"] == "uploaded"
    assert len(final["archive"]["files"]) == 4
    assert calls.count(("image-1.png", "image/png")) == 1
    assert ("resultats.csv", "text/csv") in calls
    assert len(folders) == 3
    before = len(calls)
    assert auth_client.post(url).json()["archive_status"] == "uploaded"
    assert len(calls) == before


def test_archive_requires_real_receipt(auth_client, ready, monkeypatch):
    monkeypatch.setattr(visual.drive_client, "is_configured", lambda: True)
    monkeypatch.setattr(visual.drive_client, "check_access", lambda: {})
    monkeypatch.setattr(visual.drive_client, "ensure_folder", lambda *a: "folder")
    monkeypatch.setattr(visual.drive_client, "upload", lambda *a, **k: SimpleNamespace(file_id=""))
    row = create(auth_client).json()
    assert auth_client.post(f'/api/visual/{row["id"]}/archive').json()["archive_status"] == "failed"


def test_anthropic_adapter_sends_pixels_and_rejects_bad_citations(monkeypatch):
    monkeypatch.setattr(settings, "visual_analysis_enabled", True)
    monkeypatch.setattr(settings, "visual_analysis_model", "test")
    monkeypatch.setattr(settings, "visual_analysis_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "not-a-real-key")
    real_client = httpx.Client
    bad = [False]
    def handler(request):
        body = json.loads(request.content)
        assert body["messages"][0]["content"][0]["source"]["data"]
        assert "tools" not in body
        output = result(image=2 if bad[0] else 1)
        return httpx.Response(200, json={"stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(output)}]})
    monkeypatch.setattr(vision.httpx, "Client",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    assert vision.extract("prix", [vision.prepare_image(png())[0]])["items"][0]["image"] == 1
    bad[0] = True
    with pytest.raises(ValueError, match="inexistante"):
        vision.extract("prix", [vision.prepare_image(png())[0]])


def test_existing_capture_import_and_provenance(auth_client, ready, public_example_dns):
    from pathlib import Path
    from app.models import Run, RunStatus
    target = auth_client.post("/api/targets", json={"name": "Visual source",
        "url": "https://example.com/", "run_time": "09:00"}).json()
    path = Path(settings.screenshot_dir) / ("test-" + uuid.uuid4().hex + ".png")
    path.write_bytes(png())
    with session_scope() as session:
        run = Run(target_id=target["id"], status=RunStatus.success, trigger="manual",
                  capture_date="2026-09-14", screenshot_path=str(path), idempotency_key=uuid.uuid4().hex)
        session.add(run)
        session.flush()
        run_id = run.id
    response = auth_client.post("/api/visual/from-runs",
        json={"question": "prix ?", "run_ids": [run_id]})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "success"
    assert response.json()["run_ids"] == [run_id]
    assert response.json()["source"] == "cible-" + str(target["id"])


def test_visual_storage_quota_and_daily_limit(auth_client, ready, monkeypatch):
    from app.models import Organization
    org = auth_client.post("/api/organizations", json={"name": "Visual quota"}).json()
    headers = {"X-Organization-ID": str(org["id"])}
    with session_scope() as session:
        session.get(Organization, org["id"]).quota_storage_bytes = 100
    response = auth_client.post("/api/visual", headers=headers,
        data={"question": "prix", "source": "test"}, files={"images": ("x.png", png(), "image/png")})
    assert response.status_code == 429
    with session_scope() as session:
        session.get(Organization, org["id"]).quota_storage_bytes = 10_000_000
    monkeypatch.setattr(settings, "visual_analysis_daily_limit", 1)
    kwargs = dict(headers=headers, data={"question": "prix", "source": "test"},
                  files={"images": ("x.png", png(), "image/png")})
    assert auth_client.post("/api/visual", **kwargs).status_code == 201
    assert auth_client.post("/api/visual", **kwargs).status_code == 429
