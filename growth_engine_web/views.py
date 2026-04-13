from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from urllib.parse import quote, urljoin
from uuid import uuid4

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from growth_engine.models import DISCOVERY_MODES, BusinessIntake
from growth_engine.orchestration import DecisionEngine
from growth_engine.profile_flow import (
    build_research_document_id,
    build_summary_cards,
    form_initial_for_fields,
    format_discovery_mode_label,
    get_summary_card_config,
    normalize_error_message,
    update_draft_from_partial_values,
)
from growth_engine.profile_research import BusinessProfileResearcher
from growth_engine.storage import (
    FirestoreProfileStore,
    NoOpArtifactStore,
    NoOpAuditStore,
)
from growth_engine.utils import normalize_whitespace
from growth_engine_web.analytics import build_admin_analytics_snapshot
from growth_engine_web.forms import (
    PostSaveRequestForm,
    ProfileSectionForm,
    SourceResearchForm,
)
from growth_engine_web.google_auth import (
    GOOGLE_OAUTH_STATE_KEY,
    GoogleAuthenticationError,
    build_google_oauth_authorization_url,
    create_google_oauth_state,
    exchange_google_code,
    google_auth_is_configured,
    verify_google_id_token,
)
from growth_engine_web.runtime import get_runtime_settings
from growth_engine_web.session_state import (
    BUSINESS_NAME_INPUT_KEY,
    PROFILE_SAVE_URI_KEY,
    WEBSITE_INPUT_KEY,
    clear_lead_results,
    clear_workspace_state,
    get_auth_user,
    get_draft,
    get_lead_export_bytes,
    get_lead_results,
    get_post_save_request,
    get_research_result,
    set_auth_user,
    set_draft,
    set_lead_results,
    set_post_save_request,
    set_research_result,
)


def _auth_is_required() -> bool:
    return google_auth_is_configured()


APP_BOOT_ID = uuid4().hex


def _is_admin_request(request: HttpRequest) -> bool:
    django_user = getattr(request, "user", None)
    if getattr(django_user, "is_authenticated", False) and (
        getattr(django_user, "is_staff", False)
        or getattr(django_user, "is_superuser", False)
    ):
        return True

    current_user = get_auth_user(request.session) or {}
    current_email = normalize_whitespace(str(current_user.get("email") or "")).lower()
    if not current_email:
        return False

    settings = get_runtime_settings()
    allowed_emails = {
        normalize_whitespace(email).lower() for email in settings.admin_emails
    }
    return current_email in allowed_emails


def _home_context(
    request: HttpRequest,
    *,
    source_form: SourceResearchForm | None = None,
) -> dict[str, object]:
    draft = get_draft(request.session)
    research_result = get_research_result(request.session)
    post_save_request = get_post_save_request(request.session)
    effective_requested_data = list(
        post_save_request["requested_data"]
        or (list(draft.discovery_modes) if draft else [])
    )
    current_user = get_auth_user(request.session)
    lead_results = get_lead_results(request.session)

    if source_form is None:
        source_form = SourceResearchForm(
            initial={
                "business_name": request.session.get(BUSINESS_NAME_INPUT_KEY, ""),
                "website": request.session.get(WEBSITE_INPUT_KEY, ""),
            }
        )

    return {
        "auth_required": _auth_is_required(),
        "current_user": current_user,
        "can_access_admin_analytics": _is_admin_request(request),
        "source_form": source_form,
        "draft": draft,
        "research_result": research_result,
        "summary_cards": build_summary_cards(draft) if draft else [],
        "save_uri": request.session.get(PROFILE_SAVE_URI_KEY),
        "discovery_mode_options": [
            (mode, format_discovery_mode_label(mode)) for mode in DISCOVERY_MODES
        ],
        "requested_data_selected": effective_requested_data,
        "post_save_form": PostSaveRequestForm(
            initial={
                "requested_data": post_save_request["requested_data"],
                "notes": post_save_request["notes"],
            }
        ),
        "lead_results": lead_results,
        "requested_data_summary": ", ".join(
            format_discovery_mode_label(mode) for mode in effective_requested_data
        ),
    }


def _draft_to_business_intake(
    draft,
    *,
    requested_modes: list[str],
) -> BusinessIntake:
    effective_modes = requested_modes or list(draft.discovery_modes)
    return BusinessIntake(
        business_name=normalize_whitespace(draft.business_name or ""),
        website=normalize_whitespace(draft.website or ""),
        description=normalize_whitespace(draft.description or ""),
        industry=normalize_whitespace(draft.industry or ""),
        location=normalize_whitespace(draft.location or ""),
        target_geographies=list(draft.target_geographies),
        budget=normalize_whitespace(draft.budget or ""),
        ideal_customer_profile=normalize_whitespace(draft.ideal_customer_profile or ""),
        preferred_company_sizes=list(draft.preferred_company_sizes),
        preferred_sectors=list(draft.preferred_sectors),
        offerings=list(draft.offerings),
        goals=list(draft.goals),
        discovery_modes=effective_modes,
        opportunity_type_needed=normalize_whitespace(
            draft.opportunity_type_needed or ""
        ),
        inclusion_keywords=list(draft.inclusion_keywords),
        exclusion_keywords=list(draft.exclusion_keywords),
        vendor_constraints=normalize_whitespace(draft.vendor_constraints or ""),
        supplier_constraints=normalize_whitespace(draft.supplier_constraints or ""),
        user_urls=list(draft.user_urls),
    )


@ensure_csrf_cookie
@require_GET
def home(request: HttpRequest) -> HttpResponse:
    if request.session.get("growth_engine_boot_id") != APP_BOOT_ID:
        clear_workspace_state(request.session)
        request.session["growth_engine_boot_id"] = APP_BOOT_ID
        request.session.modified = True
    return render(request, "growth_engine_web/home.html", _home_context(request))


@require_GET
def analytics_dashboard(request: HttpRequest) -> HttpResponse:
    if not _is_admin_request(request):
        messages.error(request, "Admin analytics is restricted to authorized admins.")
        return redirect("growth_engine_web:home")

    try:
        snapshot = build_admin_analytics_snapshot(get_runtime_settings())
    except Exception as exc:
        messages.error(
            request,
            normalize_error_message(
                exc,
                fallback=(
                    "Analytics could not be loaded from Firestore. "
                    "Check the admin credentials and storage configuration."
                ),
            )
            or (
                "Analytics could not be loaded from Firestore. "
                "Check the admin credentials and storage configuration."
            ),
        )
        return redirect("growth_engine_web:home")

    return render(
        request,
        "growth_engine_web/analytics.html",
        {
            "current_user": get_auth_user(request.session),
            "can_access_admin_analytics": True,
            "analytics": snapshot,
        },
    )


@require_POST
def research_profile(request: HttpRequest) -> HttpResponse:
    if _auth_is_required() and not get_auth_user(request.session):
        messages.error(request, "Sign in with Google before researching a profile.")
        return redirect("growth_engine_web:home")

    form = SourceResearchForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "growth_engine_web/home.html",
            _home_context(request, source_form=form),
            status=400,
        )

    business_name = form.cleaned_data["business_name"]
    website = form.cleaned_data["website"]
    clear_workspace_state(request.session)
    request.session[BUSINESS_NAME_INPUT_KEY] = business_name
    request.session[WEBSITE_INPUT_KEY] = website
    request.session.modified = True

    researcher = BusinessProfileResearcher(get_runtime_settings())
    try:
        result = researcher.research(business_name=business_name, website=website)
    except Exception as exc:
        messages.error(
            request,
            normalize_error_message(
                exc,
                fallback="Profile research could not be completed. Please try again.",
            )
            or "Profile research could not be completed. Please try again.",
        )
        return redirect("growth_engine_web:home")

    set_research_result(request.session, result)
    set_draft(request.session, result.draft)
    return redirect("growth_engine_web:home")


@require_http_methods(["GET", "POST"])
def edit_section(request: HttpRequest, card_id: str) -> HttpResponse:
    draft = get_draft(request.session)
    card_config = get_summary_card_config(card_id)
    if draft is None or card_config is None:
        messages.error(
            request, "Start a research run before editing a profile section."
        )
        return redirect("growth_engine_web:home")

    if request.method == "POST":
        form = ProfileSectionForm(request.POST, field_names=card_config["fields"])
        if form.is_valid():
            updated_draft = update_draft_from_partial_values(
                draft,
                form.cleaned_partial_values(),
            )
            set_draft(request.session, updated_draft)
            request.session[PROFILE_SAVE_URI_KEY] = None
            clear_lead_results(request.session)
            research_result = get_research_result(request.session)
            if research_result is not None:
                research_result.draft = updated_draft
                set_research_result(request.session, research_result)
            messages.success(
                request,
                (
                    "Section updated. Review and save the full profile again "
                    "before generating leads."
                ),
            )
            return redirect("growth_engine_web:home")
        status_code = 400
    else:
        form = ProfileSectionForm(
            field_names=card_config["fields"],
            initial=form_initial_for_fields(draft, card_config["fields"]),
        )
        status_code = 200

    return render(
        request,
        "growth_engine_web/edit_section.html",
        {
            "card_config": card_config,
            "form": form,
        },
        status=status_code,
    )


@require_POST
def save_profile(request: HttpRequest) -> HttpResponse:
    settings = get_runtime_settings()
    draft = get_draft(request.session)
    research_result = get_research_result(request.session)
    if draft is None or research_result is None:
        messages.error(request, "Research a business profile before saving.")
        return redirect("growth_engine_web:home")

    if _auth_is_required() and not get_auth_user(request.session):
        messages.error(request, "Sign in with Google before saving to Firestore.")
        return redirect("growth_engine_web:home")

    user = get_auth_user(request.session) or {}
    payload = {
        "status": "confirmed",
        "confirmed_at": datetime.now(UTC).isoformat(),
        "confirmed_by": user.get("email", ""),
        "profile": asdict(draft),
        "verification_summary": research_result.verification_summary,
        "sources": [asdict(source) for source in research_result.sources],
    }

    try:
        store = FirestoreProfileStore(settings, settings.firestore_profile_collection)
        save_uri = store.save(
            build_research_document_id(draft.business_name or "profile"),
            payload,
        )
    except Exception as exc:
        messages.error(
            request,
            normalize_error_message(
                exc,
                fallback=(
                    "Profile could not be saved. Check the Firestore "
                    "configuration and try again."
                ),
            )
            or (
                "Profile could not be saved. Check the Firestore configuration "
                "and try again."
            ),
        )
        return redirect("growth_engine_web:home")

    request.session[PROFILE_SAVE_URI_KEY] = save_uri
    clear_lead_results(request.session)
    request.session.modified = True
    return redirect("growth_engine_web:home")


@require_POST
def request_data(request: HttpRequest) -> HttpResponse:
    form = PostSaveRequestForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Choose valid data types before submitting the request."
        )
        return redirect("growth_engine_web:home")

    draft = get_draft(request.session)
    if draft is None:
        messages.error(request, "Confirm a business profile before generating leads.")
        return redirect("growth_engine_web:home")
    if not request.session.get(PROFILE_SAVE_URI_KEY):
        messages.error(request, "Save the confirmed profile before generating leads.")
        return redirect("growth_engine_web:home")

    set_post_save_request(
        request.session,
        requested_data=form.cleaned_data["requested_data"],
        notes=form.cleaned_data["notes"],
    )
    requested_modes = form.cleaned_data["requested_data"] or list(draft.discovery_modes)
    if not requested_modes:
        messages.error(
            request, "Select at least one lead type before generating leads."
        )
        return redirect("growth_engine_web:home")

    clear_lead_results(request.session)
    settings = get_runtime_settings()
    engine = DecisionEngine(settings)
    engine.artifact_store = NoOpArtifactStore()
    engine.audit_store = NoOpAuditStore()

    try:
        result = engine.run(
            _draft_to_business_intake(draft, requested_modes=requested_modes)
        )
    except Exception as exc:
        messages.error(
            request,
            normalize_error_message(
                exc,
                fallback="Lead generation could not be completed. Please try again.",
            )
            or "Lead generation could not be completed. Please try again.",
        )
        return redirect("growth_engine_web:home")

    set_lead_results(
        request.session,
        opportunity_rows=[item.as_export_row() for item in result.opportunities],
        skipped_rows=[item.as_export_row() for item in result.skipped_entities],
        export_name=result.export_name,
        export_bytes=result.export_bytes,
    )

    readable = ", ".join(format_discovery_mode_label(mode) for mode in requested_modes)
    messages.success(
        request,
        f"Generated {len(result.opportunities)} prioritized leads for {readable}.",
    )
    return redirect("growth_engine_web:home")


@require_GET
def download_leads_export(request: HttpRequest) -> HttpResponse:
    lead_results = get_lead_results(request.session)
    export_bytes = get_lead_export_bytes(request.session)
    if lead_results is None or export_bytes is None:
        messages.error(
            request, "Generate leads first before downloading the Excel workbook."
        )
        return redirect("growth_engine_web:home")

    response = HttpResponse(
        export_bytes,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(lead_results['export_name'])}"
    )
    return response


def _google_redirect_uri(request: HttpRequest) -> str:
    settings = get_runtime_settings()
    explicit_redirect_uri = normalize_whitespace(settings.google_oauth_redirect_uri)
    if explicit_redirect_uri:
        return explicit_redirect_uri
    callback_path = reverse("growth_engine_web:google_callback")
    if settings.app_base_url:
        base_url = settings.app_base_url.rstrip("/") + "/"
        return urljoin(base_url, callback_path.lstrip("/"))
    return request.build_absolute_uri(callback_path)


@require_GET
def google_login(request: HttpRequest) -> HttpResponse:
    if not _auth_is_required():
        messages.error(request, "Google authentication is not configured.")
        return redirect("growth_engine_web:home")

    state = create_google_oauth_state()
    request.session[GOOGLE_OAUTH_STATE_KEY] = state
    request.session.modified = True

    try:
        authorization_url = build_google_oauth_authorization_url(
            client_id=get_runtime_settings().google_oauth_client_id,
            redirect_uri=_google_redirect_uri(request),
            state=state,
        )
    except GoogleAuthenticationError as exc:
        messages.error(request, str(exc))
        return redirect("growth_engine_web:home")

    return redirect(authorization_url)


@require_GET
def google_callback(request: HttpRequest) -> HttpResponse:
    if not _auth_is_required():
        messages.error(request, "Google authentication is not configured.")
        return redirect("growth_engine_web:home")

    expected_state = str(request.session.pop(GOOGLE_OAUTH_STATE_KEY, ""))
    returned_state = str(request.GET.get("state", ""))
    if not expected_state or expected_state != returned_state:
        messages.error(request, "Google sign-in state did not match. Please try again.")
        return redirect("growth_engine_web:home")

    if request.GET.get("error"):
        if request.GET.get("error") == "access_denied":
            messages.info(request, "Google sign-in was cancelled.")
        else:
            messages.error(request, "Google sign-in could not be completed.")
        return redirect("growth_engine_web:home")

    try:
        token_payload = exchange_google_code(
            code=str(request.GET.get("code", "")),
            redirect_uri=_google_redirect_uri(request),
        )
        auth_user = verify_google_id_token(str(token_payload.get("id_token") or ""))
    except GoogleAuthenticationError as exc:
        messages.error(request, str(exc))
        return redirect("growth_engine_web:home")

    set_auth_user(request.session, auth_user)
    messages.success(request, f"Signed in as {auth_user['email']}.")
    return redirect("growth_engine_web:home")


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    clear_workspace_state(request.session, clear_auth=True)
    messages.info(request, "Signed out.")
    return redirect("growth_engine_web:home")
