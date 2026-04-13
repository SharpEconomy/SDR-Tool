from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from growth_engine.models import (
    SOCIAL_CHANNELS,
    AuditRecord,
    SocialChannelContent,
    SocialContentRequest,
    SocialStrategy,
    SocialWorkflowResult,
)
from growth_engine.services.email_service import (
    EmailDeliveryService,
    EmailDeliveryUnavailableError,
)
from growth_engine.services.openai_service import ModelUnavailableError, OpenAIService
from growth_engine.services.search import SearchClient
from growth_engine.utils import dedupe_keep_order, normalize_whitespace, slugify

CHANNEL_LABELS = {
    "linkedin": "LinkedIn",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "twitter_x": "Twitter/X",
}


class SocialContentService:
    def __init__(
        self,
        settings,
        *,
        search_client: SearchClient | None = None,
        openai_service: OpenAIService | None = None,
        email_service: EmailDeliveryService | None = None,
    ) -> None:
        self.settings = settings
        self.search_client = search_client or SearchClient(settings)
        self.openai_service = openai_service or OpenAIService(settings)
        self.email_service = email_service or EmailDeliveryService(settings)

    def generate(
        self,
        *,
        draft,
        research_result,
        request: SocialContentRequest,
    ) -> SocialWorkflowResult:
        channels = _normalize_channels(request.channels)
        evidence = self._build_evidence(draft, research_result, request)
        strategy = self._create_strategy(draft, research_result, request, evidence)
        channel_content, email_subject = self._generate_content(
            draft,
            research_result,
            request,
            strategy,
            evidence,
        )

        email_error = None
        email_status = "sent"
        try:
            self.email_service.send_email(
                recipient=request.delivery_email,
                subject=email_subject,
                body=self._render_email_body(draft, request, strategy, channel_content),
            )
        except EmailDeliveryUnavailableError as exc:
            email_status = "failed"
            email_error = str(exc)

        created_at = datetime.now(UTC)
        audit_record = AuditRecord(
            run_id=(
                f"{slugify(draft.business_name or 'social-workflow')}-social-"
                f"{created_at.strftime('%Y%m%d%H%M%S')}"
            ),
            created_at=created_at,
            business_name=normalize_whitespace(draft.business_name or ""),
            discovery_modes=list(draft.discovery_modes),
            opportunity_count=0,
            skipped_count=0,
            export_name="No workbook",
            export_uri=None,
            log=[
                "Strategy created",
                f"Content created for {len(channels)} channels",
                f"Email delivery {email_status}",
            ],
            workflow_type="social_media_content",
            metadata={
                "campaign_goal": request.campaign_goal,
                "request_notes": request.notes,
                "delivery_email": request.delivery_email,
                "email_delivery_status": email_status,
                "email_delivery_error": email_error,
                "channels": channels,
                "channel_count": len(channels),
                "strategy": asdict(strategy),
                "channel_content": [asdict(item) for item in channel_content],
            },
        )
        return SocialWorkflowResult(
            strategy=strategy,
            channel_content=channel_content,
            delivery_email=request.delivery_email,
            email_subject=email_subject,
            email_status=email_status,
            email_error=email_error,
            audit_record=audit_record,
        )

    def _build_evidence(self, draft, research_result, request: SocialContentRequest):
        evidence = [
            {
                "kind": source.kind,
                "title": source.title,
                "url": source.url,
                "snippet": source.snippet,
            }
            for source in research_result.sources[:6]
        ]
        for result in self._supplemental_search_results(draft, request):
            evidence.append(
                {
                    "kind": "goal_search",
                    "title": result["title"],
                    "url": result["url"],
                    "snippet": result["snippet"],
                }
            )
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in evidence:
            key = normalize_whitespace(item.get("url", "")).lower()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped.append(item)
        return deduped[:10]

    def _supplemental_search_results(self, draft, request: SocialContentRequest):
        business_name = normalize_whitespace(draft.business_name or "")
        industry = normalize_whitespace(draft.industry or "")
        goal = normalize_whitespace(
            request.campaign_goal or next(iter(draft.goals or []), "")
        )
        queries = dedupe_keep_order(
            [
                " ".join(
                    part
                    for part in [business_name, goal or "growth", industry]
                    if normalize_whitespace(part)
                ),
                f'"{business_name}" customer pain points',
                f'"{business_name}" case study {industry}'.strip(),
            ]
        )
        results: list[dict[str, str]] = []
        for query in queries:
            for item in self.search_client.search(query, max_results=2):
                results.append(
                    {
                        "title": normalize_whitespace(item.title) or "Search result",
                        "url": normalize_whitespace(item.url),
                        "snippet": normalize_whitespace(item.snippet),
                    }
                )
                if len(results) >= 4:
                    return results
        return results

    def _create_strategy(
        self, draft, research_result, request, evidence
    ) -> SocialStrategy:
        payload = {
            "profile": asdict(draft),
            "verification_summary": research_result.verification_summary,
            "evidence": evidence,
            "campaign_goal": request.campaign_goal,
            "channels": request.channels,
            "notes": request.notes,
        }
        try:
            raw = (
                self.openai_service.create_social_strategy(payload)
                if self.openai_service.is_available()
                else {}
            )
        except ModelUnavailableError:
            raw = {}
        return self._normalize_strategy(raw, draft, request, evidence)

    def _generate_content(
        self,
        draft,
        research_result,
        request,
        strategy,
        evidence,
    ) -> tuple[list[SocialChannelContent], str]:
        payload = {
            "profile": asdict(draft),
            "verification_summary": research_result.verification_summary,
            "strategy": asdict(strategy),
            "channels": request.channels,
            "campaign_goal": request.campaign_goal,
            "notes": request.notes,
            "evidence": evidence,
        }
        try:
            raw = (
                self.openai_service.generate_social_content_bundle(payload)
                if self.openai_service.is_available()
                else {}
            )
        except ModelUnavailableError:
            raw = {}

        email_subject = normalize_whitespace(raw.get("email_subject", "")) or (
            f"{normalize_whitespace(draft.business_name or 'Business')} social content package"
        )
        channel_rows = (
            raw.get("channels") if isinstance(raw.get("channels"), list) else []
        )
        if not channel_rows:
            return (
                self._fallback_channel_content(draft, request, strategy),
                email_subject,
            )

        normalized: list[SocialChannelContent] = []
        for channel in _normalize_channels(request.channels):
            matching = next(
                (
                    item
                    for item in channel_rows
                    if normalize_whitespace(str(item.get("channel", ""))).lower()
                    == channel
                ),
                None,
            )
            if not isinstance(matching, dict):
                normalized.append(
                    self._fallback_channel_item(draft, channel, request, strategy)
                )
                continue
            normalized.append(
                SocialChannelContent(
                    channel=channel,
                    post_copy=clean_text(matching.get("post_copy"))
                    or self._fallback_post_copy(draft, channel, request),
                    reply_ideas=clean_list(matching.get("reply_ideas"))[:3]
                    or self._fallback_replies(draft, request),
                    image_prompt=clean_text(matching.get("image_prompt"))
                    or self._fallback_image_prompt(draft, strategy),
                    short_video_script=clean_text(matching.get("short_video_script"))
                    or self._fallback_video_script(draft, channel, strategy),
                    hashtags=clean_list(matching.get("hashtags"))[:6]
                    or self._fallback_hashtags(draft),
                )
            )
        return normalized, email_subject

    def _normalize_strategy(self, raw, draft, request, evidence) -> SocialStrategy:
        objective = clean_text(raw.get("objective")) or normalize_whitespace(
            request.campaign_goal or next(iter(draft.goals or []), "")
        )
        if not objective:
            objective = "Build qualified awareness and engagement"
        proof_points = clean_list(raw.get("proof_points")) or [
            normalize_whitespace(item.get("title") or item.get("snippet") or "")
            for item in evidence[:3]
            if normalize_whitespace(item.get("title") or item.get("snippet") or "")
        ]
        return SocialStrategy(
            objective=objective,
            audience_summary=clean_text(raw.get("audience_summary"))
            or normalize_whitespace(draft.ideal_customer_profile or "")
            or "Best-fit buyers and partners identified in the confirmed profile",
            brand_voice=clean_text(raw.get("brand_voice"))
            or f"Clear, credible, and {normalize_whitespace(draft.industry or 'industry-aware').lower()}-savvy",
            content_pillars=clean_list(raw.get("content_pillars"))
            or dedupe_keep_order(list(draft.offerings) + list(draft.goals))[:4],
            proof_points=proof_points[:4],
            calls_to_action=clean_list(raw.get("calls_to_action"))
            or [
                normalize_whitespace(draft.opportunity_type_needed or ""),
                "Start a conversation with the team",
            ],
            engagement_guidelines=clean_list(raw.get("engagement_guidelines"))
            or [
                "Reply in a human tone and reference the confirmed business profile.",
                "Do not automate posting or outreach from this workflow.",
                "Use proof points from the source evidence instead of generic claims.",
            ],
        )

    def _fallback_channel_content(self, draft, request, strategy):
        return [
            self._fallback_channel_item(draft, channel, request, strategy)
            for channel in _normalize_channels(request.channels)
        ]

    def _fallback_channel_item(self, draft, channel, request, strategy):
        return SocialChannelContent(
            channel=channel,
            post_copy=self._fallback_post_copy(draft, channel, request),
            reply_ideas=self._fallback_replies(draft, request),
            image_prompt=self._fallback_image_prompt(draft, strategy),
            short_video_script=self._fallback_video_script(draft, channel, strategy),
            hashtags=self._fallback_hashtags(draft),
        )

    def _fallback_post_copy(
        self, draft, channel: str, request: SocialContentRequest
    ) -> str:
        business_name = normalize_whitespace(draft.business_name or "This business")
        offering = next(iter(draft.offerings or []), "its core offering")
        goal = normalize_whitespace(
            request.campaign_goal or next(iter(draft.goals or []), "")
        )
        label = CHANNEL_LABELS.get(channel, channel.title())
        return (
            f"{label} post: {business_name} helps {normalize_whitespace(draft.ideal_customer_profile or 'target buyers')} "
            f"through {offering}. Focus this post on {goal or 'qualified awareness'}, use one concrete proof point, "
            "and end with a light-touch invitation to continue the conversation."
        )

    def _fallback_replies(self, draft, request: SocialContentRequest) -> list[str]:
        goal = normalize_whitespace(
            request.campaign_goal or next(iter(draft.goals or []), "")
        )
        return [
            "Thanks for the response. Happy to share more context on how this works in practice.",
            f"That is exactly the type of challenge this campaign is addressing around {goal or 'growth'}.",
            "If useful, we can share the relevant use case and next steps in a direct conversation.",
        ]

    def _fallback_image_prompt(self, draft, strategy: SocialStrategy) -> str:
        return (
            f"Create a clean marketing visual for {normalize_whitespace(draft.business_name or 'the brand')} "
            f"highlighting {', '.join(strategy.content_pillars[:2]) or 'the core offer'}, "
            "with product-led framing, editorial lighting, and room for overlay text."
        )

    def _fallback_video_script(
        self, draft, channel: str, strategy: SocialStrategy
    ) -> str:
        label = CHANNEL_LABELS.get(channel, channel.title())
        return (
            f"{label} short video script: Hook with the core problem in 3 seconds, "
            f"show how {normalize_whitespace(draft.business_name or 'the brand')} solves it, "
            f"highlight {', '.join(strategy.proof_points[:2]) or 'one proof point'}, "
            "and close with a manual CTA to message the team or visit the website."
        )

    def _fallback_hashtags(self, draft) -> list[str]:
        raw = [
            normalize_whitespace(draft.industry or "").replace(" ", ""),
            normalize_whitespace(next(iter(draft.offerings or []), "")).replace(
                " ", ""
            ),
            "GrowthMarketing",
            "DemandGeneration",
        ]
        return [f"#{item}" for item in dedupe_keep_order(raw) if item][:6]

    def _render_email_body(
        self,
        draft,
        request: SocialContentRequest,
        strategy: SocialStrategy,
        channel_content: list[SocialChannelContent],
    ) -> str:
        lines = [
            f"Social content package for {normalize_whitespace(draft.business_name or 'Business')}",
            "",
            f"Campaign goal: {strategy.objective}",
            f"Delivery target: {request.delivery_email}",
            "",
            "Strategy",
            f"- Audience: {strategy.audience_summary}",
            f"- Brand voice: {strategy.brand_voice}",
            f"- Content pillars: {', '.join(strategy.content_pillars)}",
            f"- Proof points: {', '.join(strategy.proof_points)}",
            f"- Calls to action: {', '.join(strategy.calls_to_action)}",
            "",
            "Posting note: Humans handle publishing. This package does not automate posting.",
        ]
        for item in channel_content:
            lines.extend(
                [
                    "",
                    f"{CHANNEL_LABELS.get(item.channel, item.channel.title())}",
                    f"Post: {item.post_copy}",
                    f"Reply ideas: {' | '.join(item.reply_ideas)}",
                    f"Image brief: {item.image_prompt}",
                    f"Short video: {item.short_video_script}",
                    f"Hashtags: {' '.join(item.hashtags)}",
                ]
            )
        return "\n".join(lines).strip()


def _normalize_channels(channels: list[str]) -> list[str]:
    allowed = {item for item in SOCIAL_CHANNELS}
    normalized = []
    for channel in channels:
        cleaned = normalize_whitespace(str(channel)).lower()
        if cleaned in allowed and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized or list(SOCIAL_CHANNELS)


def clean_text(value: object) -> str:
    return normalize_whitespace(str(value or ""))


def clean_list(value: object) -> list[str]:
    if isinstance(value, list):
        return dedupe_keep_order([str(item) for item in value])
    if isinstance(value, str):
        return dedupe_keep_order(
            [item.strip() for item in value.split(",") if item.strip()]
        )
    return []
