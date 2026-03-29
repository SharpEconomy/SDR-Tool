from __future__ import annotations

from types import SimpleNamespace

import requests

from hackindia_leads.services.fetcher import FetchResult, PageFetcher


def test_fetch_uses_browser_result_when_available(settings, monkeypatch) -> None:
    fetcher = PageFetcher(settings)
    browser_result = FetchResult(
        url="https://example.com",
        status_code=200,
        text="<html></html>",
        used_browser=True,
    )
    monkeypatch.setattr(fetcher, "_fetch_with_browser", lambda url: browser_result)

    result = fetcher.fetch("https://example.com", prefer_browser=True)

    assert result is browser_result


def test_fetch_uses_browser_fallback_off_main_thread(settings, monkeypatch) -> None:
    fetcher = PageFetcher(settings)
    browser_result = FetchResult(
        url="https://example.com",
        status_code=200,
        text="<html>browser</html>",
        used_browser=True,
    )
    monkeypatch.setattr(
        fetcher,
        "_fetch_with_browser",
        lambda url: browser_result,
    )
    monkeypatch.setattr(
        fetcher._get_session(),
        "get",
        lambda url, timeout: (_ for _ in ()).throw(
            RuntimeError("requests should not run")
        ),
    )

    result = fetcher.fetch("https://example.com", prefer_browser=True)

    assert result is browser_result


def test_fetch_uses_requests_response(settings, monkeypatch) -> None:
    fetcher = PageFetcher(settings)
    response = SimpleNamespace(status_code=200, text="payload")
    monkeypatch.setattr(fetcher._get_session(), "get", lambda url, timeout: response)

    result = fetcher.fetch("https://example.com")

    assert result.status_code == 200
    assert result.text == "payload"
    assert result.used_browser is False


def test_fetch_falls_back_to_requests_when_browser_runtime_is_unavailable(
    settings, monkeypatch
) -> None:
    fetcher = PageFetcher(settings)
    response = SimpleNamespace(status_code=200, text="payload")
    monkeypatch.setattr(fetcher, "_prepare_browser_runtime", lambda: False)
    monkeypatch.setattr(fetcher._get_session(), "get", lambda url, timeout: response)

    result = fetcher.fetch("https://example.com", prefer_browser=True)

    assert result.status_code == 200
    assert result.text == "payload"
    assert result.used_browser is False


def test_fetch_returns_empty_result_on_request_error(settings, monkeypatch) -> None:
    fetcher = PageFetcher(settings)

    def raise_error(url, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr(fetcher._get_session(), "get", raise_error)

    result = fetcher.fetch("https://example.com")

    assert result.status_code is None
    assert result.text == ""
