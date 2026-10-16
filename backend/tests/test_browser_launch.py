import asyncio
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

from crawlers import engine
from crawlers import cbp_fetch


class FakeChromium:
    def __init__(self, *, chrome_works: bool = True):
        self.attempts: list[dict] = []
        self.chrome_works = chrome_works
        self.browser = object()

    async def launch(self, **options):
        self.attempts.append(options)
        if options.get("channel") == "chrome" and self.chrome_works:
            return self.browser
        raise PlaywrightError("browser executable missing")


def test_missing_chromium_falls_back_to_chrome(monkeypatch):
    monkeypatch.delenv("CRAWLER_BROWSER", raising=False)
    monkeypatch.setattr(engine, "_chromium_executable", lambda: "C:/missing/chrome.exe")
    chromium = FakeChromium()

    result = asyncio.run(engine._launch_browser(SimpleNamespace(chromium=chromium), headless=True, slow_mo=0))

    assert result is chromium.browser
    assert len(chromium.attempts) == 3
    assert chromium.attempts[0]["executable_path"] == "C:/missing/chrome.exe"
    assert "channel" not in chromium.attempts[1]
    assert chromium.attempts[2]["channel"] == "chrome"


def test_chrome_can_be_selected_first(monkeypatch):
    monkeypatch.setenv("CRAWLER_BROWSER", "chrome")
    monkeypatch.setattr(engine, "_chromium_executable", lambda: "C:/project/chrome.exe")
    chromium = FakeChromium()

    result = asyncio.run(engine._launch_browser(SimpleNamespace(chromium=chromium), headless=False, slow_mo=100))

    assert result is chromium.browser
    assert len(chromium.attempts) == 1
    assert chromium.attempts[0] == {"headless": False, "slow_mo": 100, "channel": "chrome"}


def test_all_browser_failures_are_reported(monkeypatch):
    monkeypatch.delenv("CRAWLER_BROWSER", raising=False)
    monkeypatch.setattr(engine, "_chromium_executable", lambda: None)
    chromium = FakeChromium(chrome_works=False)

    with pytest.raises(RuntimeError, match="所有浏览器均启动失败") as error:
        asyncio.run(engine._launch_browser(SimpleNamespace(chromium=chromium), headless=True, slow_mo=0))

    assert "Playwright Chromium" in str(error.value)
    assert "Google Chrome" in str(error.value)


def test_cli_returns_nonzero_when_crawl_fails(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cbp_fetch"])
    monkeypatch.setattr(cbp_fetch, "configure_logging", lambda *args, **kwargs: None)

    async def failed_crawl(**kwargs):
        return {"errors": ["all browsers failed"]}

    monkeypatch.setattr(cbp_fetch, "crawl_cbp", failed_crawl)
    with pytest.raises(SystemExit) as result:
        asyncio.run(cbp_fetch.main())

    assert result.value.code == 1
