from __future__ import annotations

import pytest

from app.services.capture import load_lazy_content


class FakeMouse:
    def __init__(self, page):
        self.page = page

    async def wheel(self, _x: int, y: int):
        self.page.y = min(self.page.y + y, max(0, self.page.height - self.page.viewport))
        # Deux nouveaux blocs sont chargés progressivement, puis la page se stabilise.
        if self.page.wheels < 2:
            self.page.height += 900
        self.page.wheels += 1


class FakePage:
    def __init__(self):
        self.y = 0
        self.height = 1800
        self.viewport = 900
        self.wheels = 0
        self.waits: list[int] = []
        self.mouse = FakeMouse(self)

    async def evaluate(self, script: str):
        if "window.scrollTo(0, 0)" in script:
            self.y = 0
            return None
        if "return {" in script:
            return {"y": self.y, "viewport": self.viewport, "height": self.height}
        return self.height

    async def wait_for_timeout(self, delay: int):
        self.waits.append(delay)


@pytest.mark.asyncio
async def test_defilement_charge_le_contenu_jusqua_stabilisation():
    page = FakePage()

    steps, height = await load_lazy_content(
        page,
        delay_ms=100,
        max_steps=20,
        stable_rounds=2,
    )

    assert page.wheels >= 4
    assert steps == page.wheels
    assert height == 3600
    assert page.y == 0


@pytest.mark.asyncio
async def test_defilement_respecte_la_limite_sur_page_infinie():
    page = FakePage()

    steps, _ = await load_lazy_content(
        page,
        delay_ms=100,
        max_steps=3,
        stable_rounds=10,
    )

    assert steps == 3
