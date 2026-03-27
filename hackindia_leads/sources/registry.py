from __future__ import annotations

from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.search import SearchClient
from hackindia_leads.sources.devpost import DevpostSource
from hackindia_leads.sources.dorahacks import DoraHacksSource
from hackindia_leads.sources.ethglobal import EthGlobalSource
from hackindia_leads.sources.mlh import MLHSource


def build_sources(
    fetcher: PageFetcher, search_client: SearchClient
) -> dict[str, object]:
    return {
        "ethglobal": EthGlobalSource(fetcher, search_client),
        "devpost": DevpostSource(fetcher, search_client),
        "dorahacks": DoraHacksSource(fetcher, search_client),
        "mlh": MLHSource(fetcher, search_client),
    }
