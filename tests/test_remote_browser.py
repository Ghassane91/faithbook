"""Le navigateur distant reste opt-in, anonyme, borne et expurge de secrets."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.models import Target
from app.services import capture, remote_browser, ssrf
from app.services.web_challenges import WebChallenge


ENDPOINT = "wss://test-customer:password-ne-jamais-journaliser@brd.superproxy.io:9222"


@pytest.fixture
def remote_enabled(monkeypatch):
    monkeypatch.setattr(remote_browser.settings, "remote_browser_provider", "brightdata")
    monkeypatch.setattr(remote_browser.settings, "remote_browser_cdp_url", SecretStr(ENDPOINT))
    monkeypatch.setattr(remote_browser.settings, "remote_browser_domains",
                        "walmart.com,academy.com,basspro.com,cabelas.com")
    monkeypatch.setattr(remote_browser.settings, "remote_browser_timeout_seconds", 120)
    monkeypatch.setattr(remote_browser.settings, "allow_private_targets", False)


def target(**kwargs):
    return Target(name="Produit public", url="https://www.walmart.com/ip/123", **kwargs)


@pytest.mark.parametrize("url", [
    "https://walmart.com/ip/123", "https://WWW.WALMART.COM./ip/123",
    "https://shop.academy.com/p/tent", "https://www.basspro.com/shop/en/camera",
    "https://www.cabelas.com/", "http://academy.com/",
])
def test_selection_accepte_seulement_les_domaines_et_sous_domaines_configures(remote_enabled, url):
    item = target()
    item.url = url
    assert remote_browser.selected(item)


@pytest.mark.parametrize("url", [
    "https://evilwalmart.com/", "https://walmart.com.evil.example/",
    "https://walmart.com@evil.example/", "https://academy-com.example/",
    "https://www.facebook.com/", "file:///walmart.com", "ftp://walmart.com/",
    "https://127.0.0.1/", "https://example.com/?next=https://walmart.com/",
])
def test_selection_refuse_les_faux_domaines(remote_enabled, url):
    item = target()
    item.url = url
    assert not remote_browser.selected(item)


def test_fournisseur_inactif_par_defaut(monkeypatch):
    monkeypatch.setattr(remote_browser.settings, "remote_browser_provider", "disabled")
    assert not remote_browser.selected(target())


@pytest.mark.parametrize(("target_values", "arguments"), [
    ({"account_id": 42}, {}),
    ({"session_profile": "profil-connecte"}, {}),
    ({"storage_state_json": '{"cookies": []}'}, {}),
    ({}, {"account_storage": {}}),
    ({}, {"account_storage": {"cookies": [{"value": "secret"}]}}),
    ({}, {"account_profile_slug": "coffre-prive"}),
    ({}, {"identifiants": object()}),
])
def test_aucun_compte_ni_session_ne_part_au_fournisseur(remote_enabled, target_values, arguments):
    assert not remote_browser.selected(target(**target_values), **arguments)


def test_endpoint_est_un_secret_et_ne_fuit_pas_dans_la_configuration():
    config = Settings(_env_file=None, remote_browser_cdp_url=ENDPOINT)
    assert config.remote_browser_cdp_url.get_secret_value() == ENDPOINT
    for rendered in (repr(config), repr(config.model_dump()), config.model_dump_json()):
        assert ENDPOINT not in rendered
        assert "password-ne-jamais-journaliser" not in rendered


@pytest.mark.parametrize("value", ["", "https://brd.superproxy.io:9222", "ws://brd.superproxy.io",
                                   "wss://example.com", "wss://brd.superproxy.io/#secret",
                                   "wss://[malformed-ipv6"])
def test_endpoint_brightdata_refuse_les_valeurs_invalides_sans_les_afficher(remote_enabled, monkeypatch, value):
    monkeypatch.setattr(remote_browser.settings, "remote_browser_cdp_url", SecretStr(value))
    with pytest.raises(remote_browser.RemoteBrowserError) as error:
        remote_browser.endpoint()
    assert str(error.value) == "Configurer REMOTE_BROWSER_CDP_URL avec l'endpoint WSS du fournisseur."


def test_endpoint_generique_wss_et_refus_du_mode_reseau_prive(remote_enabled, monkeypatch):
    monkeypatch.setattr(remote_browser.settings, "remote_browser_provider", "cdp")
    generic = "wss://browser.example/connect?token=secret"
    monkeypatch.setattr(remote_browser.settings, "remote_browser_cdp_url", SecretStr(generic))
    assert remote_browser.endpoint() == generic
    monkeypatch.setattr(remote_browser.settings, "allow_private_targets", True)
    with pytest.raises(remote_browser.RemoteBrowserError, match="ALLOW_PRIVATE_TARGETS=false"):
        remote_browser.endpoint()


@pytest.mark.parametrize("values", [
    {"remote_browser_provider": "inconnu"},
    {"remote_browser_timeout_seconds": 14},
    {"remote_browser_timeout_seconds": 301},
])
def test_configuration_bornee(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_connexion_cree_un_contexte_neuf_avec_tls_verifie(remote_enabled):
    fresh = object()
    existing = object()
    browser = SimpleNamespace(contexts=[existing], new_context=AsyncMock(return_value=fresh), close=AsyncMock())
    connect = AsyncMock(return_value=browser)
    pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))
    options = {"viewport": {"width": 1280, "height": 720}, "ignore_https_errors": True,
               "service_workers": "block"}

    result_browser, result_context = await remote_browser.connect(pw, options)

    assert result_browser is browser
    assert result_context is fresh and result_context is not existing
    connect.assert_awaited_once_with(ENDPOINT, timeout=120_000)
    browser.new_context.assert_awaited_once_with(
        viewport={"width": 1280, "height": 720}, ignore_https_errors=False, service_workers="block"
    )
    assert options["ignore_https_errors"] is True
    browser.close.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("creation impossible"), asyncio.CancelledError()])
async def test_echec_creation_contexte_ferme_aussi_le_navigateur(remote_enabled, failure):
    browser = SimpleNamespace(new_context=AsyncMock(side_effect=failure), close=AsyncMock())
    pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)))
    with pytest.raises(type(failure)):
        await remote_browser.connect(pw, {})
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_erreur_fermeture_expurgee_des_journaux(caplog):
    resource = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError(ENDPOINT)))
    await remote_browser.close_safely(resource)
    assert "Fermeture du navigateur distant incomplete" in caplog.text
    assert ENDPOINT not in caplog.text
    assert "password-ne-jamais-journaliser" not in caplog.text


def response(status, frame, *, navigation=True):
    return SimpleNamespace(status=status, frame=frame,
                           request=SimpleNamespace(is_navigation_request=lambda: navigation))


class NavigationPage:
    def __init__(self):
        self.main_frame = object()
        self.listeners = {}
        self.initial = response(403, self.main_frame)
        self.wait_for_load_state = AsyncMock()
        self.goto = AsyncMock(side_effect=self._goto)

    def on(self, event, listener):
        self.listeners[event] = listener

    def remove_listener(self, event, listener):
        assert self.listeners[event] == listener
        del self.listeners[event]

    async def _goto(self, *args, **kwargs):
        self.listeners["response"](self.initial)
        return self.initial


@pytest.mark.asyncio
async def test_brightdata_attend_la_verification_et_utilise_la_nouvelle_reponse_principale(remote_enabled):
    page = NavigationPage()
    resolved = response(200, page.main_frame)

    async def solve(*args):
        page.listeners["response"](resolved)
        page.listeners["response"](response(429, object()))  # iframe
        page.listeners["response"](response(404, page.main_frame, navigation=False))  # image
        return {"status": "solved"}

    client = SimpleNamespace(send=AsyncMock(side_effect=solve))
    context = SimpleNamespace(new_cdp_session=AsyncMock(return_value=client))
    guard = SimpleNamespace(raise_if_blocked=Mock())
    item = target(wait_until="domcontentloaded")

    result = await remote_browser.navigate(page, context, item, 60_000, guard)

    assert result is resolved
    context.new_cdp_session.assert_awaited_once_with(page)
    client.send.assert_awaited_once_with("Captcha.waitForSolve", {"detectTimeout": 10_000})
    page.goto.assert_awaited_once_with(item.url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state.assert_awaited_once_with("domcontentloaded", timeout=60_000)
    assert guard.raise_if_blocked.call_count == 2
    assert page.listeners == {}


@pytest.mark.asyncio
async def test_cdp_generique_ne_lance_aucune_commande_proprietaire(remote_enabled, monkeypatch):
    monkeypatch.setattr(remote_browser.settings, "remote_browser_provider", "cdp")
    page = NavigationPage()
    context = SimpleNamespace(new_cdp_session=AsyncMock())
    result = await remote_browser.navigate(page, context, target(), 10_000,
                                           SimpleNamespace(raise_if_blocked=Mock()))
    assert result is page.initial
    context.new_cdp_session.assert_not_awaited()
    page.wait_for_load_state.assert_not_awaited()
    assert page.listeners == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "error"])
async def test_echec_fournisseur_reste_un_defi_et_retire_le_listener(remote_enabled, status):
    page = NavigationPage()
    client = SimpleNamespace(send=AsyncMock(return_value={"status": status, "detail": ENDPOINT}))
    context = SimpleNamespace(new_cdp_session=AsyncMock(return_value=client))
    with pytest.raises(WebChallenge) as error:
        await remote_browser.navigate(page, context, target(), 10_000,
                                      SimpleNamespace(raise_if_blocked=Mock()))
    assert ENDPOINT not in str(error.value)
    assert page.listeners == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://unapproved.example/?token=private",
                                   "https://user:password@walmart.com/", "http://127.0.0.1/"])
async def test_redirection_principale_hors_perimetre_bloquee_sans_url_secrete(remote_enabled, monkeypatch, url):
    public_check = Mock()
    monkeypatch.setattr(ssrf, "check_url", public_check)
    route = SimpleNamespace(abort=AsyncMock(), continue_=AsyncMock())
    request = SimpleNamespace(url=url, is_navigation_request=lambda: True,
                              frame=SimpleNamespace(parent_frame=None), resource_type="document")
    guard = remote_browser.RemoteRequestGuard()
    await guard.handle(route, request)
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()
    public_check.assert_not_called()
    with pytest.raises(ssrf.UrlRejected) as error:
        guard.raise_if_blocked()
    assert "hors des domaines autorises" in str(error.value)
    assert url not in str(error.value)


@pytest.mark.asyncio
async def test_sous_ressources_gardent_la_protection_ssrf(remote_enabled, monkeypatch):
    monkeypatch.setattr(ssrf, "check_url", Mock(side_effect=ssrf.UrlRejected("Adresse interne")))
    route = SimpleNamespace(abort=AsyncMock(), continue_=AsyncMock())
    request = SimpleNamespace(url="http://127.0.0.1/image", is_navigation_request=lambda: False,
                              resource_type="image")
    guard = remote_browser.RemoteRequestGuard()
    await guard.handle(route, request)
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()
    with pytest.raises(ssrf.UrlRejected, match="Adresse interne"):
        guard.raise_if_blocked()


@pytest.mark.asyncio
async def test_capture_distante_expurge_une_erreur_cdp_et_ne_retente_pas(remote_enabled, monkeypatch, tmp_path):
    impl = AsyncMock(side_effect=RuntimeError(f"Unable to connect to {ENDPOINT}"))
    monkeypatch.setattr(capture, "_capture_page_impl", impl)
    item = target()
    destination = tmp_path / "capture.jpg"
    with pytest.raises(remote_browser.RemoteBrowserError) as error:
        await capture.capture_page(item, destination)
    impl.assert_awaited_once_with(item, destination, use_remote=True)
    assert ENDPOINT not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__


@pytest.mark.asyncio
async def test_delai_total_annule_une_capture_bloquee_sans_reessai(remote_enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(remote_browser.settings, "remote_browser_timeout_seconds", 0.01)
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    impl = AsyncMock(side_effect=blocked)
    monkeypatch.setattr(capture, "_capture_page_impl", impl)
    with pytest.raises(remote_browser.RemoteBrowserError, match="delai depasse"):
        await asyncio.wait_for(capture.capture_page(target(), tmp_path / "capture.jpg"), timeout=1)
    assert cancelled.is_set()
    assert impl.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("target_values", "arguments"), [
    ({"account_id": 42}, {}), ({"session_profile": "profil-connecte"}, {}),
    ({"storage_state_json": '{"cookies": []}'}, {}), ({}, {"account_storage": {}}),
    ({}, {"account_profile_slug": "coffre-prive"}), ({}, {"identifiants": object()}),
])
async def test_capture_avec_session_reste_locale(remote_enabled, monkeypatch, tmp_path, target_values, arguments):
    result = object()
    impl = AsyncMock(return_value=result)
    monkeypatch.setattr(capture, "_capture_page_impl", impl)
    assert await capture.capture_page(target(**target_values), tmp_path / "capture.jpg", **arguments) is result
    assert impl.await_count == 1
    assert not impl.await_args.kwargs.get("use_remote", False)
    for key, value in arguments.items():
        assert impl.await_args.kwargs[key] is value


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [WebChallenge(), ssrf.UrlRejected("Navigation refusee"),
                                      remote_browser.RemoteBrowserError("Configuration invalide")])
async def test_capture_conserve_les_erreurs_structurees(remote_enabled, monkeypatch, tmp_path, failure):
    impl = AsyncMock(side_effect=failure)
    monkeypatch.setattr(capture, "_capture_page_impl", impl)
    with pytest.raises(type(failure)) as error:
        await capture.capture_page(target(), tmp_path / "capture.jpg")
    assert error.value is failure
    assert impl.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["challenge200", "guard", "navigation"])
async def test_capture_incomplete_ne_produit_pas_image_et_ferme_les_ressources(remote_enabled, monkeypatch, tmp_path, stage):
    monkeypatch.setattr(ssrf, "check_url", Mock())
    page = SimpleNamespace(
        title=AsyncMock(return_value="Robot or human?"),
        inner_text=AsyncMock(return_value="Please verify that you are human."),
        screenshot=AsyncMock(), url="https://www.walmart.com/ip/123",
    )
    context = SimpleNamespace(pages=[], new_page=AsyncMock(return_value=page),
                              set_default_timeout=Mock(), close=AsyncMock())
    browser = SimpleNamespace(close=AsyncMock())
    lifecycle = []

    @asynccontextmanager
    async def playwright():
        lifecycle.append("enter")
        try:
            yield object()
        finally:
            lifecycle.append("exit")

    monkeypatch.setattr(capture, "async_playwright", playwright)
    monkeypatch.setattr(remote_browser, "connect", AsyncMock(return_value=(browser, context)))
    guard = SimpleNamespace(raise_if_blocked=Mock())
    install = AsyncMock(return_value=guard)
    navigation = AsyncMock(return_value=SimpleNamespace(status=200))
    if stage == "guard":
        install.side_effect = RuntimeError("installation garde impossible")
    elif stage == "navigation":
        navigation.side_effect = RuntimeError("navigation impossible")
    monkeypatch.setattr(remote_browser, "install_guard", install)
    monkeypatch.setattr(remote_browser, "navigate", navigation)
    item = target(full_page=False, wait_after_load_ms=0)
    destination = tmp_path / "capture.jpg"

    with pytest.raises(WebChallenge if stage == "challenge200" else RuntimeError):
        await capture._capture_page_impl(item, destination, use_remote=True)

    page.screenshot.assert_not_awaited()
    assert not destination.exists()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    context.set_default_timeout.assert_called_once_with(120_000)
    assert lifecycle == ["enter", "exit"]
