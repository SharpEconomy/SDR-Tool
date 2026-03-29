from __future__ import annotations

import json
from typing import Any

import requests

from hackindia_leads.config import Settings

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
QUALIFICATION_SYSTEM_PROMPT = """
You qualify hackathon sponsor targets for outbound sponsorship outreach.

Use only the supplied recent public evidence to make the final decision. Ignore
undated or older evidence. Prefer evidence from the last preferred window when
possible, and do not accept a company when the recent evidence is too weak or
stale.

Rule-based hints are included for relatively stable signals such as segment,
geography, and developer adoption motion. Treat those hints as trusted unless
the recent evidence clearly contradicts them.

Return JSON only with this exact shape:
{
  "accepted": true,
  "score": 0,
  "recently_funded": false,
  "recent_funding_signal": null,
  "market_visibility_need": false,
  "qualification_notes": ""
}

Rules:
- score must be an integer from 0 to 100.
- recently_funded is true only when the recent evidence explicitly supports it.
- recent_funding_signal must be null when recently_funded is false.
- market_visibility_need is true when the recent evidence shows launches,
  partnerships, ecosystem pushes, community expansion, developer go-to-market,
  or similar momentum where sponsorship helps.
- qualification_notes must be a short summary grounded in the supplied evidence.
""".strip()

CONTACT_REVIEW_SYSTEM_PROMPT = """
You review outbound sponsorship contact candidates for a company that already
passed deterministic website and email checks.

Use only the supplied evidence. Prefer named humans over generic inboxes when
the evidence supports their role. Favor founders, executives, partnerships,
ecosystem, developer relations, community, marketing, and growth contacts.
Reject contacts when the role is weak, generic, mismatched, or unsupported by
the supplied evidence.

Return JSON only with this exact shape:
{
  "contacts": [
    {
      "email": "",
      "accepted": true,
      "score": 0,
      "reason": ""
    }
  ],
  "selection_notes": ""
}

Rules:
- Include every candidate email exactly once.
- score must be an integer from 0 to 100.
- accepted is true only when the candidate is a plausible outreach target.
- reason must be a short evidence-grounded sentence.
- selection_notes must be a short overall summary.
- Respect max_selected by accepting at most that many contacts.
""".strip()

SPONSOR_EXTRACTION_SYSTEM_PROMPT = """
You extract real sponsor or partner companies from a hackathon event page.

Use only the supplied page evidence. Ignore call-to-action text, buttons,
registration prompts, organizer self-promotion, generic marketing copy, and
section headings that are not actual company names.

Return JSON only with this exact shape:
{
  "sponsors": [
    {
      "name": "",
      "website": null,
      "evidence": ""
    }
  ]
}

Rules:
- Include only real company or organization names that appear to sponsor or
  partner with the event.
- website must be null when there is no clear company URL.
- evidence must be a short phrase showing why the company was extracted.
- Do not include duplicate sponsors.
- Do not include the event organizer unless the page clearly lists it as a
  sponsor or partner.
""".strip()


class OpenAIQualificationClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def is_configured(self) -> bool:
        return bool(self.settings.openai_api_key and self.settings.openai_model)

    def qualify(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json_object(
            QUALIFICATION_SYSTEM_PROMPT,
            (
                "Evaluate this sponsor qualification payload and return JSON only:\n"
                f"{json.dumps(payload, ensure_ascii=True)}"
            ),
            missing_config_message=(
                "OPENAI_API_KEY and OPENAI_MODEL are required when "
                "qualification is enabled."
            ),
            empty_response_message="OpenAI returned an empty qualification response.",
        )
        return {
            "accepted": bool(data.get("accepted")),
            "score": self._clamp_score(data.get("score", 0)),
            "recently_funded": bool(data.get("recently_funded")),
            "recent_funding_signal": data.get("recent_funding_signal"),
            "market_visibility_need": bool(data.get("market_visibility_need")),
            "qualification_notes": str(data.get("qualification_notes", "")).strip(),
        }

    def review_contacts(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json_object(
            CONTACT_REVIEW_SYSTEM_PROMPT,
            (
                "Review these sponsorship contact candidates and return JSON only:\n"
                f"{json.dumps(payload, ensure_ascii=True)}"
            ),
            missing_config_message=(
                "OPENAI_API_KEY and OPENAI_MODEL are required when "
                "contact review is enabled."
            ),
            empty_response_message="OpenAI returned an empty contact review response.",
        )
        contacts = [
            contact
            for item in data.get("contacts", [])
            if (contact := self._normalize_contact_review(item)) is not None
        ]
        return {
            "contacts": contacts,
            "selection_notes": str(data.get("selection_notes", "")).strip(),
        }

    def extract_sponsors(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = self._request_json_object(
            SPONSOR_EXTRACTION_SYSTEM_PROMPT,
            (
                "Extract real event sponsors from this page payload and return "
                "JSON only:\n"
                f"{json.dumps(payload, ensure_ascii=True)}"
            ),
            missing_config_message=(
                "OPENAI_API_KEY and OPENAI_MODEL are required when "
                "sponsor extraction is enabled."
            ),
            empty_response_message=(
                "OpenAI returned an empty sponsor extraction response."
            ),
        )
        return [
            sponsor
            for item in data.get("sponsors", [])
            if (sponsor := self._normalize_sponsor(item)) is not None
        ]

    def _request_json_object(
        self,
        system_prompt: str,
        user_content: str,
        *,
        missing_config_message: str,
        empty_response_message: str,
    ) -> dict[str, Any]:
        self._require_configuration(missing_config_message)
        text = self._send_json_prompt(system_prompt, user_content)
        if not text:
            raise RuntimeError(empty_response_message)
        return json.loads(self._extract_json(text))

    def _require_configuration(self, missing_config_message: str) -> None:
        if not self.is_configured():
            raise RuntimeError(missing_config_message)

    def _normalize_contact_review(self, item: dict[str, Any]) -> dict[str, Any] | None:
        email = str(item.get("email", "")).strip().lower()
        if not email:
            return None
        return {
            "email": email,
            "accepted": bool(item.get("accepted")),
            "score": self._clamp_score(item.get("score", 0)),
            "reason": str(item.get("reason", "")).strip(),
        }

    def _normalize_sponsor(self, item: dict[str, Any]) -> dict[str, Any] | None:
        name = str(item.get("name", "")).strip()
        if not name:
            return None
        website = item.get("website")
        evidence = str(item.get("evidence", "")).strip() or None
        return {
            "name": name,
            "website": str(website).strip() if website else None,
            "evidence": evidence,
        }

    def _send_json_prompt(self, system_prompt: str, user_content: str) -> str:
        response = self.session.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.openai_model,
                "max_output_tokens": 700,
                "input": [
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": system_prompt,
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": user_content,
                            }
                        ],
                    },
                ],
                "text": {"format": {"type": "json_object"}},
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        return self._extract_output_text(body)

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
            raise RuntimeError("OpenAI did not return a JSON object.")
        return text[start : end + 1]

    def _clamp_score(self, value: Any) -> int:
        return max(0, min(int(value), 100))
