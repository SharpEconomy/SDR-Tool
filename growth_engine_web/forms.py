from __future__ import annotations

from django import forms

from growth_engine.models import DISCOVERY_MODES, SOCIAL_CHANNELS
from growth_engine.profile_flow import (
    FIELD_HELP_TEXT,
    FIELD_LABELS,
    LIST_FIELDS,
    MULTILINE_FIELDS,
    WRAPPED_LIST_FIELDS,
    clean_requested_modes,
    coerce_field_value,
)
from growth_engine.utils import normalize_whitespace


class SourceResearchForm(forms.Form):
    business_name = forms.CharField(
        label="Business name",
        max_length=160,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Aarohan Foods",
                "autocomplete": "organization",
            }
        ),
    )
    website = forms.CharField(
        label="Website",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "placeholder": "aarohanfoods.example",
                "inputmode": "url",
                "autocomplete": "url",
            }
        ),
    )

    def clean_business_name(self) -> str:
        return normalize_whitespace(self.cleaned_data["business_name"])

    def clean_website(self) -> str:
        return normalize_whitespace(self.cleaned_data["website"])


class ProfileSectionForm(forms.Form):
    def __init__(self, *args, field_names: tuple[str, ...], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.field_names = field_names
        for field_name in field_names:
            widget = forms.TextInput(attrs={"autocomplete": "off"})
            if field_name in LIST_FIELDS:
                rows = 5 if field_name in WRAPPED_LIST_FIELDS else 4
                widget = forms.Textarea(attrs={"rows": rows})
            elif field_name in MULTILINE_FIELDS:
                widget = forms.Textarea(attrs={"rows": 5})

            self.fields[field_name] = forms.CharField(
                label=FIELD_LABELS[field_name],
                help_text=FIELD_HELP_TEXT[field_name],
                required=False,
                widget=widget,
            )

    def cleaned_partial_values(self) -> dict[str, object]:
        return {
            field_name: coerce_field_value(field_name, self.cleaned_data[field_name])
            for field_name in self.field_names
        }


class PostSaveRequestForm(forms.Form):
    requested_data = forms.MultipleChoiceField(
        label="Choose one or more data types",
        required=False,
        choices=[(mode, mode.replace("_", " ").title()) for mode in DISCOVERY_MODES],
        widget=forms.CheckboxSelectMultiple,
    )
    notes = forms.CharField(
        label="Anything specific you want in that data?",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Example: only India-based distributors with verified websites.",
            }
        ),
    )

    def clean_requested_data(self) -> list[str]:
        return clean_requested_modes(
            list(self.cleaned_data.get("requested_data", []) or [])
        )

    def clean_notes(self) -> str:
        return normalize_whitespace(self.cleaned_data.get("notes", ""))


class SocialContentRequestForm(forms.Form):
    campaign_goal = forms.CharField(
        label="Primary social campaign goal",
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Example: build awareness with retail buyers in India.",
                "autocomplete": "off",
            }
        ),
    )
    channels = forms.MultipleChoiceField(
        label="Choose one or more social channels",
        required=False,
        choices=[
            (channel, channel.replace("_", " ").replace("x", "X").title())
            for channel in SOCIAL_CHANNELS
        ],
        widget=forms.CheckboxSelectMultiple,
    )
    notes = forms.CharField(
        label="Anything specific for the content package?",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Example: focus on product education and practical reply ideas.",
            }
        ),
    )
    delivery_email = forms.EmailField(
        label="Email the package to",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "operator@example.com",
                "autocomplete": "email",
            }
        ),
    )

    def clean_campaign_goal(self) -> str:
        return normalize_whitespace(self.cleaned_data.get("campaign_goal", ""))

    def clean_channels(self) -> list[str]:
        allowed = {channel for channel in SOCIAL_CHANNELS}
        selected = list(self.cleaned_data.get("channels", []) or [])
        return [channel for channel in selected if channel in allowed] or list(
            SOCIAL_CHANNELS
        )

    def clean_notes(self) -> str:
        return normalize_whitespace(self.cleaned_data.get("notes", ""))

    def clean_delivery_email(self) -> str:
        return normalize_whitespace(self.cleaned_data.get("delivery_email", "")).lower()
