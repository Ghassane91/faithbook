"""Bright Data Browser API: fresh public session, bounded capture, no credentials logged."""
import asyncio
import base64
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from app.config import settings
from app.services import remote_browser
from app.services.browser_links import public_url


def endpoint():
    try:
        value = Path(settings.brightdata_browser_endpoint_file).read_text().strip()
        parsed = urlsplit(value)
        if (parsed.scheme != 'wss' or parsed.hostname != 'brd.superproxy.io'
                or parsed.port != 9222 or not parsed.username or not parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or settings.allow_private_targets):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise ValueError('Endpoint Browser API absent ou invalide dans le fichier secret.') from None


def configured():
    try:
        endpoint()
        return True
    except ValueError:
        return False


def eligible(url):
    return settings.brightdata_browser_enabled and remote_browser.domain_allowed(url)


async def capture_document(page, context, url, guard):
    """Keep HTML and screenshot in one session; reject challenge/error before saving."""
    from app.services.brightdata_capture import validate_page
    latest = [None]

    def record(response):
        if response.request.is_navigation_request() and response.frame == page.main_frame:
            latest[0] = response

    page.on('response', record)
    try:
        client = await context.new_cdp_session(page)
        await page.goto(url, wait_until='domcontentloaded', timeout=60_000)
        guard.raise_if_blocked()
        result = await client.send('Captcha.waitForSolve', {'detectTimeout': 10_000})
        if result.get('status') not in ('solved', 'not_detected'):
            raise ValueError('Browser API : vérification humaine non résolue.')
        await page.wait_for_load_state('domcontentloaded', timeout=30_000)
        # Trigger lazy images without following an unbounded infinite scroll.
        for step in range(16):
            done = await page.evaluate('''() => {
                window.scrollBy(0, 800);
                return window.scrollY + innerHeight >= document.documentElement.scrollHeight;
            }''')
            await page.wait_for_timeout(250)
            if done:
                break
        await page.evaluate('window.scrollTo(0, 0)')
        await page.wait_for_function('''() => [...document.images].filter(i =>
            i.getBoundingClientRect().width >= 120 && i.getBoundingClientRect().height >= 80
        ).every(i => i.complete && i.naturalWidth > 0)''', timeout=15_000)
        guard.raise_if_blocked()
        document = {'url': page.url, 'browserHtml': await page.content(),
                    'statusCode': latest[0].status if latest[0] else 0,
                    'capture_engine': 'browser_api'}
        if not latest[0] or document['statusCode'] != 200:
            raise ValueError('Browser API : page indisponible.')
        validate_page(document, url)
        height = await page.evaluate('document.documentElement.scrollHeight')
        if height > 20000:
            raise ValueError('Browser API : page trop longue pour une capture complète.')
        image = await page.screenshot(type='png', full_page=True, timeout=30_000)
        guard.raise_if_blocked()
        if len(image) > 20_000_000:
            raise ValueError('Browser API : image trop volumineuse.')
        # Reject a navigation between DOM validation and screenshot.
        if page.url != document['url']:
            raise ValueError('Browser API : navigation pendant la capture.')
        document['screenshot'] = base64.b64encode(image).decode('ascii')
        return document
    finally:
        page.remove_listener('response', record)


async def extract_async(url):
    browser = context = None
    connection = endpoint()
    url = public_url(url)
    if not eligible(url):
        raise ValueError('Browser API : domaine non activé.')
    try:
        async with async_playwright() as pw:
            try:
                async with asyncio.timeout(settings.remote_browser_timeout_seconds):
                    browser = await pw.chromium.connect_over_cdp(connection, timeout=30_000)
                    context = await browser.new_context(viewport={'width': 1440, 'height': 1000},
                                                        ignore_https_errors=False, service_workers='block')
                    guard = await remote_browser.install_guard(context)
                    page = await context.new_page()
                    return await capture_document(page, context, url, guard)
            finally:
                await remote_browser.close_safely(context)
                await remote_browser.close_safely(browser)
    except Exception:
        # Provider exceptions may include the credential-bearing CDP URL.
        raise ValueError('Browser API : capture non validée (accès, délai, images ou configuration).') from None


def extract(url):
    return asyncio.run(extract_async(url))
