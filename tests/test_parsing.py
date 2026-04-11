from __future__ import annotations

from datetime import UTC, datetime

from growth_engine.models import DiscoveryDocument
from growth_engine.parsing import HtmlParsingService


def test_html_parser_extracts_core_fields() -> None:
    parser = HtmlParsingService()
    document = DiscoveryDocument(
        adapter_name="public_web",
        source_type="public_web",
        discovery_mode="customers",
        url="https://example.com",
        title="Example Retail - Partner with us",
        snippet="Retail partner network India",
        html="""
        <html>
          <head>
            <title>Example Retail - Partner with us</title>
            <meta name="description" content="Retail distribution company serving India." />
          </head>
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

    assert parsed.likely_entity_name == "Example Retail"
    assert parsed.meta_description == "Retail distribution company serving India."
    assert "hello@example.com" in parsed.emails
    assert parsed.likely_location == "India"
