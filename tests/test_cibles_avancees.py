"""Tests de la gestion avancee des cibles : duplication et etiquettes."""

from app.api.targets import etiquettes_de


def _creer(client, nom, tags=None, **extra):
    charge = {
        "name": nom,
        "url": "https://example.com/",
        "run_time": "09:00",
        "enabled": True,
    }
    if tags is not None:
        charge["tags"] = tags
    charge.update(extra)
    reponse = client.post("/api/targets", json=charge)
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


def test_etiquettes_vides():
    assert etiquettes_de(None) == set()
    assert etiquettes_de("") == set()
    assert etiquettes_de(" , , ") == set()


def test_etiquettes_normalisees():
    assert etiquettes_de(" Paroisse , DIOCESE ") == {"paroisse", "diocese"}


def test_duplication_recopie_les_reglages(auth_client, public_example_dns):
    source = _creer(auth_client, "Page mere", tags="client-a", subfolder="mere")
    reponse = auth_client.post("/api/targets/%d/dupliquer" % source["id"])
    assert reponse.status_code == 201, reponse.text
    copie = reponse.json()
    assert copie["id"] != source["id"]
    assert copie["url"] == source["url"]
    assert copie["tags"] == "client-a"
    assert copie["subfolder"] == "mere"


def test_duplication_arrive_desactivee(auth_client, public_example_dns):
    source = _creer(auth_client, "Page active")
    copie = auth_client.post("/api/targets/%d/dupliquer" % source["id"]).json()
    assert source["enabled"] is True
    assert copie["enabled"] is False


def test_duplication_prefixe_le_nom(auth_client, public_example_dns):
    source = _creer(auth_client, "Paroisse Saint-Jean")
    copie = auth_client.post("/api/targets/%d/dupliquer" % source["id"]).json()
    assert copie["name"] == "Copie de Paroisse Saint-Jean"


def test_duplication_cible_inconnue(auth_client):
    assert auth_client.post("/api/targets/999999/dupliquer").status_code == 404


def test_filtre_par_etiquette(auth_client, public_example_dns):
    cible = _creer(auth_client, "Avec etiquette", tags="diocese, nord")
    _creer(auth_client, "Sans etiquette")
    trouvees = auth_client.get(
        "/api/targets", params={"etiquette": "diocese"}
    ).json()
    assert cible["id"] in [t["id"] for t in trouvees]
    assert all("diocese" in (t["tags"] or "") for t in trouvees)


def test_filtre_insensible_a_la_casse(auth_client, public_example_dns):
    cible = _creer(auth_client, "Casse melangee", tags="Client-B")
    trouvees = auth_client.get(
        "/api/targets", params={"etiquette": " CLIENT-B "}
    ).json()
    assert cible["id"] in [t["id"] for t in trouvees]


def test_filtre_sans_correspondance(auth_client, public_example_dns):
    _creer(auth_client, "Une cible", tags="alpha")
    trouvees = auth_client.get(
        "/api/targets", params={"etiquette": "inexistant"}
    ).json()
    assert trouvees == []


def test_filtre_ne_matche_pas_un_prefixe(auth_client, public_example_dns):
    _creer(auth_client, "Prefixe", tags="clientele")
    trouvees = auth_client.get(
        "/api/targets", params={"etiquette": "client"}
    ).json()
    assert trouvees == []


def test_duplication_respecte_le_quota(auth_client, public_example_dns, monkeypatch):
    """Dupliquer cree une cible de plus : le quota doit s appliquer ici aussi,
    sinon un simple clic contourne la limite du plan."""
    from app.api import targets as api_targets

    source = _creer(auth_client, "Page mere")

    def plein(*args, **kwargs):
        raise api_targets.quotas.QuotaExceeded("cibles", 5, 5)

    monkeypatch.setattr(api_targets.quotas, "enforce_target_creation", plein)
    reponse = auth_client.post("/api/targets/%d/dupliquer" % source["id"])
    assert reponse.status_code == 409
    assert reponse.json()["detail"]
