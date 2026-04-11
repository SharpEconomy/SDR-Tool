from __future__ import annotations

from growth_engine.intake import BusinessProfileBuilder


class _FakeOpenAIService:
    def is_available(self) -> bool:
        return True

    def infer_targeting_model(self, payload):
        return {
            "keywords": payload["base_model"]["keywords"] + ["modern trade"],
            "sectors": ["Retail", "Distribution"],
            "company_sizes": ["SMB"],
            "value_themes": ["Expand into modern trade"],
            "buying_signals": ["buyer", "expansion"],
        }


def test_business_profile_builder_normalizes_and_refines(intake) -> None:
    builder = BusinessProfileBuilder(_FakeOpenAIService())

    profile = builder.build(intake)

    assert profile.website == "https://aarohanfoods.example"
    assert profile.domain == "aarohanfoods.example"
    assert "modern trade" in profile.targeting_model.keywords
    assert profile.discovery_modes == ["customers", "partners"]
