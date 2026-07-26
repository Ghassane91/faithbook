from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.services.capture import capture_stitched_page, requires_stitched_capture


class FakeMouse:
    def __init__(self, page):
        self.page = page

    async def wheel(self, _x: int, y: int):
        self.page.y = min(
            self.page.y + y,
            max(0, self.page.document_height - self.page.viewport),
        )


class FakePage:
    def __init__(self):
        self.y = 0
        self.viewport = 400
        self.document_height = 1000
        self.mouse = FakeMouse(self)

    async def evaluate(self, script: str):
        if "window.scrollTo(0, 0)" in script:
            self.y = 0
            return None
        if "window.scrollTo(0," in script:
            self.y = int(script.rsplit(",", 1)[1].rstrip(") "))
            return None
        if "return {" in script:
            return {
                "y": self.y,
                "viewport": self.viewport,
                "height": self.document_height,
            }
        if "scrollTop" in script:
            return self.y
        return None

    async def wait_for_timeout(self, _delay: int):
        return None

    async def screenshot(self, **_kwargs):
        # Chaque fenêtre porte une teinte liée à sa position. Si l'assemblage
        # perd une tuile, une bande de la couleur attendue disparaît.
        color = (min(255, self.y // 4), 80, 120)
        image = Image.new("RGB", (600, self.viewport), color=color)
        stream = BytesIO()
        image.save(stream, "PNG")
        return stream.getvalue()


def test_facebook_utilise_la_capture_assemblee():
    assert requires_stitched_capture("https://www.facebook.com/share/example")
    assert requires_stitched_capture("https://m.facebook.com/groups/example")
    assert not requires_stitched_capture("https://example.com/page")


@pytest.mark.asyncio
async def test_capture_assemble_chaque_fenetre_sans_trou(tmp_path):
    destination = tmp_path / "stitched.png"
    page = FakePage()

    steps, height = await capture_stitched_page(
        page,
        destination,
        delay_ms=100,
        max_steps=10,
        stable_rounds=1,
    )

    assert steps >= 2
    assert height == 1000
    assert page.y == 0
    with Image.open(destination) as image:
        assert image.size == (600, 1000)
        assert image.getpixel((10, 50)) == (0, 80, 120)
        assert image.getpixel((10, 500))[0] > 0
