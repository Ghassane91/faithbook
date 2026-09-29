"""Fiches produit liees : lecture du tableau, noms, detection des blocages."""

import os
from unittest import mock

import pytest

from app.services import fiches_liens
from app.services.fiches_liens import Lien, depuis_json, est_bloquee, nettoyer

TABLEAU = """<!doctype html><html><head><meta charset="utf-8"></head><body><table>
<thead><tr><th>BRAND ▲</th><th>MODEL</th><th>BRAND</th><th>ACADEMY</th><th>WALMART</th><th>AMAZON</th></tr></thead>
<tbody>
<tr data-id="b1"><td>Browning Trail Cameras</td><td>Command Ops Elite 22</td>
<td><a href="https://www.browning.com/p/cmd22.html">$99</a></td><td>—</td>
<td><a href="https://www.walmart.com/ip/1">$72</a></td><td><a href="https://www.amazon.com/dp/B0">$99</a></td></tr>
<tr data-id="s1"><td>Stealth Cam</td><td>Deceptor Max</td>
<td><a href="/interne">note</a></td><td><a href="https://www.academy.com/p/x">$80</a></td><td>—</td><td>—</td></tr>
</tbody></table></body></html>"""


@pytest.mark.asyncio
async def test_lecture_du_tableau_dans_un_vrai_navigateur():
    pw_mod = pytest.importorskip("playwright.async_api")
    async with pw_mod.async_playwright() as pw:
        chemin = "/opt/pw-browsers/chromium"
        try:
            nav = await (pw.chromium.launch(executable_path=chemin) if os.path.exists(chemin)
                         else pw.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium indisponible : {exc}")
        try:
            page = await nav.new_page()
            await page.set_content(TABLEAU)
            brut = await page.evaluate(fiches_liens.JS_LIENS)
        finally:
            await nav.close()
    liens = depuis_json(brut)
    assert [(l.marketplace, l.nom_fichier) for l in liens] == [
        ("Site de la marque", "Browning Trail Cameras - Command Ops Elite 22.jpg"),
        ("Walmart", "Browning Trail Cameras - Command Ops Elite 22.jpg"),
        ("Amazon", "Browning Trail Cameras - Command Ops Elite 22.jpg"),
        ("Academy", "Stealth Cam - Deceptor Max.jpg"),
    ]


def test_liens_invalides_et_doublons_ecartes():
    donnees = [
        {"marque": "A", "modele": "X", "colonne": "WALMART", "url": "https://w.com/1"},
        {"marque": "A", "modele": "X", "colonne": "WALMART", "url": "https://w.com/2"},
        {"marque": "A", "modele": "X", "colonne": "AMAZON", "url": "javascript:alert(1)"},
    ]
    assert len(depuis_json(donnees)) == 1


def test_noms_de_fichiers_surs():
    assert nettoyer('Cam "Pro"/X: 4K?') == "Cam Pro X 4K"
    assert Lien("A/B", "M*1", "BASSPRO/CAB", "https://x").marketplace == "Bass Pro - Cabela's"
    assert Lien("A", "B", "NOUVEAU", "https://x").marketplace == "Nouveau"


def test_marketplace_deduite_de_l_adresse_pas_de_la_colonne():
    # Cas reel HuntX : un lien Bass Pro saisi dans la colonne Amazon.
    assert Lien("M", "Edge 3", "AMAZON", "https://www.basspro.com/p/x").marketplace == "Bass Pro - Cabela's"
    assert Lien("M", "Edge 3", "BRAND", "https://www.amazon.fr/dp/1").marketplace == "Amazon"
    assert Lien("M", "Edge 3", "BRAND", "https://www.moultrie.com/p").marketplace == "Site de la marque"
    doublon = [
        {"marque": "M", "modele": "E", "colonne": "BASSPRO/CAB", "url": "https://www.basspro.com/p/x"},
        {"marque": "M", "modele": "E", "colonne": "AMAZON", "url": "https://www.basspro.com/p/x"},
    ]
    assert len(depuis_json(doublon)) == 1


def test_detection_anti_robot():
    assert est_bloquee("Robot or human? " + "x" * 400)
    assert est_bloquee("court")
    assert not est_bloquee("Browning Command Ops Elite 22 trail camera " * 20)


def test_lancement_en_arriere_plan_sans_bloquer(tmp_path):
    with mock.patch.object(fiches_liens.settings, "data_dir", str(tmp_path)), \
         mock.patch("subprocess.Popen") as popen:
        fichier = fiches_liens.lancer_en_arriere_plan(
            [{"marque": "A", "modele": "B", "colonne": "AMAZON", "url": "https://a"}], "2026-09-29", 7
        )
        assert fichier.exists() and popen.call_count == 1
        assert popen.call_args.kwargs["start_new_session"] is True
        assert fiches_liens.lancer_en_arriere_plan([], "2026-09-29", 8) is None


def test_marketplaces_ignorees(monkeypatch):
    monkeypatch.setattr(fiches_liens.settings, "fiches_marketplaces_ignorees", "Walmart, Bass Pro - Cabela's")
    assert fiches_liens.marketplaces_ignorees() == {"walmart", "bass pro - cabela's"}
    monkeypatch.setattr(fiches_liens.settings, "fiches_marketplaces_ignorees", "")
    assert fiches_liens.marketplaces_ignorees() == set()
