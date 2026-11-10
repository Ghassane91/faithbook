from __future__ import annotations

import re

from PIL import Image

from app.services import pagination
from app.services.capture import THUMB_WIDTH, image_change_ratio, make_thumbnail


def _capture(path, hauteur: int, couleur=(235, 232, 226), fmt="JPEG"):
    Image.new("RGB", (720, hauteur), color=couleur).save(path, fmt)
    return path


def test_pdf_ecrit_page_par_page(tmp_path):
    source = _capture(tmp_path / "capture.jpg", 4000)
    pdf = tmp_path / "capture.pdf"
    pages = pagination.pdf_par_ecran(source, 900, pdf)
    assert pages == len(pagination._limites(4000, 900, pagination.RECOUVREMENT))
    contenu = pdf.read_bytes()
    assert contenu.startswith(b"%PDF")
    # Chaque ajout reecrit l'objet Pages (mise a jour incrementale) : le
    # dernier /Count est le nombre de pages final du document.
    assert int(re.findall(rb"/Count (\d+)", contenu)[-1]) == pages


def test_pdf_ecrase_un_fichier_existant(tmp_path):
    source = _capture(tmp_path / "capture.jpg", 2000)
    pdf = tmp_path / "capture.pdf"
    pdf.write_bytes(b"%PDF-1.4 ancien contenu")
    pages = pagination.pdf_par_ecran(source, 900, pdf)
    assert pages and pages >= 2
    assert b"ancien contenu" not in pdf.read_bytes()


def test_pdf_inutile_sur_un_seul_ecran(tmp_path):
    source = _capture(tmp_path / "capture.jpg", 800)
    assert pagination.pdf_par_ecran(source, 900, tmp_path / "x.pdf") is None


def test_vignette_jpeg_reduite_sans_decodage_complet(tmp_path):
    source = _capture(tmp_path / "capture.jpg", 7200)
    vignette = make_thumbnail(source)
    assert vignette is not None
    with Image.open(vignette) as image:
        assert image.mode == "RGB"
        assert image.width <= THUMB_WIDTH
        assert abs(image.height / image.width - 10) < 0.05


def test_vignette_png_palette_toujours_convertie(tmp_path):
    source = tmp_path / "capture.png"
    Image.new("P", (1440, 2000)).save(source)
    vignette = make_thumbnail(source)
    assert vignette is not None
    with Image.open(vignette) as image:
        assert image.mode == "RGB"


def test_comparaison_jpeg_en_mode_draft_detecte_un_changement(tmp_path):
    avant = _capture(tmp_path / "a.jpg", 6000)
    apres = _capture(tmp_path / "b.jpg", 6000, couleur=(20, 20, 20))
    identique = _capture(tmp_path / "c.jpg", 6000)
    assert image_change_ratio(avant, apres) > 0.9
    assert image_change_ratio(avant, identique) == 0.0


def test_comparaison_png_inchangee(tmp_path):
    avant = _capture(tmp_path / "a.png", 3000, fmt="PNG")
    apres = _capture(tmp_path / "b.png", 4500, fmt="PNG")
    ratio = image_change_ratio(avant, apres)
    assert ratio is not None
    assert abs(ratio - 1 / 3) < 0.01  # ecart de hauteur 1500/4500
