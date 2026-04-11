from __future__ import annotations

from datetime import UTC, datetime

from growth_engine.enrichment import OpportunityEnricher
from growth_engine.intake import BusinessProfileBuilder
from growth_engine.models import DiscoveryDocument
from growth_engine.parsing import HtmlParsingService


class _FakeEmailValidator:
    def validate(self, email, include_smtp_probe=False, include_mx_lookup=True):
        from growth_engine.models import ContactValidation

        return ContactValidation(True, True, None, None)


class _FakeSearchClient:
    def __init__(self, results):
        self.results = results

    def search(self, query: str, max_results: int = 5):
        return self.results[:max_results]


def test_enricher_builds_contact_paths_and_decision_maker(
    intake, linkedin_search_result
) -> None:
    profile = BusinessProfileBuilder().build(intake)
    parser = HtmlParsingService()
    document = DiscoveryDocument(
        adapter_name="public_web",
        source_type="public_web",
        discovery_mode="partners",
        url="https://example.com",
        title="Example Retail - Partner with us",
        snippet="Retail partner network India",
        html="""
        <html>
          <head><title>Example Retail - Partner with us</title></head>
          <body>
            <h1>Example Retail</h1>
            <a href="/contact">Contact</a>
            Reach us at hello@example.com
          </body>
        </html>
        """,
        status_code=200,
        fetched_at=datetime.now(UTC),
    )
    parsed = parser.parse(document)
    enricher = OpportunityEnricher(
        _FakeSearchClient(linkedin_search_result), _FakeEmailValidator()
    )

    entity = enricher.enrich(
        profile, "partners", "public_web", document.url, parsed, document.snippet
    )

    assert entity.entity_name == "Example Retail"
    assert any(path.label == "hello@example.com" for path in entity.contact_paths)
    assert entity.contact_paths[0].kind == "decision_maker_email"
    assert entity.decision_maker_email == "riya.sharma@example.com"


def test_enricher_respects_exclusion_keywords(intake, linkedin_search_result) -> None:
    intake.exclusion_keywords = ["retail"]
    profile = BusinessProfileBuilder().build(intake)
    parser = HtmlParsingService()
    document = DiscoveryDocument(
        adapter_name="public_web",
        source_type="public_web",
        discovery_mode="customers",
        url="https://example.com",
        title="Example Retail",
        snippet="Retail buyer India",
        html="<html><body><h1>Example Retail</h1></body></html>",
        status_code=200,
        fetched_at=datetime.now(UTC),
    )
    parsed = parser.parse(document)
    enricher = OpportunityEnricher(
        _FakeSearchClient(linkedin_search_result), _FakeEmailValidator()
    )

    entity = enricher.enrich(
        profile, "customers", "public_web", document.url, parsed, document.snippet
    )

    assert entity.excluded is True
    assert entity.exclusion_reason == "Matched exclusion keyword: retail"
