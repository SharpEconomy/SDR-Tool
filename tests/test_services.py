from __future__ import annotations

import requests

from growth_engine.services.fetcher import PageFetcher
from growth_engine.services.openai_service import OpenAIService
from growth_engine.services.search import SearchClient


class _FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code
        self.text = "<html></html>"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestException("boom")

    def json(self):
        return self.payload


def test_fetcher_retries_once_on_request_error(settings, monkeypatch) -> None:
    fetcher = PageFetcher(settings)
    calls = {"count": 0}

    class _Session:
        headers = {}

        def get(self, url, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise requests.RequestException("fail")
            return _FakeResponse()

    monkeypatch.setattr(fetcher, "_get_session", lambda: _Session())

    result = fetcher.fetch("https://example.com")

    assert calls["count"] == 2
    assert result.status_code == 200


def test_search_client_retries_google_request(settings, monkeypatch) -> None:
    settings.google_search_api_key = "key"
    settings.google_search_engine_id = "cx"
    client = SearchClient(settings)
    calls = {"count": 0}

    class _Session:
        def get(self, url, params, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise requests.RequestException("fail")
            return _FakeResponse(
                {
                    "items": [
                        {
                            "title": "Example",
                            "link": "https://example.com",
                            "snippet": "Retail buyer India",
                        }
                    ]
                }
            )

    client.session = _Session()

    results = client.search("retail buyer india")

    assert calls["count"] == 2
    assert results[0].url == "https://example.com"


def test_openai_service_retries_once(settings) -> None:
    calls = {"count": 0}

    class _Session:
        def post(self, url, headers, json, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise requests.RequestException("fail")
            return _FakeResponse({"output_text": '{"keywords":["retail"]}'})

    service = OpenAIService(settings, _Session())

    result = service.infer_targeting_model({"business_name": "Demo"})

    assert calls["count"] == 2
    assert result == {"keywords": ["retail"]}
