from __future__ import annotations

import re
from urllib.parse import urlparse


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item.strip())
    return output


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = f"https://{url}"
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def is_likely_prize_label(value: str) -> bool:
    cleaned = normalize_whitespace(value)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if re.fullmatch(r"\d+(st|nd|rd|th)\s+(place|prize|winner)", lowered):
        return True
    blocked_fragments = (
        "prize",
        "prizes",
        "bounty",
        "winner",
        "winners",
        "in cash",
        "cash",
        "usd",
        "usdc",
        "award",
        "awards",
    )
    if any(fragment in lowered for fragment in blocked_fragments):
        return True
    return bool(re.search(r"[$\u20ac\u00a3\u20b9]\s*\d", cleaned))


def looks_like_company_name(value: str) -> bool:
    cleaned = normalize_whitespace(value)
    if len(cleaned) < 2 or len(cleaned) > 80:
        return False
    if is_likely_prize_label(cleaned):
        return False
    blocked_tokens = {
        "apply",
        "register",
        "view details",
        "learn more",
        "deadline",
        "schedule",
        "judges",
        "criteria",
        "questions",
        "resources",
        "requirements",
        "terms",
        "faq",
        "overview",
        "track",
        "tracks",
        "prize",
        "prizes",
    }
    if cleaned.lower() in blocked_tokens:
        return False
    return any(char.isalpha() for char in cleaned)
