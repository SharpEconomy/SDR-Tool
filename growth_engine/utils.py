from __future__ import annotations

import re
from urllib.parse import urlparse


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        cleaned = normalize_whitespace(item)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def clamp(value: float | int, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(int(round(value)), upper))


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    candidate = url if "://" in url else f"https://{url}"
    try:
        host = urlparse(candidate).netloc.lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    candidate = normalize_whitespace(url)
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"https://{host}{path}" if path else f"https://{host}"


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", normalize_whitespace(value).lower())
    return cleaned.strip("-")


def safe_first(items: list[str], default: str = "") -> str:
    return items[0] if items else default


def keyword_fragments(value: str, *, min_length: int = 3) -> list[str]:
    tokens = re.findall(
        r"[a-zA-Z0-9][a-zA-Z0-9+-]+", normalize_whitespace(value).lower()
    )
    blocked = {
        "and",
        "the",
        "with",
        "from",
        "that",
        "this",
        "into",
        "your",
        "need",
        "needs",
        "avoid",
        "prefer",
        "must",
    }
    return dedupe_keep_order(
        [token for token in tokens if len(token) >= min_length and token not in blocked]
    )
