from __future__ import annotations

import json
import logging
from typing import Any


def get_logger(name: str = "growth_engine") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **payload: Any) -> None:
    logger.info(json.dumps({"event": event, **payload}, default=str, ensure_ascii=True))
