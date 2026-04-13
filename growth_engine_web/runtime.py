from __future__ import annotations

from growth_engine.config import Settings


def get_runtime_settings() -> Settings:
    return Settings.load()
