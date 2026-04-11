from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from growth_engine.models import BusinessProfile, DiscoveryDocument


class DiscoveryAdapter(ABC):
    name: str
    source_type: str

    @abstractmethod
    def discover(
        self,
        profile: BusinessProfile,
        discovery_mode: str,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[DiscoveryDocument]:
        raise NotImplementedError
