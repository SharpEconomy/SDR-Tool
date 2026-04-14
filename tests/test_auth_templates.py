from __future__ import annotations

from pathlib import Path


def test_home_template_uses_server_side_google_login_link() -> None:
    template = Path(
        "growth_engine_web/templates/growth_engine_web/home.html"
    ).read_text(encoding="utf-8")

    assert "growth_engine_web:google_login" in template
    assert "Sign in with Google" in template
    assert "card.id == 'commercial_setup'" in template
    assert "download_leads_export" in template
    assert "Prioritized leads" in template
    assert "state-accordion" in template
    assert "lead-list" in template
    assert "lead-table" not in template
    assert "growth_engine_web:analytics" in template


def test_base_template_no_longer_loads_firebase_sdk() -> None:
    template = Path(
        "growth_engine_web/templates/growth_engine_web/base.html"
    ).read_text(encoding="utf-8")

    assert "firebase" not in template.lower()
    assert "server-authenticated" not in template
    assert "data-loading-shell" in template
    assert "data-loading-tip" in template
    assert "Marketing tip" in template
    assert "growth_engine_web/app.js" in template


def test_analytics_template_exists_with_admin_copy() -> None:
    template = Path(
        "growth_engine_web/templates/growth_engine_web/analytics.html"
    ).read_text(encoding="utf-8")

    assert "Workspace analytics" in template
    assert "Profile ledger" in template
    assert "Workflow ledger" in template
    assert "Admin-only operations surface" not in template
    assert "analytics-hero" not in template


def test_templates_mark_processing_forms_for_loading_overlay() -> None:
    home_template = Path(
        "growth_engine_web/templates/growth_engine_web/home.html"
    ).read_text(encoding="utf-8")
    edit_template = Path(
        "growth_engine_web/templates/growth_engine_web/edit_section.html"
    ).read_text(encoding="utf-8")

    assert "data-processing-label" in home_template
    assert "Generating leads and preparing the workbook" in home_template
    assert "Saving section changes" in edit_template


def test_loading_shell_respects_hidden_attribute_in_css() -> None:
    stylesheet = Path("growth_engine_web/static/growth_engine_web/app.css").read_text(
        encoding="utf-8"
    )

    assert ".loading-shell[hidden]" in stylesheet
    assert "@keyframes loading-tip-enter" in stylesheet
    assert ".loading-tip.is-active" in stylesheet


def test_loading_script_preserves_hidden_csrf_inputs() -> None:
    script = Path("growth_engine_web/static/growth_engine_web/app.js").read_text(
        encoding="utf-8"
    )

    assert "csrfmiddlewaretoken" in script
    assert 'element.type === "hidden"' in script
    assert "data-loading-tip" in script
    assert "20000" in script
