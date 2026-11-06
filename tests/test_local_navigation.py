from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import Error

from app.models import Target
from app.services import capture, local_navigation as nav
from app.services.web_challenges import WebChallenge, _BROWSER_REASON, _HUMAN_REASON


@pytest.mark.parametrize("url,expected", [
    ("https://www.walmart.com/", True),
    ("https://academy.com/", True),
    ("https://www.basspro.com/home", True),
    ("https://cabelas.com/", True),
    ("https://walmart.com.attacker.test/", False),
    ("file:///academy.com", False),
])
def test_domains(url, expected):
    assert nav.supported(url) == expected


def page_fixture(status=200):
    response = SimpleNamespace(status=status)
    page = SimpleNamespace(goto=AsyncMock(return_value=response), on=Mock(), remove_listener=Mock())
    return page, response, SimpleNamespace(raise_if_blocked=Mock())


@pytest.mark.asyncio
async def test_autonomous_check_waits_without_reloading(monkeypatch):
    page, response, guard = page_fixture()
    check = AsyncMock(side_effect=[WebChallenge(_BROWSER_REASON), None])
    monkeypatch.setattr(nav, "assert_no_challenge", check)
    monkeypatch.setattr(nav.asyncio, "sleep", AsyncMock())
    result = await nav.navigate(page, Target(url="https://academy.com/"), 1000, guard, 20)
    assert result is response
    assert check.await_count == 2
    page.goto.assert_awaited_once()
    page.remove_listener.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,grace,status", [(_HUMAN_REASON, 20, 200), (_BROWSER_REASON, 0, 200), (_BROWSER_REASON, 20, 429)])
async def test_blocked_page_does_not_loop(monkeypatch, reason, grace, status):
    page, _, guard = page_fixture(status)
    check = AsyncMock(side_effect=WebChallenge(reason))
    monkeypatch.setattr(nav, "assert_no_challenge", check)
    with pytest.raises(WebChallenge):
        await nav.navigate(page, Target(url="https://academy.com/"), 1000, guard, grace)
    assert check.await_count <= 1
    page.remove_listener.assert_called_once()


@pytest.mark.asyncio
async def test_http2_retry_is_single_and_local(monkeypatch, tmp_path):
    result = object()
    implementation = AsyncMock(side_effect=[Error("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR"), result])
    monkeypatch.setattr(capture, "_capture_page_impl", implementation)
    assert await capture.capture_page(Target(url="https://academy.com/"), tmp_path / "test.jpg") is result
    assert implementation.await_count == 2
    assert implementation.await_args.kwargs["disable_http2"] is True


@pytest.mark.asyncio
async def test_challenge_never_retries(monkeypatch, tmp_path):
    implementation = AsyncMock(side_effect=WebChallenge())
    monkeypatch.setattr(capture, "_capture_page_impl", implementation)
    with pytest.raises(WebChallenge):
        await capture.capture_page(Target(url="https://academy.com/"), tmp_path / "test.jpg")
    implementation.assert_awaited_once()
