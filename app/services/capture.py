from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from app.config import settings
from app.models import AccountStatus, Target
from app.services import crypto, session_state, ssrf
from app.services.metrics import parse_page_metrics
from app.services.profile_lock import get_profile_lock

logger = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    path: Path
    size_bytes: int
    sha256: str
    page_title: str
    final_url: str
    metrics: dict | None = None  # abonnés / mentions J'aime repérés dans la page
    # Texte visible de la page, conserve pour comparer les contenus entre
    # deux captures : un fil reordonne ne doit pas compter comme un changement.
    body_text: str | None = None
    # État rafraîchi après navigation, destiné à être rechiffré par le runner.
    storage_state: dict | None = None
    scroll_steps: int = 0
    document_height: int | None = None


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


def organization_folder(target: Target) -> str:
    """Dossier racine stable qui empêche deux organisations de partager
    physiquement leurs captures."""
    return (
        f"organization-{target.organization_id}"
        if target.organization_id is not None
        else "organization-legacy"
    )


THUMB_WIDTH = 520
THUMB_MAX_HEIGHT = 3200
THUMB_SUFFIX = ".thumb.full.jpg"
LEGACY_THUMB_SUFFIX = ".thumb.jpg"


def thumb_path(screenshot: Path) -> Path:
    return screenshot.with_suffix(screenshot.suffix + THUMB_SUFFIX)


def legacy_thumb_path(screenshot: Path) -> Path:
    return screenshot.with_suffix(screenshot.suffix + LEGACY_THUMB_SUFFIX)


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


# En dessous de cette longueur, une ligne est du decor (boutons, compteurs,
# separateurs) et non du contenu : on l ignore pour comparer deux pages.
_TEXT_MIN_LEN = 8


def _lignes_utiles(text: str) -> set[str]:
    """Lignes de contenu d une page, normalisees pour la comparaison."""
    lignes: set[str] = set()
    for brute in text.splitlines():
        ligne = " ".join(brute.split())
        if len(ligne) >= _TEXT_MIN_LEN:
            lignes.add(ligne.casefold())
    return lignes


def text_change_ratio(before: str | None, after: str | None) -> float | None:
    """Proportion (0..1) de lignes de texte apparues ou disparues.

    Insensible a l ordre : un fil de publications reordonne, sans contenu
    nouveau, donne 0. C est la difference decisive avec la comparaison
    pixel, qui compare des positions absolues et voit un changement massif
    des que les publications changent de place.

    Retourne None si l une des captures n a pas de texte exploitable ;
    l appelant retombe alors sur la comparaison d images.
    """
    if not before or not after:
        return None
    avant = _lignes_utiles(before)
    apres = _lignes_utiles(after)
    if not avant or not apres:
        return None
    union = avant | apres
    if not union:
        return 0.0
    return round(len(avant ^ apres) / len(union), 4)


def _lignes_indexees(text: str) -> dict[str, str]:
    """Lignes utiles indexees par forme normalisee -> texte d origine."""
    index: dict[str, str] = {}
    for brute in text.splitlines():
        ligne = " ".join(brute.split())
        if len(ligne) >= _TEXT_MIN_LEN:
            index.setdefault(ligne.casefold(), ligne)
    return index


def diff_lignes(
    before: str | None, after: str | None
) -> tuple[list[str], list[str]]:
    """Lignes apparues puis lignes disparues entre deux captures.

    On garde le texte d origine et son ordre : la synthese IA doit
    recevoir des phrases lisibles, pas des cles normalisees.
    """
    avant = _lignes_indexees(before or "")
    apres = _lignes_indexees(after or "")
    ajoutees = [texte for cle, texte in apres.items() if cle not in avant]
    retirees = [texte for cle, texte in avant.items() if cle not in apres]
    return ajoutees, retirees


def make_thumbnail(screenshot: Path) -> Path | None:
    """Genere une vignette JPEG a cote de la capture.

    Une capture pleine page pese souvent plusieurs centaines de Ko : sans
    vignette, la planche du frontend telecharge des dizaines de Mo et se fige.
    La vignette conserve toute la page : elle est réduite proportionnellement,
    jamais recadrée au premier écran. Un échec ici ne doit jamais faire échouer
    l'exécution.
    """
    try:
        from PIL import Image

        destination = thumb_path(screenshot)
        with Image.open(screenshot) as img:
            img = img.convert("RGB")
            # Ne jamais rogner le bas : la Planche propose un aperçu vertical
            # déroulant. La borne de hauteur garde un fichier léger même pour
            # les fils réellement très longs.
            img.thumbnail((THUMB_WIDTH, THUMB_MAX_HEIGHT), Image.LANCZOS)
            img.save(destination, "JPEG", quality=74, optimize=True, progressive=True)
        # Supprime l'ancienne vignette 4:3 dès qu'elle a été remplacée.
        legacy_thumb_path(screenshot).unlink(missing_ok=True)
        return destination
    except Exception:  # noqa: BLE001 - la vignette est un confort, pas un requis
        logger.warning("Vignette impossible pour %s", screenshot, exc_info=True)
        return None


class SessionExpired(RuntimeError):
    """La session liée nécessite une intervention humaine."""

    def __init__(
        self,
        message: str,
        account_status: AccountStatus = AccountStatus.expired,
    ) -> None:
        super().__init__(message)
        self.account_status = account_status


async def load_lazy_content(
    page,
    *,
    delay_ms: int | None = None,
    max_steps: int | None = None,
    stable_rounds: int | None = None,
) -> tuple[int, int]:
    """Descend progressivement jusqu'à stabilisation de la page.

    Un saut immédiat vers le bas ne suffit pas sur Facebook et les applications
    modernes : IntersectionObserver et les listes virtualisées ont besoin de
    passages successifs dans la fenêtre visible. La limite de pas empêche une
    page réellement infinie de bloquer la capture.
    """
    delay = max(100, delay_ms or settings.auto_scroll_delay_ms)
    limit = max(1, max_steps or settings.auto_scroll_max_steps)
    stable_needed = max(1, stable_rounds or settings.auto_scroll_stable_rounds)

    await page.evaluate("window.scrollTo(0, 0)")
    previous_height = 0
    stable = 0
    steps = 0
    final_height = 0

    for _ in range(limit):
        metrics = await page.evaluate(
            """() => {
                const root = document.scrollingElement || document.documentElement;
                return {
                    y: root.scrollTop,
                    viewport: window.innerHeight,
                    height: Math.max(
                        root.scrollHeight,
                        document.body ? document.body.scrollHeight : 0
                    )
                };
            }"""
        )
        final_height = int(metrics.get("height") or 0)
        viewport = max(320, int(metrics.get("viewport") or 0))
        y = int(metrics.get("y") or 0)
        at_bottom = y + viewport >= final_height - 8

        if at_bottom and final_height == previous_height:
            stable += 1
        else:
            stable = 0
        if stable >= stable_needed:
            break

        # Un mouvement de souris réel déclenche plus fidèlement les observateurs
        # de visibilité qu'un unique window.scrollTo() jusqu'en bas.
        await page.mouse.wheel(0, max(500, int(viewport * 0.85)))
        await page.wait_for_timeout(delay)
        previous_height = final_height
        steps += 1

    # Laisse les dernières requêtes lazy se terminer, puis revient en haut pour
    # obtenir un PNG déterministe avec les en-têtes au début.
    await page.wait_for_timeout(min(5000, delay * 2))
    final_height = int(
        await page.evaluate(
            """() => Math.max(
                (document.scrollingElement || document.documentElement).scrollHeight,
                document.body ? document.body.scrollHeight : 0
            )"""
        )
        or final_height
    )
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(250)
    return steps, final_height


def requires_stitched_capture(url: str) -> bool:
    """Les fils Facebook virtualisent leurs publications.

    Une capture Chromium ``full_page`` classique voit la hauteur totale du
    document, mais les publications sorties de l'écran ont déjà été retirées
    du DOM. Le résultat contient alors une très longue zone vide.
    """
    host = (urlparse(url).hostname or "").lower()
    return host == "facebook.com" or host.endswith(".facebook.com")


async def capture_stitched_page(
    page,
    destination: Path,
    *,
    delay_ms: int | None = None,
    max_steps: int | None = None,
    stable_rounds: int | None = None,
) -> tuple[int, int]:
    """Capture chaque fenêtre pendant le défilement puis assemble les tuiles.

    Le chevauchement évite les coupures et retire les en-têtes fixes répétés.
    Cette méthode conserve les publications des listes virtualisées, car leurs
    pixels sont enregistrés avant que le site ne les décharge du DOM.
    """
    from PIL import Image

    delay = max(100, delay_ms or settings.auto_scroll_delay_ms)
    limit = max(1, max_steps or settings.auto_scroll_max_steps)
    stable_needed = max(1, stable_rounds or settings.auto_scroll_stable_rounds)

    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(250)

    tiles: list[Image.Image] = []
    covered_until = 0
    previous_height = 0
    stable = 0
    steps = 0
    output_width = 0
    pixel_scale_y = 1.0

    try:
        for _ in range(limit):
            metrics = await page.evaluate(
                """() => {
                    const root = document.scrollingElement || document.documentElement;
                    return {
                        y: root.scrollTop,
                        viewport: window.innerHeight,
                        height: Math.max(
                            root.scrollHeight,
                            document.body ? document.body.scrollHeight : 0
                        )
                    };
                }"""
            )
            y = max(0, int(metrics.get("y") or 0))
            viewport = max(320, int(metrics.get("viewport") or 0))
            document_height = max(viewport, int(metrics.get("height") or viewport))

            raw = await page.screenshot(
                type="png",
                full_page=False,
                animations="disabled",
                caret="hide",
            )
            with Image.open(BytesIO(raw)) as opened:
                image = opened.convert("RGB")
            output_width = output_width or image.width
            if image.width != output_width:
                image = image.resize(
                    (output_width, round(image.height * output_width / image.width)),
                    Image.LANCZOS,
                )

            scale_y = image.height / viewport
            pixel_scale_y = scale_y
            overlap_css = max(0, covered_until - y)
            visible_css = max(0, min(viewport, document_height - y))
            top_px = min(image.height, round(overlap_css * scale_y))
            bottom_px = min(image.height, round(visible_css * scale_y))
            if bottom_px > top_px:
                tiles.append(image.crop((0, top_px, image.width, bottom_px)))
                covered_until = max(covered_until, y + visible_css)

            at_bottom = y + viewport >= document_height - 8
            if at_bottom and document_height == previous_height:
                stable += 1
            else:
                stable = 0
            if stable >= stable_needed:
                break

            previous_height = document_height
            distance = max(1, int(viewport * 0.90))
            await page.mouse.wheel(0, distance)
            await page.wait_for_timeout(delay)
            steps += 1

            # Certains sites interceptent la molette sans déplacer le document.
            # Un scroll direct sert alors de repli, sans sauter de contenu.
            next_y = int(
                await page.evaluate(
                    "() => (document.scrollingElement || document.documentElement).scrollTop"
                )
                or 0
            )
            if next_y <= y and y + viewport < document_height:
                forced_y = min(y + distance, max(0, document_height - viewport))
                await page.evaluate(f"window.scrollTo(0, {forced_y})")
                await page.wait_for_timeout(delay)

        if not tiles:
            await page.screenshot(path=str(destination), full_page=True)
            return steps, previous_height

        total_height = sum(tile.height for tile in tiles)
        stitched = Image.new("RGB", (output_width, total_height), color=(255, 255, 255))
        offset = 0
        for tile in tiles:
            stitched.paste(tile, (0, offset))
            offset += tile.height
            tile.close()
        stitched.save(destination, "PNG", optimize=False, compress_level=6)
        stitched.close()
        image.close()
        return steps, round(total_height / pixel_scale_y)
    finally:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(250)


def profile_dir(name: str, organization_id: int | None = None) -> Path:
    """Isole les profils Chromium persistants par organisation.

    Un ancien profil non cloisonné est déplacé une seule fois lors de sa
    première utilisation afin de préserver les sessions existantes.
    """
    profile_name = slugify(name, 40)
    if organization_id is None:
        return Path(settings.data_dir) / "profiles" / profile_name
    destination = (
        Path(settings.data_dir)
        / "organizations"
        / str(organization_id)
        / "profiles"
        / profile_name
    )
    legacy = Path(settings.data_dir) / "profiles" / profile_name
    if legacy.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(destination))
    return destination


async def capture_page(
    target: Target,
    destination: Path,
    account_storage: dict | None = None,
    account_profile_slug: str | None = None,
) -> CaptureResult:
    """Sérialise l'accès au coffre du compte, puis exécute la capture."""
    if account_profile_slug:
        async with get_profile_lock(account_profile_slug):
            return await _capture_page_impl(
                target,
                destination,
                account_storage=account_storage,
                account_profile_slug=account_profile_slug,
            )
    return await _capture_page_impl(target, destination, account_storage=account_storage)


async def _capture_page_impl(
    target: Target,
    destination: Path,
    account_storage: dict | None = None,
    account_profile_slug: str | None = None,
) -> CaptureResult:
    """Ouvre la page avec Chromium et ecrit la capture pleine page sur disque.

    Le coffre `account_profile_slug` est prioritaire. Il est ouvert en mémoire,
    utilisé comme profil persistant, puis rescellé après la navigation. La copie
    `account_storage` sert d'amorçage et est rafraîchie au retour.
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
    proxy = ssrf.playwright_proxy()

    work_dir: Path | None = None
    refreshed_storage: dict | None = None
    async with async_playwright() as pw:
        context_kwargs: dict = {
            "viewport": {"width": width, "height": height},
            "ignore_https_errors": True,
            # Les Service Workers peuvent court-circuiter l'interception
            # Playwright ; le proxy sortant reste actif, mais on les bloque
            # aussi ici pour que chaque requete passe par BrowserRequestGuard.
            "service_workers": "block",
        }
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        if target.locale:
            context_kwargs["locale"] = target.locale

        browser = None
        if account_profile_slug:
            # Compte connecté : le profil est déchiffré en RAM puis rescellé.
            # Cela conserve aussi les cookies que Facebook fait tourner pendant
            # une capture, contrairement à un contexte éphémère.
            profile_was_present = crypto.profile_exists(account_profile_slug)
            work_dir = crypto.open_profile(account_profile_slug)
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(work_dir), args=launch_args, proxy=proxy, **context_kwargs
                )
            except Exception:
                crypto.discard_profile(work_dir)
                raise
            if not profile_was_present and account_storage:
                cookies = account_storage.get("cookies") or []
                if cookies:
                    await context.add_cookies(cookies)
        elif account_storage is not None:
            # Compatibilité avec les appels sans compte nommé.
            browser = await pw.chromium.launch(args=launch_args, proxy=proxy)
            context_kwargs["storage_state"] = account_storage
            context = await browser.new_context(**context_kwargs)
        elif target.session_profile:
            # Profil persistant : les cookies rafraichis par le site sont conserves
            # d'une execution a l'autre (indispensable pour une session longue duree).
            udd = profile_dir(target.session_profile, target.organization_id)
            is_new_profile = not udd.exists()
            udd.mkdir(parents=True, exist_ok=True)
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(udd), args=launch_args, proxy=proxy, **context_kwargs
            )
            if is_new_profile and target.storage_state_json:
                state = session_state.parse_state(target.storage_state_json)
                if state and state.get("cookies"):
                    await context.add_cookies(state["cookies"])
        else:
            browser = await pw.chromium.launch(args=launch_args, proxy=proxy)
            if target.storage_state_json:
                state = session_state.parse_state(target.storage_state_json)
                if state:
                    context_kwargs["storage_state"] = state
            context = await browser.new_context(**context_kwargs)

        context.set_default_timeout(timeout)
        guard = await ssrf.install_browser_guard(context)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            try:
                response = await page.goto(
                    target.url, wait_until=target.wait_until, timeout=timeout
                )
            except Exception:
                guard.raise_if_blocked()
                raise
            guard.raise_if_blocked()
            if response is not None and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} sur {target.url}")

            if wait_after:
                await page.wait_for_timeout(wait_after)
            guard.raise_if_blocked()

            if account_profile_slug:
                lower_url = page.url.lower()
                if any(marker in lower_url for marker in ("checkpoint", "two_factor", "captcha")):
                    raise SessionExpired(
                        f"Facebook demande une vérification manuelle : {page.url}",
                        AccountStatus.verification_required,
                    )
                if any(marker in lower_url for marker in ("login", "recover")):
                    raise SessionExpired(
                        f"Facebook a déconnecté le compte : {page.url}",
                        AccountStatus.disconnected,
                    )

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

            scroll_steps = 0
            document_height = None
            screenshot_written = False
            # Règle générale : une capture pleine page charge d'abord les
            # contenus différés en descendant progressivement.
            if target.full_page and settings.auto_scroll_full_page:
                if requires_stitched_capture(page.url):
                    scroll_steps, document_height = await capture_stitched_page(
                        page,
                        destination,
                    )
                    screenshot_written = True
                else:
                    scroll_steps, document_height = await load_lazy_content(page)

            title = await page.title()
            final_url = page.url
            # Defense en profondeur : l'URL finale doit elle aussi rester
            # publique, meme si le moteur change son comportement de routage.
            await asyncio.to_thread(ssrf.check_url, final_url)
            guard.raise_if_blocked()
            # Métriques (abonnés, mentions J'aime…) depuis le texte de la page,
            # best-effort : un échec ici ne compromet jamais la capture.
            body_text = None
            try:
                body_text = await page.inner_text("body")
                metrics = parse_page_metrics(body_text) or None
            except Exception:  # noqa: BLE001
                metrics = None
            if not screenshot_written:
                await page.screenshot(path=str(destination), full_page=target.full_page)
            guard.raise_if_blocked()
        finally:
            if account_profile_slug:
                try:
                    refreshed_storage = await context.storage_state()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Export du storage_state impossible pour %s",
                        account_profile_slug,
                        exc_info=True,
                    )
            try:
                await context.close()
            finally:
                try:
                    if browser is not None:
                        await browser.close()
                finally:
                    if account_profile_slug and work_dir is not None:
                        try:
                            crypto.seal_profile(account_profile_slug, work_dir)
                        finally:
                            crypto.discard_profile(work_dir)

    data = destination.read_bytes()
    return CaptureResult(
        path=destination,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_title=title,
        final_url=final_url,
        metrics=metrics,
        body_text=body_text,
        storage_state=refreshed_storage,
        scroll_steps=scroll_steps,
        document_height=document_height,
    )
