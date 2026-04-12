from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

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
from growth_engine.storage import FirestoreProfileStore
from growth_engine_web.firebase_auth import (
    FirebaseAuthenticationError,
    verify_firebase_login,
)
from growth_engine_web.forms import (
    PostSaveRequestForm,
    ProfileSectionForm,
    SourceResearchForm,
)
from growth_engine_web.runtime import get_runtime_settings
from growth_engine_web.session_state import (
    BUSINESS_NAME_INPUT_KEY,
    PROFILE_SAVE_URI_KEY,
    WEBSITE_INPUT_KEY,
    clear_workspace_state,
    get_auth_user,
    get_draft,
    get_post_save_request,
    get_research_result,
    set_auth_user,
    set_draft,
    set_post_save_request,
    set_research_result,
)


def _auth_is_required() -> bool:
    settings = get_runtime_settings()
    return bool(
        settings.firebase_api_key
        and settings.firebase_auth_domain
        and settings.firebase_project_id
    )


def _home_context(
    request: HttpRequest,
    *,
    source_form: SourceResearchForm | None = None,
) -> dict[str, object]:
    draft = get_draft(request.session)
    research_result = get_research_result(request.session)
    post_save_request = get_post_save_request(request.session)
    current_user = get_auth_user(request.session)

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
        "source_form": source_form,
        "draft": draft,
        "research_result": research_result,
        "summary_cards": build_summary_cards(draft) if draft else [],
        "save_uri": request.session.get(PROFILE_SAVE_URI_KEY),
        "post_save_form": PostSaveRequestForm(
            initial={
                "requested_data": post_save_request["requested_data"],
                "notes": post_save_request["notes"],
            }
        ),
        "requested_data_summary": ", ".join(
            format_discovery_mode_label(mode)
            for mode in post_save_request["requested_data"]
        ),
    }


@ensure_csrf_cookie
@require_GET
def home(request: HttpRequest) -> HttpResponse:
    return render(request, "growth_engine_web/home.html", _home_context(request))


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
    request.session[BUSINESS_NAME_INPUT_KEY] = business_name
    request.session[WEBSITE_INPUT_KEY] = website
    request.session[PROFILE_SAVE_URI_KEY] = None
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
    messages.success(
        request,
        "Profile drafted from public evidence. Review the cards before saving.",
    )
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
            research_result = get_research_result(request.session)
            if research_result is not None:
                research_result.draft = updated_draft
                set_research_result(request.session, research_result)
            messages.success(
                request,
                "Section updated. Review the full profile before saving.",
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
                fallback="Profile could not be saved. Check the Firestore configuration and try again.",
            )
            or "Profile could not be saved. Check the Firestore configuration and try again.",
        )
        return redirect("growth_engine_web:home")

    request.session[PROFILE_SAVE_URI_KEY] = save_uri
    request.session.modified = True
    messages.success(request, "Profile confirmed and saved to Firestore.")
    return redirect("growth_engine_web:home")


@require_POST
def request_data(request: HttpRequest) -> HttpResponse:
    form = PostSaveRequestForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Choose valid data types before submitting the request."
        )
        return redirect("growth_engine_web:home")

    set_post_save_request(
        request.session,
        requested_data=form.cleaned_data["requested_data"],
        notes=form.cleaned_data["notes"],
    )
    if form.cleaned_data["requested_data"]:
        readable = ", ".join(
            format_discovery_mode_label(mode)
            for mode in form.cleaned_data["requested_data"]
        )
        messages.info(request, f"Requested next data: {readable}")
    else:
        messages.info(request, "Saved the follow-up data request notes.")
    return redirect("growth_engine_web:home")


@require_POST
def firebase_login(request: HttpRequest) -> JsonResponse:
    if not _auth_is_required():
        return JsonResponse(
            {"error": "Firebase authentication is not configured."},
            status=400,
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid login payload."}, status=400)

    try:
        auth_user = verify_firebase_login(str(payload.get("token", "")))
    except FirebaseAuthenticationError as exc:
        return JsonResponse({"error": str(exc)}, status=401)

    set_auth_user(request.session, auth_user)
    return JsonResponse({"ok": True, "user": auth_user})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    clear_workspace_state(request.session, clear_auth=True)
    messages.info(request, "Signed out.")
    return redirect("growth_engine_web:home")
