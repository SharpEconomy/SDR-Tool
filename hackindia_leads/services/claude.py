from __future__ import annotations

import json
from typing import Any

import requests

from hackindia_leads.config import Settings

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
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


class ClaudeQualificationClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def is_configured(self) -> bool:
        return bool(self.settings.anthropic_api_key and self.settings.anthropic_model)

    def qualify(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise RuntimeError(
                "ANTHROPIC_API_KEY and ANTHROPIC_MODEL are required when "
                "qualification is enabled."
            )

        text = self._send_json_prompt(
            QUALIFICATION_SYSTEM_PROMPT,
            (
                "Evaluate this sponsor qualification payload and return JSON only:\n"
                f"{json.dumps(payload, ensure_ascii=True)}"
            ),
        )
        if not text:
            raise RuntimeError("Claude returned an empty qualification response.")

        data = json.loads(self._extract_json(text))
        return {
            "accepted": bool(data.get("accepted")),
            "score": max(0, min(int(data.get("score", 0)), 100)),
            "recently_funded": bool(data.get("recently_funded")),
            "recent_funding_signal": data.get("recent_funding_signal"),
            "market_visibility_need": bool(data.get("market_visibility_need")),
            "qualification_notes": str(data.get("qualification_notes", "")).strip(),
        }

    def review_contacts(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise RuntimeError(
                "ANTHROPIC_API_KEY and ANTHROPIC_MODEL are required when "
                "contact review is enabled."
            )

        text = self._send_json_prompt(
            CONTACT_REVIEW_SYSTEM_PROMPT,
            (
                "Review these sponsorship contact candidates and return JSON only:\n"
                f"{json.dumps(payload, ensure_ascii=True)}"
            ),
        )
        if not text:
            raise RuntimeError("Claude returned an empty contact review response.")

        data = json.loads(self._extract_json(text))
        contacts = []
        for item in data.get("contacts", []):
            email = str(item.get("email", "")).strip().lower()
            if not email:
                continue
            contacts.append(
                {
                    "email": email,
                    "accepted": bool(item.get("accepted")),
                    "score": max(0, min(int(item.get("score", 0)), 100)),
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
        return {
            "contacts": contacts,
            "selection_notes": str(data.get("selection_notes", "")).strip(),
        }

    def _send_json_prompt(self, system_prompt: str, user_content: str) -> str:
        response = self.session.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": self.settings.anthropic_api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self.settings.anthropic_model,
                "max_tokens": 700,
                "temperature": 0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content_blocks = body.get("content", [])
        return "\n".join(
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ).strip()

    def _extract_json(self, text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise RuntimeError("Claude did not return a JSON object.")
        return text[start : end + 1]
