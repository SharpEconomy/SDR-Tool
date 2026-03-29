from __future__ import annotations

from hackindia_leads.utils import (
    dedupe_keep_order,
    extract_domain,
    is_likely_prize_label,
    looks_like_company_name,
    normalize_whitespace,
)


def test_normalize_whitespace_collapses_spaces() -> None:
    assert normalize_whitespace("  hello \n world\t ") == "hello world"


def test_dedupe_keep_order_is_case_insensitive() -> None:
    assert dedupe_keep_order(["ENS", "ens", " Polygon ", "polygon"]) == [
        "ENS",
        "Polygon",
    ]


def test_extract_domain_strips_www() -> None:
    assert extract_domain("https://www.openai.com/docs") == "openai.com"


def test_extract_domain_handles_missing_value() -> None:
    assert extract_domain(None) is None


def test_looks_like_company_name_filters_prize_label() -> None:
    assert not looks_like_company_name("Prizes")
    assert looks_like_company_name("Polygon")


def test_is_likely_prize_label_handles_non_dollar_currency() -> None:
    assert is_likely_prize_label("EUR 5,000 Award") is True
    assert is_likely_prize_label("€ 5,000 Prize") is True
