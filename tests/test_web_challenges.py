from __future__ import annotations

import asyncio

import pytest

from app.services import web_challenges
from app.services.web_challenges import WebChallenge, assert_no_challenge, detect_challenge


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("Robot or human?", "Activate and hold the button to confirm that you're human."),
        ("Walmart", "Walmart\nRobot or human?\nPlease verify you are human to continue."),
        ("", "Robot or human? " + "x" * 400),
        ("Verify you are human", "Please complete the security check to continue."),
        ("Êtes-vous un humain ?", "Confirmez que vous êtes bien un humain."),
        ("Cabela's", "Vérifiez que vous êtes un humain\nContinuez après vérification."),
        ("Security", "Press & hold to confirm you are a human."),
        ("Vérification", "Appuyez et maintenez le bouton pour confirmer que vous êtes humain."),
        ("Pardon Our Interruption", "Something about your browser made us think you were a bot."),
        ("Bass Pro Shops", "Pardon Our Interruption\nPlease enable JavaScript to continue."),
        ("Just a moment...", "Checking your browser before accessing this site. Cloudflare"),
        ("Just a moment...", "Verifying you are human. This may take a few seconds. Cloudflare"),
        ("Un instant…", "Vérification de votre navigateur avant de continuer."),
        ("Academy", "Human verification\nPlease complete this check."),
    ],
)
def test_reconnait_les_interstitiels_humains(title, body):
    reason = detect_challenge(title, body)
    assert reason is not None
    assert str(WebChallenge(reason)) == reason


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("Robot vacuum - Walmart", "Robot vacuum\nPrice $99.\nAdd to cart."),
        ("Academy Sports", "Shop outdoor products and robot toys."),
        ("Product", "Tent\n$89.99\nAdd to cart\nVerify you are human\nCAPTCHA widget"),
        ("Product", "Tent\nThis site is protected by reCAPTCHA. Privacy Policy and Terms apply."),
        ("Privacy policy", "We verify you are human using CAPTCHA to prevent bot traffic."),
        ("Product", "Robot vacuum. Verify you are human? Learn about our checkout CAPTCHA."),
        ("Customer support", "To reset your robot, press and hold the power button."),
        ("Camera manual", "Press and hold the button to take a photo."),
        ("Just a moment", "A book about taking time to enjoy life. Add to cart."),
        ("Just a moment...", "Cloudflare"),
        ("Checking stock", "Are you human or robot? This quiz is a board game for families."),
        ("Store", "Tent specifications\n" * 250 + "Robot or human?"),
        ("", ""),
    ],
)
def test_ne_confond_pas_les_pages_utiles_avec_un_defi(title, body):
    assert detect_challenge(title, body) is None


def test_raison_ne_contient_ni_extrait_de_page_ni_url():
    secret = "https://example.com/check?session=ne-pas-journaliser"
    reason = detect_challenge("Robot or human?", f"Verify you are human. {secret}")
    assert reason is not None
    assert "session=" not in str(WebChallenge(reason))
    assert secret not in str(WebChallenge(secret))


class FakePage:
    def __init__(self, title="Product", body="Tent\nAdd to cart"):
        self.page_title = title
        self.body = body
        self.reads = []

    async def title(self):
        return self.page_title

    async def inner_text(self, selector, *, timeout):
        self.reads.append((selector, timeout))
        return self.body


@pytest.mark.asyncio
async def test_lecture_visible_bornee_avant_detection():
    page = FakePage("Robot or human?", "Please complete the verification.")
    with pytest.raises(WebChallenge, match="vérification humaine"):
        await assert_no_challenge(page)
    assert page.reads == [("body", 5000)]


@pytest.mark.asyncio
async def test_page_normale_est_acceptee():
    page = FakePage()
    assert await assert_no_challenge(page) is None
    assert page.reads == [("body", 5000)]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["title", "body"])
async def test_erreur_de_lecture_ne_devient_pas_une_reussite(stage):
    class BrokenPage(FakePage):
        async def title(self):
            if stage == "title":
                raise RuntimeError("Page closed")
            return await super().title()

        async def inner_text(self, *args, **kwargs):
            raise RuntimeError("Page closed")

    with pytest.raises(RuntimeError, match="Page closed"):
        await assert_no_challenge(BrokenPage())


@pytest.mark.asyncio
async def test_lecture_du_titre_ne_peut_pas_bloquer_indefiniment(monkeypatch):
    monkeypatch.setattr(web_challenges, "_READ_TIMEOUT_MS", 10)

    class HungPage(FakePage):
        async def title(self):
            await asyncio.Event().wait()

    with pytest.raises(asyncio.TimeoutError):
        await assert_no_challenge(HungPage())
