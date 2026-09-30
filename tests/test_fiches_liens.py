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


@pytest.mark.asyncio
async def test_une_image_par_ligne_avec_en_tete(tmp_path):
    pw_mod = pytest.importorskip("playwright.async_api")
    from PIL import Image

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
            lignes = await fiches_liens.capturer_lignes(page, tmp_path / "lignes")
            hauteur_entete = await page.evaluate("document.querySelector('thead').getBoundingClientRect().height")
            hauteur_ligne = await page.evaluate("document.querySelector('tbody tr').getBoundingClientRect().height")
        finally:
            await nav.close()
    assert [l["nom"] for l in lignes] == [
        "Browning Trail Cameras - Command Ops Elite 22.jpg", "Stealth Cam - Deceptor Max.jpg",
    ]
    with Image.open(lignes[0]["fichier"]) as im:
        assert abs(im.height - (hauteur_entete + hauteur_ligne)) <= 3


def test_envoi_des_lignes_puis_nettoyage(tmp_path):
    fichier = tmp_path / "l.jpg"
    fichier.write_bytes(b"x")
    faux = mock.MagicMock()
    faux.is_configured.return_value = True
    faux.ensure_folder.side_effect = ["racine", "jour"]
    with mock.patch("app.services.drive.drive_client", faux), \
         mock.patch.object(fiches_liens, "_journaliser"):
        n = fiches_liens.envoyer_lignes([{"fichier": str(fichier), "nom": "A - B.jpg"}], "2026-09-30", 1)
    assert n == 1 and not fichier.exists()
    faux.upload.assert_called_once_with(fichier, "jour", "A - B.jpg")
    assert faux.ensure_folder.call_args_list[0].args[0] == fiches_liens.DOSSIER_LIGNES


@pytest.mark.asyncio
async def test_page_anti_robot_jamais_envoyee_sur_drive(tmp_path):
    from types import SimpleNamespace

    liens = [
        Lien("Spypoint", "Flex", "AMAZON", "https://www.amazon.com/dp/1"),
        Lien("Spypoint", "Flex", "WALMART", "https://www.walmart.com/ip/1"),
    ]
    textes = {liens[0].url: "Spypoint Flex trail camera " * 40, liens[1].url: "Robot or human?"}

    async def fausse_capture(cible, destination, **_):
        destination.write_bytes(b"x")
        return SimpleNamespace(body_text=textes[cible.url])

    faux = mock.MagicMock()
    faux.is_configured.return_value = True
    faux.ensure_folder.side_effect = lambda nom, parent=None: f"id-{nom}"
    with mock.patch("app.services.drive.drive_client", faux), \
         mock.patch("app.services.capture.capture_page", fausse_capture), \
         mock.patch.object(fiches_liens.settings, "screenshot_dir", str(tmp_path)), \
         mock.patch.object(fiches_liens, "_journaliser"):
        bilan = await fiches_liens.capturer_tout(liens, "2026-09-30", 1, pause_s=0)
    assert bilan == {"total": 2, "ok": 1, "bloquees": 1, "erreurs": 0}
    faux.upload.assert_called_once()
    assert faux.upload.call_args.args[1:] == ("id-Amazon", "Spypoint - Flex.jpg")
    assert not any(tmp_path.rglob("*.jpg"))
