from __future__ import annotations

from growth_engine_web.analytics import build_admin_analytics_snapshot


def test_build_admin_analytics_snapshot_aggregates_profiles_and_runs(
    settings,
    monkeypatch,
) -> None:
    settings.audit_backend = "firestore"

    def _fake_loader(runtime_settings, collection_name: str, *, limit: int):
        if collection_name == settings.firestore_profile_collection:
            return [
                {
                    "confirmed_at": "2026-04-13T10:00:00+00:00",
                    "confirmed_by": "admin@example.com",
                    "profile": {
                        "business_name": "Demo Co",
                        "industry": "Software",
                        "location": "Mumbai, India",
                        "discovery_modes": ["customers", "partners"],
                    },
                },
                {
                    "confirmed_at": "2026-04-10T08:30:00+00:00",
                    "confirmed_by": "ops@example.com",
                    "profile": {
                        "business_name": "Apex Foods",
                        "industry": "Food and beverage",
                        "location": "Delhi, India",
                        "discovery_modes": ["customers"],
                    },
                },
            ]
        return [
            {
                "business_name": "Demo Co",
                "created_at": "2026-04-13T10:30:00+00:00",
                "discovery_modes": ["customers"],
                "opportunity_count": 4,
                "skipped_count": 2,
                "export_name": "demo.xlsx",
            }
        ]

    monkeypatch.setattr(
        "growth_engine_web.analytics._load_collection_documents",
        _fake_loader,
    )

    snapshot = build_admin_analytics_snapshot(settings)

    assert snapshot.metrics[0].value == "2"
    assert snapshot.metrics[3].value == "1"
    assert snapshot.metrics[4].value == "4"
    assert snapshot.discovery_breakdown[0]["label"] == "Customers"
    assert snapshot.discovery_breakdown[0]["count"] == 2
    assert snapshot.industry_breakdown[0]["label"] == "Software"
    assert snapshot.recent_profiles[0]["business_name"] == "Demo Co"
    assert snapshot.recent_runs[0]["export_name"] == "demo.xlsx"
