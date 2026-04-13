from __future__ import annotations

import json
import time
from typing import Any

import requests

from growth_engine.config import Settings
from growth_engine.utils import clamp

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

SYSTEM_PROMPTS = {
    "targeting_model": (
        "You normalize business growth opportunity criteria. "
        "Return JSON only with concise inferred keywords, sectors, company_sizes, "
        "value_themes, and buying_signals. Use only supplied business context."
    ),
    "entity_extraction": (
        "You extract a business opportunity entity from messy public web content. "
        "Return JSON only with entity_name, category, description, location, "
        "company_size, budget_signal, trust_signals, timing_signals, "
        "accessibility_signals, and matched_keywords."
    ),
    "score_refinement": (
        "You refine business opportunity prioritization. Deterministic scores are "
        "already provided. Keep your output grounded in the provided facts, stay "
        "within a small adjustment range, and return JSON only with the shape "
        '{"opportunities":[{"priority_adjustment":0,"confidence_adjustment":0,'
        '"why_it_matters":"","next_action":""}]}.'
    ),
    "intake_extraction": (
        "You extract structured business intake data from a conversation update. "
        "Use only the user's latest answer plus the known draft. "
        "Return JSON only with keys for any fields you can confidently update: "
        "business_name, website, description, industry, location, "
        "target_geographies, budget, ideal_customer_profile, preferred_company_sizes, "
        "preferred_sectors, offerings, goals, discovery_modes, opportunity_type_needed, "
        "inclusion_keywords, exclusion_keywords, vendor_constraints, "
        "supplier_constraints, user_urls. Use arrays for list fields. "
        "Leave missing fields out. Prefer concise normalized values."
    ),
    "intake_question": (
        "You are an intake interviewer for a business growth decision engine. "
        "Ask one smart, concise next question that feels natural, avoids repetition, "
        "and follows from what is already known. Return JSON only with "
        '{"question":"","focus_fields":["field_name"],"rationale":""}.'
    ),
    "profile_verification": (
        "You verify a company's business profile from website and search evidence. "
        "Cross-check the evidence, prefer facts that appear on the primary website, "
        "and make one final grounded call. Return JSON only with keys: "
        "business_name, website, description, industry, location, target_geographies, "
        "budget, ideal_customer_profile, preferred_company_sizes, preferred_sectors, "
        "offerings, goals, discovery_modes, opportunity_type_needed, "
        "inclusion_keywords, exclusion_keywords, vendor_constraints, "
        "supplier_constraints, user_urls, verification_summary. "
        "Use arrays for list fields. If evidence is weak, use conservative defaults "
        "instead of inventing specifics."
    ),
    "social_strategy": (
        "You create a human-posted social media strategy for a business. "
        "Use only the supplied profile, website/search evidence, and request notes. "
        "Return JSON only with keys: objective, audience_summary, brand_voice, "
        "content_pillars, proof_points, calls_to_action, engagement_guidelines. "
        "Use concise strings and arrays. Ground proof_points in the supplied evidence."
    ),
    "social_content_bundle": (
        "You generate channel-ready social content for a human team to post manually. "
        "Use the supplied business profile, evidence, strategy, and requested channels. "
        "Return JSON only with keys: email_subject, channels. "
        "channels must be an array of objects with keys: channel, post_copy, "
        "reply_ideas, image_prompt, short_video_script, hashtags. "
        "Keep each channel tailored to its format, avoid inventing facts, and make "
        "visual/video outputs creative briefs or scripts rather than automation steps."
    ),
}


class ModelUnavailableError(RuntimeError):
    """Raised when the model layer cannot be used."""


class OpenAIService:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def is_available(self) -> bool:
        return bool(
            self.settings.openai_enabled
            and self.settings.openai_api_key
            and self.settings.openai_model
        )

    def infer_targeting_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="targeting_model",
            payload=payload,
            max_output_tokens=500,
        )

    def extract_entity(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="entity_extraction",
            payload=payload,
            max_output_tokens=800,
        )

    def refine_scores(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="score_refinement",
            payload=payload,
            max_output_tokens=1200,
        )

    def extract_intake_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="intake_extraction",
            payload=payload,
            max_output_tokens=900,
        )

    def generate_intake_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="intake_question",
            payload=payload,
            max_output_tokens=400,
        )

    def verify_business_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="profile_verification",
            payload=payload,
            max_output_tokens=1400,
        )

    def create_social_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="social_strategy",
            payload=payload,
            max_output_tokens=1200,
        )

    def generate_social_content_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            prompt_name="social_content_bundle",
            payload=payload,
            max_output_tokens=2600,
        )

    def _request_json(
        self,
        *,
        prompt_name: str,
        payload: dict[str, Any],
        max_output_tokens: int,
    ) -> dict[str, Any]:
        if not self.is_available():
            raise ModelUnavailableError("OpenAI is not configured for this run.")
        response = None
        for attempt in range(1, self.settings.request_retry_attempts + 2):
            try:
                response = self.session.post(
                    OPENAI_RESPONSES_URL,
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.openai_model,
                        "reasoning": {"effort": self.settings.openai_reasoning_effort},
                        "max_output_tokens": max_output_tokens,
                        "input": [
                            {
                                "role": "system",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": SYSTEM_PROMPTS[prompt_name],
                                    }
                                ],
                            },
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": json.dumps(payload, ensure_ascii=True),
                                    }
                                ],
                            },
                        ],
                        "text": {"format": {"type": "json_object"}},
                    },
                    timeout=self.settings.request_timeout_seconds,
                )
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt > self.settings.request_retry_attempts:
                    raise ModelUnavailableError(str(exc)) from exc
                time.sleep(self.settings.request_retry_backoff_seconds * attempt)
        body = response.json()
        output_text = body.get("output_text") or self._extract_output_text(body)
        if not output_text:
            raise ModelUnavailableError("OpenAI returned an empty response.")
        try:
            return json.loads(self._extract_json(output_text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ModelUnavailableError("OpenAI returned invalid JSON.") from exc

    def _extract_output_text(self, body: dict[str, Any]) -> str:
        texts: list[str] = []
        for item in body.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text = str(content.get("text", "")).strip()
                    if text:
                        texts.append(text)
        return "\n".join(texts).strip()

    def _extract_json(self, text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found.")
        return text[start : end + 1]


def bounded_adjustment(value: Any, lower: int = -10, upper: int = 10) -> int:
    return clamp(int(value), lower, upper)
