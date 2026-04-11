from __future__ import annotations

import base64
import json
from typing import Any

from growth_engine.config import Settings
from growth_engine.models import BusinessIntake, DecisionRunResult
from growth_engine.orchestration import DecisionEngine


def intake_from_payload(payload: dict[str, Any]) -> BusinessIntake:
    return BusinessIntake(
        business_name=str(payload.get("business_name", "")),
        website=str(payload.get("website", "")),
        description=str(payload.get("description", "")),
        industry=str(payload.get("industry", "")),
        location=str(payload.get("location", "")),
        target_geographies=list(payload.get("target_geographies", []) or []),
        budget=str(payload.get("budget", "")),
        ideal_customer_profile=str(payload.get("ideal_customer_profile", "")),
        preferred_company_sizes=list(payload.get("preferred_company_sizes", []) or []),
        preferred_sectors=list(payload.get("preferred_sectors", []) or []),
        offerings=list(payload.get("offerings", []) or []),
        goals=list(payload.get("goals", []) or []),
        discovery_modes=list(payload.get("discovery_modes", []) or []),
        opportunity_type_needed=str(payload.get("opportunity_type_needed", "")),
        inclusion_keywords=list(payload.get("inclusion_keywords", []) or []),
        exclusion_keywords=list(payload.get("exclusion_keywords", []) or []),
        vendor_constraints=str(payload.get("vendor_constraints", "")),
        supplier_constraints=str(payload.get("supplier_constraints", "")),
        user_urls=list(payload.get("user_urls", []) or []),
    )


def summarize_result(result: DecisionRunResult) -> dict[str, Any]:
    return {
        "business_name": result.profile.business_name,
        "opportunity_count": len(result.opportunities),
        "skipped_count": len(result.skipped_entities),
        "top_opportunities": [
            {
                "entity_name": item.entity_name,
                "priority_score": item.priority_score,
                "why_it_matters": item.why_it_matters,
                "next_action": item.next_action,
            }
            for item in result.opportunities[:5]
        ],
        "export_name": result.export_name,
        "export_uri": result.export_uri,
        "run_id": result.audit_record.run_id,
    }


def run_decision_job(
    payload: dict[str, Any], settings: Settings | None = None
) -> dict[str, Any]:
    effective_settings = settings or Settings.load()
    engine = DecisionEngine(effective_settings)
    result = engine.run(intake_from_payload(payload))
    return summarize_result(result)


def pubsub_decision_handler(
    event: dict[str, Any], context: Any | None = None
) -> dict[str, Any]:
    data = event.get("data", "")
    decoded = base64.b64decode(data).decode("utf-8") if data else "{}"
    payload = json.loads(decoded)
    return run_decision_job(payload)
