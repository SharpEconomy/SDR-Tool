from __future__ import annotations

from functools import lru_cache

from growth_engine.config import Settings


@lru_cache(maxsize=1)
def get_runtime_settings() -> Settings:
    return Settings.load()
