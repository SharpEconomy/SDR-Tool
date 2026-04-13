from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from growth_engine.cloud.credentials import get_google_credentials
from growth_engine.config import Settings
from growth_engine.profile_flow import format_discovery_mode_label
from growth_engine.storage.artifacts import _import_google_cloud_module
from growth_engine.utils import normalize_whitespace


@dataclass(slots=True)
class AnalyticsMetric:
    label: str
    value: str
    detail: str


@dataclass(slots=True)
class AdminAnalyticsSnapshot:
    metrics: list[AnalyticsMetric]
    recent_profiles: list[dict[str, str]]
    recent_runs: list[dict[str, str]]
    discovery_breakdown: list[dict[str, object]]
    industry_breakdown: list[dict[str, object]]
    availability_notes: list[str]

    @property
    def has_data(self) -> bool:
        return bool(self.recent_profiles or self.recent_runs)


def build_admin_analytics_snapshot(settings: Settings) -> AdminAnalyticsSnapshot:
    profiles = _load_collection_documents(
        settings,
        settings.firestore_profile_collection,
        limit=120,
    )
    runs: list[dict[str, Any]] = []
    availability_notes: list[str] = []
    if settings.audit_backend == "firestore":
        runs = _load_collection_documents(
            settings,
            settings.firestore_collection,
            limit=120,
        )
    else:
        availability_notes.append(
            "Audit analytics are empty because audit persistence is not using "
            "Firestore."
        )

    if not profiles:
        availability_notes.append("No confirmed profiles were found in Firestore yet.")

    if settings.audit_backend == "firestore" and not runs:
        availability_notes.append(
            "No Firestore audit runs were found yet for the configured collection."
        )

    return AdminAnalyticsSnapshot(
        metrics=_build_metrics(profiles, runs),
        recent_profiles=_recent_profiles(profiles),
        recent_runs=_recent_runs(runs),
        discovery_breakdown=_discovery_breakdown(profiles),
        industry_breakdown=_industry_breakdown(profiles),
        availability_notes=availability_notes,
    )


def _build_metrics(
    profiles: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> list[AnalyticsMetric]:
    now = datetime.now(UTC)
    recent_profiles = sum(
        1
        for profile in profiles
        if (parsed := _parse_datetime(profile.get("confirmed_at")))
        and parsed >= now - timedelta(days=7)
    )
    unique_operators = {
        normalize_whitespace(str(profile.get("confirmed_by") or "")).lower()
        for profile in profiles
        if normalize_whitespace(str(profile.get("confirmed_by") or ""))
    }
    total_opportunities = sum(_safe_int(run.get("opportunity_count")) for run in runs)
    average_opportunities = total_opportunities / len(runs) if runs else 0
    return [
        AnalyticsMetric(
            label="Confirmed profiles",
            value=str(len(profiles)),
            detail="Profiles saved to the Firestore workspace.",
        ),
        AnalyticsMetric(
            label="Last 7 days",
            value=str(recent_profiles),
            detail="Profiles confirmed in the trailing week.",
        ),
        AnalyticsMetric(
            label="Operators",
            value=str(len(unique_operators)),
            detail="Distinct confirmed-by emails across saved profiles.",
        ),
        AnalyticsMetric(
            label="Decision runs",
            value=str(len(runs)),
            detail="Audit records available from the run collection.",
        ),
        AnalyticsMetric(
            label="Opportunities surfaced",
            value=str(total_opportunities),
            detail="Summed prioritized opportunities across saved runs.",
        ),
        AnalyticsMetric(
            label="Avg. opportunities",
            value=f"{average_opportunities:.1f}" if runs else "0.0",
            detail="Average prioritized opportunities per available run.",
        ),
    ]


def _recent_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, str]]:
    ranked = sorted(
        profiles,
        key=lambda item: _parse_datetime(item.get("confirmed_at"))
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    output: list[dict[str, str]] = []
    for item in ranked[:8]:
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        output.append(
            {
                "business_name": _fallback_text(
                    profile.get("business_name"),
                    "Unnamed business",
                ),
                "industry": _fallback_text(
                    profile.get("industry"),
                    "Industry not set",
                ),
                "location": _fallback_text(
                    profile.get("location"),
                    "Location not set",
                ),
                "confirmed_by": _fallback_text(
                    item.get("confirmed_by"),
                    "Unknown operator",
                ),
                "confirmed_at": _format_timestamp(item.get("confirmed_at")),
                "discovery_modes": ", ".join(
                    _discovery_mode_labels(profile.get("discovery_modes"))
                ),
            }
        )
    return output


def _recent_runs(runs: list[dict[str, Any]]) -> list[dict[str, str]]:
    ranked = sorted(
        runs,
        key=lambda item: _parse_datetime(item.get("created_at"))
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    output: list[dict[str, str]] = []
    for item in ranked[:8]:
        output.append(
            {
                "business_name": _fallback_text(
                    item.get("business_name"),
                    "Unknown business",
                ),
                "created_at": _format_timestamp(item.get("created_at")),
                "discovery_modes": ", ".join(
                    _discovery_mode_labels(item.get("discovery_modes"))
                ),
                "opportunity_count": str(_safe_int(item.get("opportunity_count"))),
                "skipped_count": str(_safe_int(item.get("skipped_count"))),
                "export_name": _fallback_text(
                    item.get("export_name"),
                    "No workbook",
                ),
            }
        )
    return output


def _discovery_breakdown(profiles: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    for item in profiles:
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        for mode in profile.get("discovery_modes", []) or []:
            normalized = normalize_whitespace(str(mode))
            if normalized:
                counts[format_discovery_mode_label(normalized)] += 1
    return _counter_rows(counts)


def _industry_breakdown(profiles: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    for item in profiles:
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        label = _fallback_text(profile.get("industry"), "Not specified")
        counts[label] += 1
    return _counter_rows(counts)


def _counter_rows(counter: Counter[str]) -> list[dict[str, object]]:
    if not counter:
        return []
    largest = max(counter.values()) or 1
    return [
        {
            "label": label,
            "count": count,
            "width": max(16, round((count / largest) * 100)),
        }
        for label, count in counter.most_common(8)
    ]


def _load_collection_documents(
    settings: Settings,
    collection_name: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not collection_name:
        return []
    firestore = _import_google_cloud_module(
        "google.cloud.firestore",
        "google-cloud-firestore",
    )
    credentials, project_id = get_google_credentials(settings)
    client = firestore.Client(
        project=project_id or None,
        credentials=credentials,
        database=settings.firestore_database,
    )
    documents: list[dict[str, Any]] = []
    for snapshot in client.collection(collection_name).limit(limit).stream():
        payload = snapshot.to_dict()
        if isinstance(payload, dict):
            documents.append(payload)
    return documents


def _discovery_mode_labels(raw_modes: object) -> list[str]:
    if not isinstance(raw_modes, list):
        return []
    return [
        format_discovery_mode_label(normalize_whitespace(str(mode)))
        for mode in raw_modes
        if normalize_whitespace(str(mode))
    ]


def _format_timestamp(value: object) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return "Unknown time"
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    normalized = normalize_whitespace(str(value or ""))
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fallback_text(value: object, fallback: str) -> str:
    cleaned = normalize_whitespace(str(value or ""))
    return cleaned or fallback
