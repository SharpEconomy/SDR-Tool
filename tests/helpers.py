from __future__ import annotations

from dataclasses import asdict
from typing import Any

from django.test import Client

from growth_engine.models import IntakeDraft, ProfileResearchResult, ResearchSource


def localhost_client(**kwargs) -> Client:
    return Client(HTTP_HOST="localhost", **kwargs)


def enable_google_auth(settings) -> None:
    settings.google_sign_in_enabled = True
    settings.google_oauth_client_id = "google-client-id"
    settings.google_oauth_client_secret = "google-client-secret"


def build_intake_draft(**overrides: Any) -> IntakeDraft:
    base = {
        "business_name": "Demo Co",
        "website": "https://demo.example",
        "description": "B2B analytics platform",
        "industry": "Software",
        "location": "Mumbai, India",
        "target_geographies": ["India"],
        "budget": "Balanced",
        "ideal_customer_profile": "Ops teams",
        "preferred_company_sizes": ["SMB"],
        "preferred_sectors": ["Retail"],
        "offerings": ["Analytics"],
        "goals": ["Grow pipeline"],
        "discovery_modes": ["customers"],
        "opportunity_type_needed": "Qualified buyers",
        "inclusion_keywords": ["analytics"],
        "exclusion_keywords": [],
        "vendor_constraints": "None",
        "supplier_constraints": "None",
        "user_urls": ["https://demo.example"],
    }
    base.update(overrides)
    return IntakeDraft(**base)


def build_draft_payload(**overrides: Any) -> dict[str, Any]:
    return asdict(build_intake_draft(**overrides))


def build_research_source(**overrides: Any) -> ResearchSource:
    base = {
        "kind": "website",
        "url": "https://demo.example",
        "title": "Demo",
        "snippet": "B2B analytics platform",
    }
    base.update(overrides)
    return ResearchSource(**base)


def build_research_result(
    *,
    draft: IntakeDraft | None = None,
    sources: list[ResearchSource] | None = None,
    verification_summary: str = "Verified from website and search results.",
) -> ProfileResearchResult:
    effective_draft = draft or build_intake_draft()
    effective_sources = sources if sources is not None else [build_research_source()]
    return ProfileResearchResult(
        draft=effective_draft,
        sources=effective_sources,
        verification_summary=verification_summary,
    )


def build_research_result_payload(**draft_overrides: Any) -> dict[str, Any]:
    draft_payload = build_draft_payload(**draft_overrides)
    return {
        "draft": draft_payload,
        "sources": [asdict(build_research_source())],
        "verification_summary": "Verified from website and search results.",
    }
