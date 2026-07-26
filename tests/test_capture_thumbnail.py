from __future__ import annotations

from PIL import Image

from app.services.capture import (
    THUMB_MAX_HEIGHT,
    THUMB_WIDTH,
    legacy_thumb_path,
    make_thumbnail,
)


def test_vignette_conserve_toute_la_hauteur_sans_recadrage(tmp_path):
    original = tmp_path / "capture.png"
    Image.new("RGB", (1440, 7200), color=(235, 232, 226)).save(original)
    legacy = legacy_thumb_path(original)
    Image.new("RGB", (520, 390), color=(255, 255, 255)).save(legacy)

    thumbnail = make_thumbnail(original)

    assert thumbnail is not None
    assert not legacy.exists()
    with Image.open(thumbnail) as image:
        assert image.width <= THUMB_WIDTH
        assert image.height <= THUMB_MAX_HEIGHT
        assert image.height > image.width
        # Le ratio 1:5 de la pleine page est conservé à l'arrondi près.
        assert abs((image.height / image.width) - 5) < 0.02
