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
    workflow_breakdown: list[dict[str, object]]
    social_channel_breakdown: list[dict[str, object]]
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
    runs = _load_collection_documents(
        settings,
        settings.firestore_collection,
        limit=160,
    )
    availability_notes: list[str] = []

    if not profiles:
        availability_notes.append("No confirmed profiles were found in Firestore yet.")

    if not runs:
        availability_notes.append(
            "No Firestore workflow records were found yet for the configured collection."
        )

    return AdminAnalyticsSnapshot(
        metrics=_build_metrics(profiles, runs),
        recent_profiles=_recent_profiles(profiles),
        recent_runs=_recent_runs(runs),
        discovery_breakdown=_discovery_breakdown(profiles),
        industry_breakdown=_industry_breakdown(profiles),
        workflow_breakdown=_workflow_breakdown(runs),
        social_channel_breakdown=_social_channel_breakdown(runs),
        availability_notes=availability_notes,
    )


def _build_metrics(
    profiles: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> list[AnalyticsMetric]:
    now = datetime.now(UTC)
    recent_profiles_count = sum(
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
    lead_runs = [run for run in runs if _workflow_type(run) == "lead_generation"]
    social_runs = [run for run in runs if _workflow_type(run) == "social_media_content"]
    total_opportunities = sum(
        _safe_int(run.get("opportunity_count")) for run in lead_runs
    )
    social_emails_sent = sum(
        1
        for run in social_runs
        if _run_metadata(run).get("email_delivery_status") == "sent"
    )
    return [
        AnalyticsMetric(
            label="Confirmed profiles",
            value=str(len(profiles)),
            detail="Profiles saved to the Firestore workspace.",
        ),
        AnalyticsMetric(
            label="Last 7 days",
            value=str(recent_profiles_count),
            detail="Profiles confirmed in the trailing week.",
        ),
        AnalyticsMetric(
            label="Operators",
            value=str(len(unique_operators)),
            detail="Distinct confirmed-by emails across saved profiles.",
        ),
        AnalyticsMetric(
            label="Lead workflows",
            value=str(len(lead_runs)),
            detail="Lead-generation workflow records stored in Firestore.",
        ),
        AnalyticsMetric(
            label="Opportunities surfaced",
            value=str(total_opportunities),
            detail="Summed prioritized leads across lead workflow runs.",
        ),
        AnalyticsMetric(
            label="Social emails sent",
            value=str(social_emails_sent),
            detail="Social content packages successfully emailed to operators.",
        ),
        AnalyticsMetric(
            label="Social workflows",
            value=str(len(social_runs)),
            detail="Social strategy and content workflow records stored in Firestore.",
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
        workflow_type = _workflow_type(item)
        metadata = _run_metadata(item)
        output.append(
            {
                "business_name": _fallback_text(
                    item.get("business_name"),
                    "Unknown business",
                ),
                "workflow_type": _workflow_type_label(workflow_type),
                "created_at": _format_timestamp(item.get("created_at")),
                "discovery_modes": ", ".join(
                    _discovery_mode_labels(item.get("discovery_modes"))
                ),
                "primary_label": (
                    "Prioritized" if workflow_type == "lead_generation" else "Channels"
                ),
                "primary_value": (
                    str(_safe_int(item.get("opportunity_count")))
                    if workflow_type == "lead_generation"
                    else str(
                        _safe_int(metadata.get("channel_count"))
                        or len(metadata.get("channels", []) or [])
                    )
                ),
                "secondary_label": (
                    "Skipped" if workflow_type == "lead_generation" else "Email"
                ),
                "secondary_value": (
                    str(_safe_int(item.get("skipped_count")))
                    if workflow_type == "lead_generation"
                    else _fallback_text(
                        metadata.get("email_delivery_status"),
                        "Unknown",
                    )
                    .replace("_", " ")
                    .title()
                ),
                "artifact_label": (
                    "Workbook" if workflow_type == "lead_generation" else "Delivery"
                ),
                "artifact_name": (
                    _fallback_text(item.get("export_name"), "No workbook")
                    if workflow_type == "lead_generation"
                    else _fallback_text(
                        metadata.get("delivery_email"),
                        "No delivery target",
                    )
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


def _workflow_breakdown(runs: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    for item in runs:
        counts[_workflow_type_label(_workflow_type(item))] += 1
    return _counter_rows(counts)


def _social_channel_breakdown(runs: list[dict[str, Any]]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    for item in runs:
        if _workflow_type(item) != "social_media_content":
            continue
        for channel in _run_metadata(item).get("channels", []) or []:
            label = _workflow_channel_label(str(channel))
            if label:
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


def _run_metadata(run: dict[str, Any]) -> dict[str, Any]:
    return run.get("metadata") if isinstance(run.get("metadata"), dict) else {}


def _workflow_type(run: dict[str, Any]) -> str:
    value = normalize_whitespace(str(run.get("workflow_type") or "")).lower()
    return value or "lead_generation"


def _workflow_type_label(value: str) -> str:
    return (
        "Social Media Content" if value == "social_media_content" else "Lead Generation"
    )


def _workflow_channel_label(channel: str) -> str:
    normalized = normalize_whitespace(channel).lower()
    if not normalized:
        return ""
    return "Twitter/X" if normalized == "twitter_x" else normalized.title()


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
