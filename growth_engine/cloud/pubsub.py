from __future__ import annotations

import importlib
import json

from growth_engine.cloud.credentials import get_google_credentials
from growth_engine.config import Settings
from growth_engine.models import BusinessIntake

DEFAULT_PUBSUB_TOPIC = "growth-engine-runs"


class PubSubOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def publish_intake(self, intake: BusinessIntake) -> str:
        pubsub_v1 = importlib.import_module("google.cloud.pubsub_v1")

        project_id = self.settings.google_cloud_project
        credentials, credentials_project_id = get_google_credentials(self.settings)
        project_id = credentials_project_id or project_id
        if not project_id:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT is required for Pub/Sub orchestration."
            )
        publisher = pubsub_v1.PublisherClient(credentials=credentials)
        topic_path = publisher.topic_path(project_id, DEFAULT_PUBSUB_TOPIC)
        payload = json.dumps(
            {
                "business_name": intake.business_name,
                "website": intake.website,
                "description": intake.description,
                "industry": intake.industry,
                "location": intake.location,
                "target_geographies": intake.target_geographies,
                "budget": intake.budget,
                "ideal_customer_profile": intake.ideal_customer_profile,
                "preferred_company_sizes": intake.preferred_company_sizes,
                "preferred_sectors": intake.preferred_sectors,
                "offerings": intake.offerings,
                "goals": intake.goals,
                "discovery_modes": intake.discovery_modes,
                "opportunity_type_needed": intake.opportunity_type_needed,
                "inclusion_keywords": intake.inclusion_keywords,
                "exclusion_keywords": intake.exclusion_keywords,
                "vendor_constraints": intake.vendor_constraints,
                "supplier_constraints": intake.supplier_constraints,
                "user_urls": intake.user_urls,
            }
        ).encode("utf-8")
        message_id = publisher.publish(topic_path, payload).result()
        return str(message_id)
