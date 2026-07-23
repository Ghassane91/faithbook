from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from app.config import settings
from app.models import Target
from app.services import session_state, ssrf
from app.services.metrics import parse_page_metrics

logger = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    path: Path
    size_bytes: int
    sha256: str
    page_title: str
    final_url: str
    metrics: dict | None = None  # abonnés / mentions J'aime repérés dans la page


_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify(value: str, max_len: int = 60) -> str:
    cleaned = _SLUG_RE.sub("-", value).strip("-")
    return (cleaned[:max_len] or "capture").lower()


def site_label(url: str) -> str:
    """Étiquette lisible du site/page tirée de l'URL : domaine (sans `www`) et,
    s'il existe, le chemin — pour distinguer deux pages d'un même domaine.

    https://www.facebook.com/SPYPOINT.CA  ->  facebook.com-spypoint.ca
    http://www.integr-it.com              ->  integr-it.com
    """
    try:
        parsed = urlparse(url if "//" in url else "http://" + url)
    except Exception:  # noqa: BLE001
        return "site"
    host = (parsed.netloc or "").split("@")[-1].split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.strip("/")
    label = f"{host}/{path}" if path else host
    return slugify(label, 80) or "site"


def build_filename(target: Target, capture_date: str, stamp: str) -> str:
    # Nom reconnaissable : <site>_<date>_<heure>.png
    return f"{site_label(target.url)}_{capture_date}_{stamp}.png"


THUMB_WIDTH = 520
THUMB_SUFFIX = ".thumb.jpg"


def thumb_path(screenshot: Path) -> Path:
    return screenshot.with_suffix(screenshot.suffix + THUMB_SUFFIX)


# Seuil de différence par pixel (sur 255) au-delà duquel un pixel est « changé ».
_PIXEL_DELTA = 24
_DIFF_WIDTH = 400  # largeur normalisée pour comparer deux captures


def image_change_ratio(before: Path, after: Path) -> float | None:
    """Proportion (0..1) de la page qui a changé entre deux captures.

    Robuste au reflow : les deux images sont ramenées à une largeur commune, et
    l'on combine (a) la part de pixels différents sur la hauteur commune et
    (b) l'écart de hauteur (une page qui s'allonge/raccourcit = un changement).
    Retourne None si la comparaison est impossible.
    """
    try:
        from PIL import Image, ImageChops

        with Image.open(before) as ba, Image.open(after) as aa:
            a = ba.convert("L")
            b = aa.convert("L")

            def norm(im: "Image.Image") -> "Image.Image":
                h = max(1, round(im.height * _DIFF_WIDTH / im.width))
                return im.resize((_DIFF_WIDTH, h))

            a, b = norm(a), norm(b)
            common_h = min(a.height, b.height)
            ac = a.crop((0, 0, _DIFF_WIDTH, common_h))
            bc = b.crop((0, 0, _DIFF_WIDTH, common_h))

            diff = ImageChops.difference(ac, bc)
            hist = diff.histogram()  # 256 niveaux
            changed_px = sum(hist[_PIXEL_DELTA + 1 :])
            total_px = _DIFF_WIDTH * common_h
            pixel_ratio = changed_px / total_px if total_px else 0.0

            hmax = max(a.height, b.height)
            height_ratio = abs(a.height - b.height) / hmax if hmax else 0.0

        return round(min(1.0, max(pixel_ratio, height_ratio)), 4)
    except Exception:  # noqa: BLE001 - la comparaison est un confort, jamais bloquante
        logger.warning("Comparaison d'images impossible (%s vs %s)", before, after, exc_info=True)
        return None


def make_thumbnail(screenshot: Path) -> Path | None:
    """Genere une vignette JPEG a cote de la capture.

    Une capture pleine page pese souvent plusieurs centaines de Ko : sans
    vignette, la planche du frontend telecharge des dizaines de Mo et se fige.
    Un echec ici ne doit jamais faire echouer l'execution.
    """
    try:
        from PIL import Image

        destination = thumb_path(screenshot)
        with Image.open(screenshot) as img:
            img = img.convert("RGB")
            # Une capture pleine page est tres haute : on garde le haut,
            # cadre en 4/3, ce que la planche affiche de toute facon.
            largeur, hauteur = img.size
            hauteur_utile = min(hauteur, int(largeur * 3 / 4))
            img = img.crop((0, 0, largeur, hauteur_utile))
            img.thumbnail((THUMB_WIDTH, THUMB_WIDTH), Image.LANCZOS)
            img.save(destination, "JPEG", quality=78, optimize=True)
        return destination
    except Exception:  # noqa: BLE001 - la vignette est un confort, pas un requis
        logger.warning("Vignette impossible pour %s", screenshot, exc_info=True)
        return None


class SessionExpired(RuntimeError):
    """La page servie n'est pas celle attendue : session expiree ou mur de connexion."""


def profile_dir(name: str) -> Path:
    return Path(settings.data_dir) / "profiles" / slugify(name, 40)


async def capture_page(
    target: Target, destination: Path, account_storage: dict | None = None
) -> CaptureResult:
    """Ouvre la page avec Chromium et ecrit la capture pleine page sur disque.

    `account_storage` : storage_state (cookies) déchiffré d'un compte connecté.
    S'il est fourni, la page est capturée **en étant connecté** via ce compte —
    prioritaire sur `session_profile` / `storage_state_json` de la cible.
    """
    # Anti-SSRF : revalide juste avant la navigation (et pas seulement a la
    # creation de la cible), au cas ou le DNS aurait change depuis (rebinding).
    # check_url() fait une resolution DNS bloquante : a lancer hors event loop.
    await asyncio.to_thread(ssrf.check_url, target.url)

    width = target.viewport_width or settings.default_viewport_width
    height = target.viewport_height or settings.default_viewport_height
    timeout = target.timeout_ms or settings.default_timeout_ms
    wait_after = (
        target.wait_after_load_ms
        if target.wait_after_load_ms is not None
        else settings.default_wait_after_load_ms
    )
    user_agent = target.user_agent or settings.default_user_agent or None

    destination.parent.mkdir(parents=True, exist_ok=True)

    launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

    async with async_playwright() as pw:
        context_kwargs: dict = {
            "viewport": {"width": width, "height": height},
            "ignore_https_errors": True,
        }
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        if target.locale:
            context_kwargs["locale"] = target.locale

        browser = None
        if account_storage is not None:
            # Compte connecté : contexte éphémère chargé avec la session déchiffrée.
            browser = await pw.chromium.launch(args=launch_args)
            context_kwargs["storage_state"] = account_storage
            context = await browser.new_context(**context_kwargs)
        elif target.session_profile:
            # Profil persistant : les cookies rafraichis par le site sont conserves
            # d'une execution a l'autre (indispensable pour une session longue duree).
            udd = profile_dir(target.session_profile)
            is_new_profile = not udd.exists()
            udd.mkdir(parents=True, exist_ok=True)
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(udd), args=launch_args, **context_kwargs
            )
            if is_new_profile and target.storage_state_json:
                state = session_state.parse_state(target.storage_state_json)
                if state and state.get("cookies"):
                    await context.add_cookies(state["cookies"])
        else:
            browser = await pw.chromium.launch(args=launch_args)
            if target.storage_state_json:
                state = session_state.parse_state(target.storage_state_json)
                if state:
                    context_kwargs["storage_state"] = state
            context = await browser.new_context(**context_kwargs)

        context.set_default_timeout(timeout)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            response = await page.goto(target.url, wait_until=target.wait_until, timeout=timeout)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} sur {target.url}")

            if wait_after:
                await page.wait_for_timeout(wait_after)

            # Fermeture des bandeaux/modales. Un selecteur absent n'est pas une
            # erreur : la banniere peut deja avoir ete acceptee via le profil.
            if target.dismiss_selectors:
                for selector in filter(
                    None, (s.strip() for s in target.dismiss_selectors.split(";"))
                ):
                    try:
                        await page.click(selector, timeout=5000)
                        await page.wait_for_timeout(1200)
                    except Exception:
                        pass

            # Detection de session expiree AVANT de produire une capture inutile :
            # sans ce controle on archiverait des semaines de murs de connexion.
            if target.fail_if_url_contains:
                for fragment in filter(
                    None, (f.strip() for f in target.fail_if_url_contains.split(";"))
                ):
                    if fragment.lower() in page.url.lower():
                        raise SessionExpired(
                            f"URL finale '{page.url}' contient '{fragment}' : "
                            "session probablement expiree ou acces refuse"
                        )
            if target.expected_selector:
                try:
                    await page.wait_for_selector(
                        target.expected_selector, state="attached", timeout=min(timeout, 15000)
                    )
                except Exception as exc:
                    raise SessionExpired(
                        f"Element attendu '{target.expected_selector}' absent de la page "
                        "(session expiree, page modifiee ou contenu non charge)"
                    ) from exc

            if target.hide_selectors:
                for selector in filter(None, (s.strip() for s in target.hide_selectors.split(";"))):
                    await page.add_style_tag(
                        content=f"{selector} {{ display: none !important; }}"
                    )

            # Force le chargement des images lazy avant une capture pleine page
            if target.full_page:
                await page.evaluate(
                    "async () => {"
                    "  const step = window.innerHeight;"
                    "  for (let y = 0; y < document.body.scrollHeight; y += step) {"
                    "    window.scrollTo(0, y);"
                    "    await new Promise(r => setTimeout(r, 120));"
                    "  }"
                    "  window.scrollTo(0, 0);"
                    "}"
                )
                await page.wait_for_timeout(400)

            title = await page.title()
            final_url = page.url
            # Métriques (abonnés, mentions J'aime…) depuis le texte de la page,
            # best-effort : un échec ici ne compromet jamais la capture.
            try:
                body_text = await page.inner_text("body")
                metrics = parse_page_metrics(body_text) or None
            except Exception:  # noqa: BLE001
                metrics = None
            await page.screenshot(path=str(destination), full_page=target.full_page)
        finally:
            await context.close()
            if browser is not None:
                await browser.close()

    data = destination.read_bytes()
    return CaptureResult(
        path=destination,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_title=title,
        final_url=final_url,
        metrics=metrics,
    )
