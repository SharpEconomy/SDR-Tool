from __future__ import annotations

import html
import threading
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from queue import Empty, Queue

import pandas as pd
import streamlit as st

from growth_engine.auth import firebase_login_screen
from growth_engine.config import Settings
from growth_engine.intake import IntakeInterviewer
from growth_engine.models import (
    EXPORT_OPPORTUNITY_COLUMNS,
    BusinessIntake,
    DecisionRunResult,
    IntakeDraft,
    IntakeQuestion,
)
from growth_engine.orchestration import DecisionEngine, PipelineControl
from growth_engine.services.openai_service import OpenAIService
from growth_engine.utils import dedupe_keep_order, normalize_whitespace

ACTIVE_RUN_KEY = "growth_engine_active_run"
INTAKE_DRAFT_KEY = "growth_engine_intake_draft"
INTAKE_CHAT_KEY = "growth_engine_intake_chat"
INTAKE_QUESTION_KEY = "growth_engine_intake_question"
RESULT_TABLE_HEIGHT = 440
EMPTY_BRIEF_MESSAGE = "Still waiting for the first answer."
SNAPSHOT_FIELDS = (
    "business_name",
    "website",
    "description",
    "industry",
    "location",
    "discovery_modes",
    "opportunity_type_needed",
    "goals",
    "target_geographies",
    "ideal_customer_profile",
    "preferred_company_sizes",
    "preferred_sectors",
    "budget",
    "offerings",
    "inclusion_keywords",
    "exclusion_keywords",
    "vendor_constraints",
    "supplier_constraints",
    "user_urls",
)
FOLLOW_UP_LEADS = {
    "business_name": "That gives me the business basics.",
    "description": "That gives me the business basics.",
    "industry": "That gives me the business basics.",
    "location": "That gives me the business basics.",
    "website": "Good. I have the main public reference point.",
    "discovery_modes": "That sharpens the kind of opportunity to look for.",
    "opportunity_type_needed": "That sharpens the kind of opportunity to look for.",
    "goals": "That sharpens the kind of opportunity to look for.",
    "target_geographies": "That helps narrow the target.",
    "ideal_customer_profile": "That helps narrow the target.",
    "preferred_company_sizes": "That improves the fit filter.",
    "preferred_sectors": "That improves the fit filter.",
    "budget": "Understood. I have the budget posture.",
    "offerings": "That tells me what the market-facing offer is.",
    "inclusion_keywords": "That tightens the filter logic.",
    "exclusion_keywords": "That tightens the filter logic.",
    "vendor_constraints": "That adds practical guardrails.",
    "supplier_constraints": "That adds practical guardrails.",
    "user_urls": "That adds practical guardrails.",
}

FIELD_LABELS = {
    "business_name": "Business name",
    "website": "Website",
    "description": "What you sell",
    "industry": "Industry",
    "location": "Base location",
    "target_geographies": "Target markets",
    "budget": "Budget comfort",
    "ideal_customer_profile": "Ideal profile",
    "preferred_company_sizes": "Company sizes",
    "preferred_sectors": "Sectors",
    "offerings": "Offerings",
    "goals": "Goals",
    "discovery_modes": "Opportunity types",
    "opportunity_type_needed": "Primary need",
    "inclusion_keywords": "Must-have words",
    "exclusion_keywords": "Avoid words",
    "vendor_constraints": "Vendor constraints",
    "supplier_constraints": "Supplier constraints",
    "user_urls": "Seed URLs",
}

REFINE_QUESTIONS = {
    "business": IntakeQuestion(
        question=(
            "What should I update about the business basics: name, website, what "
            "you sell, industry, or base location?"
        ),
        focus_fields=[
            "business_name",
            "website",
            "description",
            "industry",
            "location",
        ],
        rationale="manual_refine_business",
    ),
    "targeting": IntakeQuestion(
        question=(
            "What should I refine about the opportunities you want, the target "
            "markets, the ideal profile, size, sector, budget, or offerings?"
        ),
        focus_fields=[
            "discovery_modes",
            "opportunity_type_needed",
            "goals",
            "target_geographies",
            "ideal_customer_profile",
            "preferred_company_sizes",
            "preferred_sectors",
            "budget",
            "offerings",
        ],
        rationale="manual_refine_targeting",
    ),
    "filters": IntakeQuestion(
        question=(
            "What should I change in the must-have filters, avoid words, vendor or "
            "supplier constraints, or trusted URLs?"
        ),
        focus_fields=[
            "inclusion_keywords",
            "exclusion_keywords",
            "vendor_constraints",
            "supplier_constraints",
            "user_urls",
        ],
        rationale="manual_refine_filters",
    ),
}


@dataclass(slots=True)
class ActiveRunState:
    progress_queue: Queue[tuple[str, object]]
    controller: PipelineControl
    worker: threading.Thread
    started_at: float
    status: str = "running"
    result: DecisionRunResult | None = None
    error: str | None = None
    log_lines: list[str] = dataclass_field(default_factory=list)
    completion_notice_shown: bool = False


def render() -> None:
    st.set_page_config(page_title="Growth Decision Engine", layout="wide")
    _inject_styles()
    settings = Settings.load()
    _ensure_session_state()

    if settings.firebase_api_key and not _render_auth_gate(settings):
        return

    st.markdown(
        """
        <section class="hero-shell">
          <div class="hero-kicker">AI business growth decision engine</div>
          <h1>Build the growth brief through a guided conversation.</h1>
          <p>
            Answer a few smart questions in plain language. The engine turns that
            into a business profile, discovers the strongest opportunities, and
            explains why each one deserves attention.
          </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    interviewer = IntakeInterviewer(OpenAIService(settings))
    _ensure_interview_state(interviewer)
    intake = _render_interview(interviewer)

    active_run = _get_active_run()
    if active_run is not None:
        _sync_active_run(active_run)

    _render_controls(intake, active_run, settings)

    active_run = _get_active_run()
    if active_run is None:
        _render_empty_state()
        return

    _sync_active_run(active_run)
    _render_run_status(active_run)
    _render_progress(active_run)
    _render_results(active_run)

    if active_run.status in {"running", "stopping"} and active_run.worker.is_alive():
        time.sleep(0.4)
        st.rerun()


def _render_auth_gate(settings: Settings) -> bool:
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if st.session_state["user"]:
        email_col, logout_col = st.columns([6, 1])
        email_col.caption(
            f"Signed in as {st.session_state['user'].get('email', 'User')}"
        )
        if logout_col.button("Log out", use_container_width=True):
            st.session_state["user"] = None
            st.rerun()
        return True
    st.markdown(
        "<div class='step-card'><h3>Sign in</h3><p>Use Google sign-in to protect the workspace.</p></div>",
        unsafe_allow_html=True,
    )
    auth_result = firebase_login_screen(
        {
            "apiKey": settings.firebase_api_key,
            "authDomain": settings.firebase_auth_domain,
            "projectId": settings.firebase_project_id,
        }
    )
    if auth_result and "token" in auth_result:
        st.session_state["user"] = auth_result
        st.rerun()
    return False


def _render_interview(interviewer: IntakeInterviewer) -> BusinessIntake | None:
    draft: IntakeDraft = st.session_state[INTAKE_DRAFT_KEY]
    messages: list[dict[str, str]] = st.session_state[INTAKE_CHAT_KEY]
    current_question: IntakeQuestion | None = st.session_state[INTAKE_QUESTION_KEY]
    active_run = _get_active_run()
    run_is_active = active_run is not None and active_run.status in {
        "running",
        "paused",
        "stopping",
    }

    left, right = st.columns([1.35, 0.95], gap="large")
    with left:
        st.markdown(
            """
            <div class="chat-shell">
              <div class="step-label">Step 1</div>
              <h3>Tell the story once</h3>
              <p>
                I will ask only for what is still missing. You can answer naturally
                in full sentences or short bullet-style replies.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for message in messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = (
            "Discovery is running. Pause or wait for this run to finish before editing the brief."
            if run_is_active
            else "Answer here"
        )
        answer = st.chat_input(
            prompt,
            disabled=run_is_active or current_question is None,
        )
        if answer:
            _handle_interview_answer(interviewer, answer)
            st.rerun()

    with right:
        _render_snapshot(interviewer, draft, run_is_active)

    updated_draft: IntakeDraft = st.session_state[INTAKE_DRAFT_KEY]
    if interviewer.missing_fields(updated_draft):
        return None
    return interviewer.to_business_intake(updated_draft)


def _render_snapshot(
    interviewer: IntakeInterviewer,
    draft: IntakeDraft,
    run_is_active: bool,
) -> None:
    progress = interviewer.completion_ratio(draft)
    missing_fields = interviewer.missing_fields(draft)
    st.markdown(
        """
        <div class="snapshot-shell">
          <div class="step-label">Step 2</div>
          <h3>Business brief</h3>
          <p>This turns into the profile that drives discovery, filtering, ranking, and matching.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress(progress)
    st.caption(f"{round(progress * 100)}% complete")
    if missing_fields:
        st.markdown(
            _badge_row([FIELD_LABELS[field_name] for field_name in missing_fields]),
            unsafe_allow_html=True,
        )
    else:
        st.success("The brief is complete. Review it below, then run discovery.")

    st.markdown(_snapshot_card_html(draft), unsafe_allow_html=True)

    refine_cols = st.columns(3)
    business_clicked = refine_cols[0].button(
        "Refine business",
        disabled=run_is_active,
        use_container_width=True,
    )
    targeting_clicked = refine_cols[1].button(
        "Refine need",
        disabled=run_is_active,
        use_container_width=True,
    )
    filters_clicked = refine_cols[2].button(
        "Refine filters",
        disabled=run_is_active,
        use_container_width=True,
    )
    reset_clicked = st.button(
        "Start over",
        disabled=run_is_active,
        use_container_width=True,
    )

    if business_clicked:
        _queue_assistant_question(
            REFINE_QUESTIONS["business"],
            lead="We can tighten the business brief.",
        )
        st.rerun()
    if targeting_clicked:
        _queue_assistant_question(
            REFINE_QUESTIONS["targeting"],
            lead="We can sharpen the matching target.",
        )
        st.rerun()
    if filters_clicked:
        _queue_assistant_question(
            REFINE_QUESTIONS["filters"],
            lead="We can tune the filters and constraints.",
        )
        st.rerun()
    if reset_clicked:
        _reset_interview_state(interviewer)
        st.session_state[ACTIVE_RUN_KEY] = None
        st.rerun()


def _render_controls(
    intake: BusinessIntake | None,
    active_run: ActiveRunState | None,
    settings: Settings,
) -> None:
    run_is_active = active_run is not None and active_run.status in {
        "running",
        "paused",
        "stopping",
    }
    draft: IntakeDraft = st.session_state[INTAKE_DRAFT_KEY]
    interviewer = IntakeInterviewer()
    missing_count = len(interviewer.missing_fields(draft))

    control_cols = st.columns([1, 1, 1, 4])
    start_clicked = control_cols[0].button(
        "Run discovery",
        disabled=run_is_active or intake is None,
        use_container_width=True,
    )
    pause_label = (
        "Resume"
        if active_run is not None and active_run.status == "paused"
        else "Pause"
    )
    pause_clicked = control_cols[1].button(
        pause_label,
        disabled=not (
            active_run is not None and active_run.status in {"running", "paused"}
        ),
        use_container_width=True,
    )
    stop_clicked = control_cols[2].button(
        "Stop",
        disabled=not (
            active_run is not None
            and active_run.status in {"running", "paused", "stopping"}
        ),
        use_container_width=True,
    )
    control_message = (
        f"Run state: {_describe_run_state(active_run)}"
        if intake is not None
        else (
            f"Answer {missing_count} more question"
            f"{'s' if missing_count != 1 else ''} to unlock discovery."
        )
    )
    control_cols[3].markdown(
        f"<div class='run-state'>{html.escape(control_message)}</div>",
        unsafe_allow_html=True,
    )

    if start_clicked and intake is not None:
        st.session_state[ACTIVE_RUN_KEY] = None
        _start_background_run(settings, intake)
        st.rerun()

    if pause_clicked and active_run is not None:
        if active_run.status == "paused":
            active_run.controller.resume()
            active_run.status = "running"
        else:
            active_run.controller.pause()
            active_run.status = "paused"
        st.rerun()
        return

    if stop_clicked and active_run is not None:
        active_run.controller.stop()
        active_run.status = "stopping"


def _render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-shell">
          <h3>When the brief is ready, the engine takes over</h3>
          <p>
            It will normalize the business profile, evaluate public opportunity
            sources, score the best matches, and export a ranked workbook with the
            skipped entities and reasons.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_run_status(active_run: ActiveRunState) -> None:
    if active_run.error:
        st.error(active_run.error)
        return
    if active_run.status == "paused":
        st.info(
            "Discovery is paused. Resume to continue or stop to keep the current output."
        )
    elif active_run.status == "running":
        st.info(
            "Discovery is running. The opportunity list will appear as soon as the engine finishes."
        )
    elif active_run.status == "stopping":
        st.warning("Stopping the run after the current in-flight work finishes.")
    elif active_run.status == "completed" and not active_run.completion_notice_shown:
        st.success("Discovery completed. Ranked opportunities are ready below.")
        active_run.completion_notice_shown = True


def _render_progress(active_run: ActiveRunState) -> None:
    left, right = st.columns([1, 1.5])
    with left:
        st.markdown(
            "<div class='step-card'><div class='step-label'>Step 3</div><h3>Progress</h3></div>",
            unsafe_allow_html=True,
        )
        elapsed = int(time.time() - active_run.started_at)
        st.metric("Elapsed", _format_duration(elapsed))
        st.metric("Events", len(active_run.log_lines))
    with right:
        st.markdown(
            "<div class='step-card'><div class='step-label'>Step 4</div><h3>Live log</h3></div>",
            unsafe_allow_html=True,
        )
        st.code(
            "\n".join(active_run.log_lines[-16:]) or "Waiting to start...",
            language="text",
        )


def _render_results(active_run: ActiveRunState) -> None:
    result = active_run.result
    if result is None:
        return
    st.markdown(
        "<div class='step-card'><div class='step-label'>Step 5</div><h3>Review top matches</h3></div>",
        unsafe_allow_html=True,
    )
    summary_cols = st.columns(3)
    summary_cols[0].metric("Ranked opportunities", len(result.opportunities))
    summary_cols[1].metric("Skipped entities", len(result.skipped_entities))
    summary_cols[2].metric("Modes covered", len(result.profile.discovery_modes))
    st.download_button(
        "Download Excel",
        data=result.export_bytes,
        file_name=result.export_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )
    if result.export_uri:
        st.caption(f"Artifact saved to `{result.export_uri}`")

    for opportunity in result.opportunities[:8]:
        opportunity_mode = html.escape(
            opportunity.discovery_mode.replace("_", " ").title()
        )
        opportunity_side = html.escape(opportunity.market_side)
        st.markdown(
            f"""
            <article class="opportunity-card">
              <div class="opportunity-score">{opportunity.priority_score}</div>
              <div class="opportunity-body">
                <div class="opportunity-meta">{opportunity_mode} &middot; {opportunity_side}</div>
                <h4>{html.escape(opportunity.entity_name)}</h4>
                <p>{html.escape(opportunity.why_it_matters)}</p>
                <p><strong>Reasoning:</strong> {html.escape(opportunity.reasoning_summary)}</p>
                <div class="opportunity-tags">
                  <span>{html.escape(opportunity.category)}</span>
                  <span>{html.escape(opportunity.location)}</span>
                  <span>{html.escape(opportunity.expected_value)}</span>
                  <span>{html.escape(opportunity.contact_path)}</span>
                </div>
                <strong>Next action:</strong> {html.escape(opportunity.next_action)}
              </div>
            </article>
            """,
            unsafe_allow_html=True,
        )

    frame = pd.DataFrame(
        [item.as_export_row() for item in result.opportunities],
        columns=EXPORT_OPPORTUNITY_COLUMNS,
    )
    st.dataframe(frame, use_container_width=True, height=RESULT_TABLE_HEIGHT)


def _ensure_session_state() -> None:
    if ACTIVE_RUN_KEY not in st.session_state:
        st.session_state[ACTIVE_RUN_KEY] = None
    if INTAKE_DRAFT_KEY not in st.session_state:
        st.session_state[INTAKE_DRAFT_KEY] = IntakeDraft()
    if INTAKE_CHAT_KEY not in st.session_state:
        st.session_state[INTAKE_CHAT_KEY] = []
    if INTAKE_QUESTION_KEY not in st.session_state:
        st.session_state[INTAKE_QUESTION_KEY] = None


def _ensure_interview_state(interviewer: IntakeInterviewer) -> None:
    messages: list[dict[str, str]] = st.session_state[INTAKE_CHAT_KEY]
    current_question: IntakeQuestion | None = st.session_state[INTAKE_QUESTION_KEY]
    draft: IntakeDraft = st.session_state[INTAKE_DRAFT_KEY]
    if not messages:
        opening = interviewer.opening_question()
        _queue_assistant_question(
            opening,
            lead="I will build the growth brief with you one answer at a time.",
        )
        return
    if current_question is None and interviewer.missing_fields(draft):
        next_question = interviewer.next_question(draft, transcript=messages)
        if next_question is not None:
            _queue_assistant_question(next_question)


def _reset_interview_state(interviewer: IntakeInterviewer) -> None:
    st.session_state[INTAKE_DRAFT_KEY] = IntakeDraft()
    st.session_state[INTAKE_CHAT_KEY] = []
    st.session_state[INTAKE_QUESTION_KEY] = None
    _ensure_interview_state(interviewer)


def _queue_assistant_question(
    question: IntakeQuestion,
    *,
    lead: str | None = None,
) -> None:
    st.session_state[INTAKE_QUESTION_KEY] = question
    content = question.question if not lead else f"{lead}\n\n{question.question}"
    st.session_state[INTAKE_CHAT_KEY].append({"role": "assistant", "content": content})


def _handle_interview_answer(interviewer: IntakeInterviewer, answer: str) -> None:
    cleaned_answer = normalize_whitespace(answer)
    if not cleaned_answer:
        return

    messages: list[dict[str, str]] = st.session_state[INTAKE_CHAT_KEY]
    current_question: IntakeQuestion | None = st.session_state[INTAKE_QUESTION_KEY]
    messages.append({"role": "user", "content": cleaned_answer})
    updated_draft = interviewer.apply_answer(
        st.session_state[INTAKE_DRAFT_KEY],
        cleaned_answer,
        focus_fields=current_question.focus_fields if current_question else [],
        transcript=messages,
    )
    st.session_state[INTAKE_DRAFT_KEY] = updated_draft
    st.session_state[ACTIVE_RUN_KEY] = None

    next_question = interviewer.next_question(updated_draft, transcript=messages)
    if next_question is None:
        st.session_state[INTAKE_QUESTION_KEY] = None
        messages.append(
            {
                "role": "assistant",
                "content": (
                    "The brief is complete. Review the snapshot and run discovery "
                    "when you are ready."
                ),
            }
        )
        return

    _queue_assistant_question(
        next_question,
        lead=_follow_up_lead(current_question),
    )


def _follow_up_lead(question: IntakeQuestion | None) -> str | None:
    if question is None:
        return None
    for field_name in question.focus_fields:
        lead = FOLLOW_UP_LEADS.get(field_name)
        if lead:
            return lead
    return None


def _get_active_run() -> ActiveRunState | None:
    return st.session_state.get(ACTIVE_RUN_KEY)


def _start_background_run(settings: Settings, intake: BusinessIntake) -> ActiveRunState:
    controller = PipelineControl()
    progress_queue: Queue[tuple[str, object]] = Queue()
    worker = threading.Thread(
        target=_run_worker,
        args=(settings, intake, controller, progress_queue),
        daemon=True,
    )
    active_run = ActiveRunState(
        progress_queue=progress_queue,
        controller=controller,
        worker=worker,
        started_at=time.time(),
    )
    st.session_state[ACTIVE_RUN_KEY] = active_run
    worker.start()
    return active_run


def _run_worker(
    settings: Settings,
    intake: BusinessIntake,
    controller: PipelineControl,
    progress_queue: Queue[tuple[str, object]],
) -> None:
    try:
        engine = DecisionEngine(settings)
        result = engine.run(
            intake,
            progress_callback=lambda message: progress_queue.put(("progress", message)),
            control=controller,
        )
        progress_queue.put(("result", result))
    except Exception as exc:
        progress_queue.put(("error", str(exc)))


def _sync_active_run(active_run: ActiveRunState) -> None:
    while True:
        try:
            kind, payload = active_run.progress_queue.get_nowait()
        except Empty:
            break
        if kind == "progress":
            active_run.log_lines.append(str(payload))
        elif kind == "result":
            active_run.result = (
                payload if isinstance(payload, DecisionRunResult) else None
            )
        elif kind == "error" and payload:
            active_run.error = str(payload)

    if active_run.error is not None:
        active_run.status = "error"
    elif active_run.worker.is_alive():
        if active_run.status not in {"paused", "stopping"}:
            active_run.status = "running"
    elif active_run.result is not None:
        active_run.status = (
            "stopped" if active_run.controller.should_stop() else "completed"
        )


def _parse_list_input(raw_value: str) -> list[str]:
    return dedupe_keep_order(
        [
            item
            for item in raw_value.replace("\n", ",").split(",")
            if normalize_whitespace(item)
        ]
    )


def _parse_multiline_urls(raw_value: str) -> list[str]:
    items = [normalize_whitespace(line) for line in raw_value.splitlines()]
    cleaned = []
    for item in items:
        if not item:
            continue
        cleaned.append(item if "://" in item else f"https://{item}")
    return dedupe_keep_order(cleaned)


def _describe_run_state(active_run: ActiveRunState | None) -> str:
    if active_run is None:
        return "Idle"
    return active_run.status.replace("_", " ").title()


def _format_duration(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, total_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _badge_row(items: list[str]) -> str:
    badges = "".join(f"<span>{html.escape(item)}</span>" for item in items)
    return f"<div class='missing-badges'>{badges}</div>"


def _snapshot_card_html(draft: IntakeDraft) -> str:
    rows = []
    for field_name in SNAPSHOT_FIELDS:
        rendered = _render_field_value(getattr(draft, field_name))
        if not rendered:
            continue
        rows.append(
            f"<div class='detail-row'><span>{html.escape(FIELD_LABELS[field_name])}</span><strong>{rendered}</strong></div>"
        )
    if not rows:
        rows.append(
            f"<div class='detail-row'><span>Brief status</span><strong>{html.escape(EMPTY_BRIEF_MESSAGE)}</strong></div>"
        )
    return f"<div class='snapshot-card'>{''.join(rows)}</div>"


def _render_field_value(value: object) -> str:
    if isinstance(value, list):
        if not value:
            return ""
        return html.escape(", ".join(str(item) for item in value))
    cleaned = normalize_whitespace(str(value or ""))
    return html.escape(cleaned) if cleaned else ""


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@400;500;600;700&display=swap');

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(218, 231, 212, 0.72), transparent 28%),
                radial-gradient(circle at right 20%, rgba(236, 220, 196, 0.68), transparent 24%),
                linear-gradient(180deg, #f6f0e3 0%, #fbf8f1 100%);
            color: #19352a;
        }

        .hero-shell, .step-card, .opportunity-card, .empty-shell, .chat-shell, .snapshot-shell, .snapshot-card {
            background: rgba(255, 252, 246, 0.88);
            border: 1px solid rgba(35, 69, 53, 0.12);
            border-radius: 24px;
            box-shadow: 0 18px 40px rgba(36, 52, 41, 0.08);
        }

        .hero-shell {
            padding: 2rem 2.2rem;
            margin-bottom: 1.4rem;
        }

        .chat-shell, .snapshot-shell {
            padding: 1rem 1.1rem;
            margin-bottom: 0.9rem;
        }

        .snapshot-card {
            padding: 0.6rem 0.95rem;
            margin: 0.8rem 0 1rem;
        }

        .hero-shell h1, .step-card h3, .opportunity-card h4, .empty-shell h3, .chat-shell h3, .snapshot-shell h3 {
            font-family: "Fraunces", serif;
            margin: 0;
            color: #19352a;
        }

        .hero-shell p, .step-card p, .opportunity-card p, .empty-shell p, .run-state, .chat-shell p, .snapshot-shell p {
            font-family: "Manrope", sans-serif;
            color: #496152;
        }

        .hero-kicker, .step-label, .opportunity-meta {
            font-family: "Manrope", sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.72rem;
            color: #7a8f7f;
        }

        .step-card {
            padding: 0.95rem 1.1rem;
            margin-bottom: 0.65rem;
        }

        .run-state {
            padding-top: 0.55rem;
            font-weight: 600;
        }

        .empty-shell {
            padding: 1.6rem 1.8rem;
            margin-top: 1rem;
        }

        .opportunity-card {
            display: grid;
            grid-template-columns: 92px 1fr;
            gap: 1rem;
            padding: 1.1rem 1.2rem;
            margin-bottom: 0.85rem;
        }

        .opportunity-score {
            width: 76px;
            height: 76px;
            border-radius: 50%;
            background: linear-gradient(180deg, #224f3b 0%, #2f7256 100%);
            color: #f9f5eb;
            font-family: "Fraunces", serif;
            font-size: 1.7rem;
            display: flex;
            align-items: center;
            justify-content: center;
            align-self: center;
        }

        .opportunity-body {
            font-family: "Manrope", sans-serif;
        }

        .opportunity-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin: 0.75rem 0;
        }

        .opportunity-tags span, .missing-badges span {
            background: #edf3eb;
            color: #35513f;
            border-radius: 999px;
            padding: 0.3rem 0.75rem;
            font-size: 0.78rem;
            border: 1px solid rgba(53, 81, 63, 0.08);
            font-family: "Manrope", sans-serif;
        }

        .missing-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin: 0.55rem 0 0.8rem;
        }

        .detail-row {
            display: grid;
            grid-template-columns: minmax(120px, 160px) 1fr;
            gap: 0.75rem;
            align-items: start;
            padding: 0.55rem 0;
            border-bottom: 1px solid rgba(35, 69, 53, 0.08);
            font-family: "Manrope", sans-serif;
        }

        .detail-row:last-child {
            border-bottom: 0;
        }

        .detail-row span {
            color: #6b7f72;
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .detail-row strong {
            color: #1e3b2d;
            font-size: 0.94rem;
            line-height: 1.45;
        }

        [data-testid="stChatMessage"] {
            background: rgba(255, 252, 246, 0.55);
            border-radius: 20px;
            border: 1px solid rgba(35, 69, 53, 0.08);
            padding: 0.25rem 0.35rem;
            box-shadow: 0 10px 24px rgba(36, 52, 41, 0.05);
        }

        [data-testid="stChatMessage"] p {
            font-family: "Manrope", sans-serif;
            color: #213f31;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
