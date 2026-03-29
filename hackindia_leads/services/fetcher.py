from __future__ import annotations

import threading
from dataclasses import dataclass

import requests

from hackindia_leads.config import Settings

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int | None
    text: str
    used_browser: bool


class PageFetcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread_local = threading.local()

    def _get_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            self._thread_local.session = session
        return session

    def fetch(self, url: str, prefer_browser: bool = False) -> FetchResult:
        if prefer_browser and self.settings.use_browser_fallback:
            browser_result = self._fetch_with_browser(url)
            if browser_result is not None:
                return browser_result

        try:
            response = self._get_session().get(
                url, timeout=self.settings.request_timeout_seconds
            )
        except requests.RequestException:
            return FetchResult(url=url, status_code=None, text="", used_browser=False)
        return FetchResult(
            url=url,
            status_code=response.status_code,
            text=response.text,
            used_browser=False,
        )

    def _fetch_with_browser(self, url: str) -> FetchResult | None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.settings.request_timeout_seconds * 1000,
                )
                html = page.content()
                browser.close()
                return FetchResult(
                    url=url, status_code=200, text=html, used_browser=True
                )
        except Exception:
            return None
