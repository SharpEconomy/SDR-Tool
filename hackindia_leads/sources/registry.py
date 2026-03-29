from __future__ import annotations

from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.search import SearchClient
from hackindia_leads.sources.base import SourceAdapter
from hackindia_leads.sources.custom import CustomWebsiteSource
from hackindia_leads.sources.devpost import DevpostSource
from hackindia_leads.sources.dorahacks import DoraHacksSource
from hackindia_leads.sources.ethglobal import EthGlobalSource
from hackindia_leads.sources.mlh import MLHSource


def build_sources(
    fetcher: PageFetcher,
    search_client: SearchClient,
    custom_urls: list[str] | None = None,
) -> dict[str, SourceAdapter]:
    sources: dict[str, SourceAdapter] = {
        "ethglobal": EthGlobalSource(fetcher, search_client),
        "devpost": DevpostSource(fetcher, search_client),
        "dorahacks": DoraHacksSource(fetcher, search_client),
        "mlh": MLHSource(fetcher, search_client),
    }
    if custom_urls:
        sources["custom"] = CustomWebsiteSource(fetcher, search_client, custom_urls)
    return sources
