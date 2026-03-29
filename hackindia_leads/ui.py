from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Queue

import streamlit as st

from hackindia_leads.config import Settings
from hackindia_leads.models import PUBLIC_LEAD_COLUMNS
from hackindia_leads.pipeline import LeadPipeline, PipelineControl, PipelineResult
from hackindia_leads.sources.custom import normalize_custom_urls

SOURCE_PANEL_COLUMNS = 2
SOURCE_PANEL_HEIGHT = 360
SOURCE_LOG_HEIGHT = 190
ACTIVE_RUN_KEY = "active_run"
LOADING_TABLE_ROWS = 6
TABLE_MAX_HEIGHT = 480
TABLE_MIN_HEIGHT = 110
TABLE_HEADER_HEIGHT = 40
TABLE_ROW_HEIGHT = 35
TABLE_VERTICAL_PADDING = 18


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
    finished_at: float | None = None
    completion_notice_shown: bool = False


def render() -> None:
    st.set_page_config(page_title="HackIndia Lead Finder", layout="wide")
    _inject_styles()
    st.title("HackIndia Lead Finder")
    st.caption(
        (
            "Sponsor-lead scraper focused on Tech/AI/Web3 companies, using "
            "optional OpenAI-backed review with a US/India priority."
        )
    )

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
            format_func=_format_source_label,
        )
        keywords_raw = st.text_input(
            "Themes", value=",".join(settings.default_keywords)
        )
        custom_urls_raw = st.text_area(
            "Custom event URLs",
            value="",
            help=(
                "Paste one or more hackathon or event page URLs. Each URL will be "
                "scraped like an additional source."
            ),
            height=110,
        )
        settings.use_openai_qualification = st.checkbox(
            "Use OpenAI Qualification",
            value=settings.use_openai_qualification,
            help=(
                "Turn this off to force the deterministic non-LLM review flow "
                "for this run. If OpenAI is unavailable, the app falls back "
                "automatically."
            ),
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

    if start_clicked:
        custom_urls = _parse_custom_urls(custom_urls_raw)
        effective_sources = list(selected_sources)
        if custom_urls:
            effective_sources.append("custom")
        if not effective_sources:
            st.error("Select at least one source or enter at least one custom URL.")
            return
        if not settings.smtp_from_email:
            st.error(
                "Set SMTP_FROM_EMAIL in your .env file before running the scraper."
            )
            return
        if (
            settings.qualification_enabled
            and settings.use_openai_qualification
            and not settings.openai_api_key
        ):
            st.warning(
                (
                    "OPENAI_API_KEY is not set. Using the non-LLM "
                    "fallback flow for sponsor and contact review in this run."
                )
            )
        keywords = [item.strip() for item in keywords_raw.split(",") if item.strip()]
        st.session_state[ACTIVE_RUN_KEY] = None
        active_run = _start_background_run(
            settings,
            effective_sources,
            keywords,
            int(limit_per_source),
            custom_urls,
        )

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

    active_run = _get_active_run()
    if active_run is None:
        return

    _sync_active_run(active_run)
    _show_completion_notice(active_run)
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
    custom_urls: list[str] | None = None,
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
            custom_urls,
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
            settings,
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
    custom_urls: list[str] | None,
    controller: PipelineControl,
    progress_queue: Queue[tuple[str, object]],
) -> None:
    try:
        pipeline = LeadPipeline(settings)
        result = pipeline.run(
            selected_sources,
            keywords,
            limit_per_source,
            custom_urls=custom_urls,
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
        if active_run.finished_at is None:
            active_run.finished_at = time.time()
        active_run.status = (
            "stopped" if active_run.controller.should_stop() else "completed"
        )
        return
    if active_run.status == "stopping":
        active_run.status = "stopped"


def _show_completion_notice(active_run: ActiveRunState) -> None:
    if active_run.completion_notice_shown:
        return
    if active_run.result is None or active_run.finished_at is None:
        return
    if active_run.status not in {"completed", "stopped"}:
        return

    elapsed_seconds = max(0, int(active_run.finished_at - active_run.started_at))
    prefix = "Run stopped" if active_run.status == "stopped" else "Run finished"
    st.info(
        (f"{prefix} in {_format_duration(elapsed_seconds)}. " "Output table is ready.")
    )
    active_run.completion_notice_shown = True


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
        _render_loading_table()
        return

    rows = active_run.result.rows
    if active_run.status == "stopped":
        st.warning(f"Run stopped. {len(rows)} validated lead(s) are ready to download.")
    else:
        st.success(f"{len(rows)} validated lead(s) are ready to download.")

    if not rows:
        st.warning(
            (
                "No validated leads were exported. Review the per-source cards "
                "below to see whether a site returned no sponsor data or "
                "whether contacts failed the email precheck."
            )
        )
    if active_run.result.export_bytes:
        st.download_button(
            "Download Excel",
            data=active_run.result.export_bytes,
            file_name=active_run.result.export_name,
            mime=(
                "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )
    frame = active_run.result.dataframe()
    st.dataframe(
        frame,
        use_container_width=True,
        height=_dataframe_height_for_rows(len(rows)),
    )
    _render_filtered_sponsors_download(active_run.result)


def _render_loading_table() -> None:
    header_cells = "".join(
        f"<div class='loading-table__header-cell'>{column}</div>"
        for column in PUBLIC_LEAD_COLUMNS
    )
    body_rows = []
    for row_index in range(LOADING_TABLE_ROWS):
        cells = []
        for column_index, _ in enumerate(PUBLIC_LEAD_COLUMNS):
            width_class = _loading_cell_width_class(row_index, column_index)
            cells.append(
                (
                    "<div class='loading-table__cell'>"
                    f"<span class='loading-table__bar {width_class}'></span>"
                    "</div>"
                )
            )
        body_rows.append(f"<div class='loading-table__row'>{''.join(cells)}</div>")
    st.markdown(
        (
            "<div class='loading-table'>"
            f"<div class='loading-table__header'>{header_cells}</div>"
            f"<div class='loading-table__body'>{''.join(body_rows)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_filtered_sponsors_download(result: PipelineResult) -> None:
    if not result.filtered_export_bytes or not result.filtered_export_name:
        return

    st.download_button(
        "Download Filtered Sponsors",
        data=result.filtered_export_bytes,
        file_name=result.filtered_export_name,
        mime=("application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"),
        use_container_width=True,
    )


def _loading_cell_width_class(row_index: int, column_index: int) -> str:
    width_variants = (
        "loading-table__bar--short",
        "loading-table__bar--medium",
        "loading-table__bar--long",
    )
    return width_variants[(row_index + column_index) % len(width_variants)]


def _dataframe_height_for_rows(row_count: int) -> int:
    content_height = (
        TABLE_HEADER_HEIGHT
        + (max(0, row_count) * TABLE_ROW_HEIGHT)
        + TABLE_VERTICAL_PADDING
    )
    return max(TABLE_MIN_HEIGHT, min(TABLE_MAX_HEIGHT, content_height))


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


def _estimate_total_seconds(
    settings: Settings,
    source_count: int,
    limit_per_source: int,
) -> int:
    source_workers = max(1, min(source_count, settings.max_source_workers))
    event_count = max(1, source_count * limit_per_source)
    enrichment_workers = max(1, settings.max_enrichment_workers)
    estimated_sponsors_per_event = 8

    base_seconds = 20
    per_source_discovery_seconds = 18
    per_event_fetch_seconds = 8
    if settings.use_browser_fallback:
        per_source_discovery_seconds += 4
        per_event_fetch_seconds += 4

    per_sponsor_seconds = 4
    if settings.website_precheck_required:
        per_sponsor_seconds += 2
    if settings.qualification_enabled:
        per_sponsor_seconds += 4
        if settings.use_openai_qualification:
            per_sponsor_seconds += 3
    if settings.smtp_precheck_required:
        per_sponsor_seconds += 4
    else:
        per_sponsor_seconds += 1

    discovery_seconds = (
        (source_count * per_source_discovery_seconds) + source_workers - 1
    ) // source_workers
    event_fetch_seconds = (
        (event_count * per_event_fetch_seconds) + source_workers - 1
    ) // source_workers
    sponsor_jobs = event_count * estimated_sponsors_per_event
    enrichment_seconds = (
        (sponsor_jobs * per_sponsor_seconds) + enrichment_workers - 1
    ) // enrichment_workers

    return max(
        75,
        base_seconds
        + discovery_seconds
        + event_fetch_seconds
        + enrichment_seconds,
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


def _format_source_label(source_name: str) -> str:
    return source_name.replace("_", " ").upper()


def _parse_custom_urls(raw_value: str) -> list[str]:
    return normalize_custom_urls(raw_value.replace(",", "\n").splitlines())


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
            container.subheader(_format_source_label(source_name))
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
        parsed_count = _extract_progress_count(cleaned, "discovered ")
        if parsed_count is not None:
            state.event_pages = parsed_count
        return

    if "fetching event " in cleaned:
        state.status = "Fetching event pages"
        return

    if "event(s) ready for enrichment" in cleaned:
        state.status = "Enriching sponsors"
        parsed_count = _extract_progress_count(cleaned, ": ")
        if parsed_count is not None:
            state.events_ready = parsed_count
        return

    if "enriching sponsor" in cleaned:
        state.status = "Resolving contacts"
        return

    if "qualified sponsor" in cleaned:
        state.status = "Applying target fit"
        return

    if "filtered sponsor" in cleaned and "fit filter" in cleaned:
        state.status = "Filtered by target fit"
        state.filtered += 1
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


def _extract_progress_count(message: str, marker: str) -> int | None:
    if marker not in message:
        return None
    try:
        return int(message.split(marker, 1)[1].split(" ", 1)[0])
    except (IndexError, ValueError):
        return None


def _inject_styles() -> None:
    column_count = len(PUBLIC_LEAD_COLUMNS)
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

        .loading-table {
            border: 1px solid #e1e7ef;
            border-radius: 0.9rem;
            overflow: hidden;
            background: #ffffff;
        }

        .loading-table__header,
        .loading-table__row {
            display: grid;
            grid-template-columns: repeat(__COLUMN_COUNT__, minmax(120px, 1fr));
            gap: 0;
        }

        .loading-table__header {
            background: #f6f8fb;
            border-bottom: 1px solid #e1e7ef;
        }

        .loading-table__header-cell {
            padding: 0.85rem 0.9rem;
            font-size: 0.76rem;
            font-weight: 600;
            color: #5f6b7a;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            border-right: 1px solid #eef2f7;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .loading-table__header-cell:last-child,
        .loading-table__cell:last-child {
            border-right: none;
        }

        .loading-table__body {
            max-height: 480px;
            overflow: auto;
        }

        .loading-table__row:not(:last-child) {
            border-bottom: 1px solid #eef2f7;
        }

        .loading-table__cell {
            padding: 0.95rem 0.9rem;
            border-right: 1px solid #f2f5f9;
        }

        .loading-table__bar {
            display: block;
            height: 0.8rem;
            border-radius: 999px;
            background: linear-gradient(
                90deg,
                #e8edf4 0%,
                #f5f8fb 45%,
                #e8edf4 100%
            );
            background-size: 200% 100%;
            animation: loading-shimmer 1.2s ease-in-out infinite;
        }

        .loading-table__bar--short {
            width: 48%;
        }

        .loading-table__bar--medium {
            width: 68%;
        }

        .loading-table__bar--long {
            width: 86%;
        }

        @keyframes loading-shimmer {
            0% {
                background-position: 200% 0;
            }
            100% {
                background-position: -200% 0;
            }
        }
        </style>
        """.replace("__COLUMN_COUNT__", str(column_count)),
        unsafe_allow_html=True,
    )
