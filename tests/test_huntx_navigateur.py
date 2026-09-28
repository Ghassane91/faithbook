"""Connexion automatique et depliage des listes, dans un vrai Chromium.

Le site est simule par page.route : aucun reseau. Ignore si Chromium est
absent de la machine de test.
"""

import os

import pytest

from app.services import auto_login, zones_defilantes

playwright = pytest.importorskip("playwright.async_api")

SITE = "https://huntx.test"

PAGE_CONNEXION = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<form id="f"><input type="email" name="email"><input type="password" name="password">
<button type="submit">Sign in</button></form>
<script>
document.getElementById('f').addEventListener('submit', (e) => {
  e.preventDefault();
  const ok = document.querySelector('[name=email]').value === 'robot@novostok.com'
          && document.querySelector('[name=password]').value === 'S3cret!é';
  if (ok) { document.cookie = 'session=ok; path=/'; location.href = '/app/cameras'; }
  else { document.body.insertAdjacentHTML('beforeend', '<p>Invalid</p>'); }
});
</script></body></html>"""

PAGE_CAMERAS = """<!doctype html><html><head><style>
html, body { height: 100%; margin: 0; overflow: hidden; }
.app { display: flex; flex-direction: column; height: 100vh; }
.liste { height: 300px; overflow-y: auto; border: 1px solid #000; }
.cam { height: 40px; }
</style></head><body><div class="app"><h1>Cameras</h1><div class="liste">"""
PAGE_CAMERAS += "".join(f'<div class="cam" id="c{i}">Camera {i}</div>' for i in range(1, 81))
PAGE_CAMERAS += "</div></div></body></html>"


async def _navigateur(pw):
    chemin = os.environ.get("FB_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    try:
        if os.path.exists(chemin):
            return await pw.chromium.launch(executable_path=chemin)
        return await pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium indisponible : {exc}")


async def _page_site(pw):
    navigateur = await _navigateur(pw)
    contexte = await navigateur.new_context(viewport={"width": 1280, "height": 720})

    async def repondre(route, requete):
        connecte = "session=ok" in ((await requete.all_headers()).get("cookie") or "")
        if requete.url.endswith("/app/cameras") and connecte:
            await route.fulfill(body=PAGE_CAMERAS, content_type="text/html")
        else:
            await route.fulfill(body=PAGE_CONNEXION, content_type="text/html")

    await contexte.route(f"{SITE}/**", repondre)
    return navigateur, contexte, await contexte.new_page()


def _ident(mdp="S3cret!é"):
    return auto_login.Identifiants(utilisateur="robot@novostok.com", mot_de_passe=mdp)


@pytest.mark.asyncio
async def test_connexion_automatique_puis_retour_page_cible():
    async with playwright.async_playwright() as pw:
        navigateur, contexte, page = await _page_site(pw)
        try:
            await page.goto(f"{SITE}/app/cameras")
            assert await auto_login.formulaire_visible(page, _ident())
            fait = await auto_login.connecter_si_besoin(
                page, _ident(), f"{SITE}/app/cameras", "load", 15000
            )
            assert fait
            assert await page.inner_text("h1") == "Cameras"
            # Deuxieme passage : deja connecte, rien a faire.
            await page.goto(f"{SITE}/app/cameras")
            assert not await auto_login.connecter_si_besoin(
                page, _ident(), f"{SITE}/app/cameras", "load", 15000
            )
        finally:
            await navigateur.close()


@pytest.mark.asyncio
async def test_mauvais_mot_de_passe_refuse():
    async with playwright.async_playwright() as pw:
        navigateur, contexte, page = await _page_site(pw)
        try:
            await page.goto(f"{SITE}/app/cameras")
            with pytest.raises(auto_login.ConnexionRefusee):
                await auto_login.connecter_si_besoin(
                    page, _ident("faux"), f"{SITE}/app/cameras", "load", 3000
                )
        finally:
            await navigateur.close()


@pytest.mark.asyncio
async def test_liste_defilante_depliee_en_entier():
    async with playwright.async_playwright() as pw:
        navigateur, contexte, page = await _page_site(pw)
        try:
            await contexte.add_cookies([{"name": "session", "value": "ok", "url": SITE}])
            await page.goto(f"{SITE}/app/cameras")
            avant = await page.evaluate("document.documentElement.scrollHeight")
            assert avant <= 720  # la page ne defile pas : seule la liste defile

            resultat = await zones_defilantes.deplier(page, pause_ms=10)
            assert resultat["zones"] == 1
            hauteur = await page.evaluate("document.documentElement.scrollHeight")
            assert hauteur >= 80 * 40  # les 80 cameras tiennent dans la page
            derniere = await page.evaluate(
                "document.getElementById('c80').getBoundingClientRect().bottom + window.scrollY"
            )
            assert derniere <= hauteur
            image = await page.screenshot(full_page=True, type="jpeg", quality=75)
            from io import BytesIO

            from PIL import Image

            with Image.open(BytesIO(image)) as im:
                assert im.size[1] >= 80 * 40
        finally:
            await navigateur.close()


@pytest.mark.asyncio
async def test_page_sans_zone_defilante_inchangee():
    async with playwright.async_playwright() as pw:
        navigateur = await _navigateur(pw)
        try:
            page = await navigateur.new_page()
            await page.set_content("<p>Rien a deplier</p>")
            assert (await zones_defilantes.deplier(page))["zones"] == 0
        finally:
            await navigateur.close()


def test_identifiants_chiffres_et_jamais_affiches():
    class Compte:
        id = 1
        encrypted_credentials = auto_login.chiffrer("robot@novostok.com", "S3cret!é")
        login_selectors = '{"submit": "#go"}'
        login_url = None

    assert "S3cret" not in Compte.encrypted_credentials
    ident = auto_login.charger(Compte)
    assert ident.utilisateur == "robot@novostok.com" and ident.mot_de_passe == "S3cret!é"
    assert ident.bouton_valider == "#go"
    assert "S3cret" not in repr(ident)

    class SansIdentifiants:
        encrypted_credentials = None

    assert auto_login.charger(SansIdentifiants) is None
