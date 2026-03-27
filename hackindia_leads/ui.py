from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Queue

import streamlit as st

from hackindia_leads.config import Settings
from hackindia_leads.pipeline import LeadPipeline, PipelineControl, PipelineResult

SOURCE_PANEL_COLUMNS = 2
SOURCE_PANEL_HEIGHT = 360
SOURCE_LOG_HEIGHT = 190
ACTIVE_RUN_KEY = "active_run"


@dataclass(slots=True)
class SourceProgressState:
    name: str
    status: str = "Waiting"
    event_pages: int = 0
    events_ready: int = 0
    accepted: int = 0
    filtered: int = 0
    skipped: int = 0
    recent_logs: list[str] = field(default_factory=list)

    def push_log(self, message: str) -> None:
        self.recent_logs.append(message)
        self.recent_logs = self.recent_logs[-8:]


@dataclass(slots=True)
class ActiveRunState:
    source_order: list[str]
    source_states: dict[str, SourceProgressState]
    progress_queue: Queue[tuple[str, object]]
    controller: PipelineControl
    worker: threading.Thread
    started_at: float
    estimated_total_seconds: int
    status: str = "running"
    result: PipelineResult | None = None
    error: str | None = None


def render() -> None:
    st.set_page_config(page_title="HackIndia Lead Finder", layout="wide")
    _inject_styles()
    st.title("HackIndia Lead Finder")
    st.caption("Minimal sponsor-lead scraper for AI and Web3 hackathons.")

    settings = Settings.load()
    _ensure_session_state()
    active_run = _get_active_run()
    if active_run is not None:
        _sync_active_run(active_run)

    with st.sidebar:
        st.subheader("Run Scope")
        selected_sources = st.multiselect(
            "Sources",
            options=["ethglobal", "devpost", "dorahacks", "mlh"],
            default=settings.default_sources,
        )
        keywords_raw = st.text_input(
            "Themes", value=",".join(settings.default_keywords)
        )
        limit_per_source = st.number_input(
            "Event pages per source",
            min_value=1,
            max_value=25,
            value=settings.max_events_per_source,
            step=1,
        )
        control_cols = st.columns(3)
        run_is_active = _run_is_active(active_run)
        start_clicked = control_cols[0].button(
            "Start",
            use_container_width=True,
            disabled=run_is_active,
        )
        pause_label = "Resume" if _run_is_paused(active_run) else "Pause"
        pause_clicked = control_cols[1].button(
            pause_label,
            use_container_width=True,
            disabled=not _can_pause_or_resume(active_run),
        )
        stop_clicked = control_cols[2].button(
            "Stop",
            use_container_width=True,
            disabled=not _can_stop(active_run),
        )
        st.caption(f"Run state: {_describe_run_state(active_run)}")
        st.caption("Environment status")
        _render_env_status(settings)

    if start_clicked:
        if not selected_sources:
            st.error("Select at least one source.")
            return
        if not settings.smtp_from_email:
            st.error(
                "Set SMTP_FROM_EMAIL in your .env file before running the scraper."
            )
            return
        keywords = [item.strip() for item in keywords_raw.split(",") if item.strip()]
        st.session_state[ACTIVE_RUN_KEY] = None
        active_run = _start_background_run(
            settings,
            selected_sources,
            keywords,
            int(limit_per_source),
        )

    if pause_clicked and active_run is not None:
        if active_run.status == "paused":
            active_run.controller.resume()
            active_run.status = "running"
        else:
            active_run.controller.pause()
            active_run.status = "paused"

    if stop_clicked and active_run is not None:
        active_run.controller.stop()
        active_run.status = "stopping"

    active_run = _get_active_run()
    if active_run is None:
        return

    _sync_active_run(active_run)
    _render_run_outcome(active_run)
    source_panels = _create_source_panels(active_run.source_order)
    for source_name in active_run.source_order:
        _render_source_panel(
            active_run.source_states[source_name],
            source_panels[source_name],
        )

    if active_run.status in {"running", "stopping"} and active_run.worker.is_alive():
        time.sleep(0.5)
        st.rerun()


def _ensure_session_state() -> None:
    if ACTIVE_RUN_KEY not in st.session_state:
        st.session_state[ACTIVE_RUN_KEY] = None


def _get_active_run() -> ActiveRunState | None:
    return st.session_state.get(ACTIVE_RUN_KEY)


def _start_background_run(
    settings: Settings,
    selected_sources: list[str],
    keywords: list[str],
    limit_per_source: int,
) -> ActiveRunState:
    controller = PipelineControl()
    progress_queue: Queue[tuple[str, object]] = Queue()
    source_states = {
        source_name: SourceProgressState(name=source_name)
        for source_name in selected_sources
    }
    worker = threading.Thread(
        target=_run_pipeline_worker,
        args=(
            settings,
            selected_sources,
            keywords,
            limit_per_source,
            controller,
            progress_queue,
        ),
        daemon=True,
    )
    active_run = ActiveRunState(
        source_order=list(selected_sources),
        source_states=source_states,
        progress_queue=progress_queue,
        controller=controller,
        worker=worker,
        started_at=time.time(),
        estimated_total_seconds=_estimate_total_seconds(
            len(selected_sources),
            limit_per_source,
        ),
    )
    st.session_state[ACTIVE_RUN_KEY] = active_run
    worker.start()
    return active_run


def _run_pipeline_worker(
    settings: Settings,
    selected_sources: list[str],
    keywords: list[str],
    limit_per_source: int,
    controller: PipelineControl,
    progress_queue: Queue[tuple[str, object]],
) -> None:
    try:
        pipeline = LeadPipeline(settings)
        result = pipeline.run(
            selected_sources,
            keywords,
            limit_per_source,
            progress_callback=lambda message: progress_queue.put(("progress", message)),
            control=controller,
        )
        progress_queue.put(("result", result))
    except Exception as exc:
        progress_queue.put(("error", str(exc)))


def _sync_active_run(active_run: ActiveRunState) -> None:
    _drain_progress_queue(active_run)
    if active_run.error is not None:
        active_run.status = "error"
        return
    if active_run.worker.is_alive():
        return
    if active_run.result is not None:
        active_run.status = (
            "stopped" if active_run.controller.should_stop() else "completed"
        )
        return
    if active_run.status == "stopping":
        active_run.status = "stopped"


def _drain_progress_queue(active_run: ActiveRunState) -> None:
    while True:
        try:
            kind, payload = active_run.progress_queue.get_nowait()
        except Empty:
            break

        if kind == "progress":
            source_name = _extract_source_name(
                str(payload),
                active_run.source_states,
            )
            if source_name is None:
                continue
            state = active_run.source_states[source_name]
            _apply_progress_message(state, str(payload))
            continue
        if kind == "result":
            active_run.result = payload if isinstance(payload, PipelineResult) else None
            continue
        if kind == "error":
            active_run.error = str(payload)


def _render_run_outcome(active_run: ActiveRunState) -> None:
    if active_run.error:
        st.error(active_run.error)
        return

    runtime_summary = _build_runtime_summary(active_run)
    if active_run.status == "paused":
        st.info(
            (
                "Run paused. Use Resume to continue or Stop to end the run. "
                f"{runtime_summary}"
            )
        )
    elif active_run.status == "running":
        st.info(f"Fetching data in the background. {runtime_summary}")
    elif active_run.status == "stopping":
        st.warning(
            f"Stopping the run. Waiting for in-flight work to finish. {runtime_summary}"
        )

    if active_run.result is None:
        return

    rows = active_run.result.rows
    if active_run.status == "stopped":
        st.warning(
            (
                f"Run stopped. Saved {len(rows)} validated leads to "
                f"{active_run.result.csv_path}"
            )
        )
    else:
        st.success(f"Saved {len(rows)} validated leads to {active_run.result.csv_path}")

    if not rows:
        st.warning(
            (
                "No validated leads were exported. Review the per-source cards "
                "below to see whether a site returned no sponsor data or "
                "whether contacts failed the email precheck."
            )
        )
    frame = active_run.result.dataframe()
    st.dataframe(frame, use_container_width=True, height=480)
    if active_run.result.csv_path.exists():
        st.download_button(
            "Download CSV",
            data=active_run.result.csv_path.read_bytes(),
            file_name=active_run.result.csv_path.name,
            mime="text/csv",
            use_container_width=True,
        )


def _run_is_active(active_run: ActiveRunState | None) -> bool:
    return active_run is not None and active_run.status in {
        "running",
        "paused",
        "stopping",
    }


def _run_is_paused(active_run: ActiveRunState | None) -> bool:
    return active_run is not None and active_run.status == "paused"


def _can_pause_or_resume(active_run: ActiveRunState | None) -> bool:
    return active_run is not None and active_run.status in {"running", "paused"}


def _can_stop(active_run: ActiveRunState | None) -> bool:
    return active_run is not None and active_run.status in {
        "running",
        "paused",
        "stopping",
    }


def _describe_run_state(active_run: ActiveRunState | None) -> str:
    if active_run is None:
        return "Idle"
    return active_run.status.replace("_", " ").title()


def _estimate_total_seconds(source_count: int, limit_per_source: int) -> int:
    base_seconds = 20
    per_source_seconds = 25
    per_page_seconds = 8
    return max(
        30,
        base_seconds
        + (source_count * per_source_seconds)
        + (source_count * limit_per_source * per_page_seconds),
    )


def _build_runtime_summary(active_run: ActiveRunState) -> str:
    elapsed_seconds = max(0, int(time.time() - active_run.started_at))
    remaining_seconds = max(0, active_run.estimated_total_seconds - elapsed_seconds)
    return (
        f"Elapsed: {_format_duration(elapsed_seconds)}. "
        f"Estimated time remaining: {_format_duration(remaining_seconds)}."
    )


def _format_duration(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, total_seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _create_source_panels(
    selected_sources: list[str],
) -> dict[str, dict[str, object]]:
    panels: dict[str, dict[str, object]] = {}
    for index in range(0, len(selected_sources), SOURCE_PANEL_COLUMNS):
        row_sources = selected_sources[index : index + SOURCE_PANEL_COLUMNS]
        columns = st.columns(SOURCE_PANEL_COLUMNS)
        for column_index, source_name in enumerate(row_sources):
            container = columns[column_index].container(
                border=True,
                height=SOURCE_PANEL_HEIGHT,
            )
            container.subheader(source_name.replace("_", " ").title())
            container.caption("Live source-specific progress")
            logs_container = container.container(height=SOURCE_LOG_HEIGHT, border=False)
            panels[source_name] = {
                "status": container.empty(),
                "metrics": container.empty(),
                "logs": logs_container.empty(),
            }
    return panels


def _render_source_panel(state: SourceProgressState, panel: dict[str, object]) -> None:
    panel["status"].markdown(
        (
            f"<div class='source-status'>"
            f"<span class='source-status__label'>Status</span>"
            f"<span class='source-status__value'>{state.status}</span>"
            f"</div>"
        ),
        unsafe_allow_html=True,
    )
    panel["metrics"].markdown(
        (
            f"<div class='source-metrics'>"
            f"<div><span>Event pages</span><strong>{state.event_pages}</strong></div>"
            f"<div><span>Events ready</span><strong>{state.events_ready}</strong></div>"
            f"<div><span>Accepted</span><strong>{state.accepted}</strong></div>"
            f"<div><span>Filtered</span><strong>{state.filtered}</strong></div>"
            f"<div><span>Skipped</span><strong>{state.skipped}</strong></div>"
            f"</div>"
        ),
        unsafe_allow_html=True,
    )
    if state.recent_logs:
        rendered_logs = "\n".join(
            f"{index + 1}. {line}" for index, line in enumerate(state.recent_logs)
        )
        panel["logs"].code(rendered_logs, language="text")
    else:
        panel["logs"].caption("No activity yet.")


def _extract_source_name(
    message: str, source_states: dict[str, SourceProgressState]
) -> str | None:
    for source_name in source_states:
        if message.startswith(f"{source_name}:") or message.startswith(
            f"[{source_name}]"
        ):
            return source_name
    return None


def _apply_progress_message(state: SourceProgressState, message: str) -> None:
    cleaned = message.strip()
    state.push_log(cleaned)

    if "discovered " in cleaned and "event page(s)" in cleaned:
        state.status = "Discovering events"
        try:
            state.event_pages = int(cleaned.split("discovered ", 1)[1].split(" ", 1)[0])
        except ValueError:
            pass
        return

    if "fetching event " in cleaned:
        state.status = "Fetching event pages"
        return

    if "event(s) ready for enrichment" in cleaned:
        state.status = "Enriching sponsors"
        try:
            state.events_ready = int(cleaned.split(": ", 1)[1].split(" ", 1)[0])
        except (IndexError, ValueError):
            pass
        return

    if "enriching sponsor" in cleaned:
        state.status = "Resolving contacts"
        return

    if "accepted lead for" in cleaned:
        state.status = "Accepted lead found"
        state.accepted += 1
        return

    if "filtered out" in cleaned:
        state.status = "Email precheck filtered lead"
        state.filtered += 1
        return

    if "skipped sponsor" in cleaned or "source failed" in cleaned:
        state.status = "Encountered issues"
        state.skipped += 1
        return

    if "no sponsors found" in cleaned:
        state.status = "No sponsors found"
        return

    if "queued event" in cleaned:
        state.status = "Queued for enrichment"
        return

    if "parsed '" in cleaned:
        state.status = "Parsed sponsor data"
        return

    if "validating '" in cleaned:
        state.status = "Validating email"


def _render_env_status(settings: Settings) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("SMTP sender", "set" if settings.smtp_from_email else "missing")
    col2.metric(
        "Website precheck", "on" if settings.website_precheck_required else "off"
    )
    col3.metric("SMTP precheck", "on" if settings.smtp_precheck_required else "off")
    col4.metric("Browser fallback", "on" if settings.use_browser_fallback else "off")


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="column"] {
            align-self: stretch;
        }

        .source-status {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 0.35rem;
        }

        .source-status__label {
            color: #5f6b7a;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .source-status__value {
            font-weight: 600;
            color: #132238;
        }

        .source-metrics {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.45rem 0.75rem;
            margin-bottom: 0.75rem;
        }

        .source-metrics div {
            background: #f6f8fb;
            border: 1px solid #e1e7ef;
            border-radius: 0.6rem;
            padding: 0.55rem 0.7rem;
        }

        .source-metrics span {
            display: block;
            color: #5f6b7a;
            font-size: 0.8rem;
            margin-bottom: 0.1rem;
        }

        .source-metrics strong {
            color: #132238;
            font-size: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
