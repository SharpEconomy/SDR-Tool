from __future__ import annotations

from pathlib import Path
from queue import Queue

from hackindia_leads import ui
from hackindia_leads.pipeline import PipelineControl


class FakeSidebar:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeColumn:
    def __init__(self, button_presses=None, events=None) -> None:
        self.metrics = []
        self.containers = []
        self.button_presses = {} if button_presses is None else button_presses
        self.events = [] if events is None else events

    def metric(self, label, value) -> None:
        self.metrics.append((label, value))

    def container(self, border=False, height=None) -> "FakeContainer":
        container = FakeContainer(border=border, height=height)
        self.containers.append(container)
        self.events.append("container")
        return container

    def button(self, label, use_container_width=False, disabled=False) -> bool:
        if disabled:
            return False
        return self.button_presses.get(label, False)


class FakePlaceholder:
    def __init__(self) -> None:
        self.markdowns = []
        self.codes = []
        self.captions = []

    def markdown(self, text, unsafe_allow_html=False) -> None:
        self.markdowns.append((text, unsafe_allow_html))

    def code(self, text, language="text") -> None:
        self.codes.append((text, language))

    def caption(self, text) -> None:
        self.captions.append(text)


class FakeContainer:
    def __init__(self, border=False, height=None) -> None:
        self.subheaders = []
        self.captions = []
        self.placeholders = []
        self.containers = []
        self.border = border
        self.height = height

    def subheader(self, text) -> None:
        self.subheaders.append(text)

    def caption(self, text) -> None:
        self.captions.append(text)

    def empty(self) -> FakePlaceholder:
        placeholder = FakePlaceholder()
        self.placeholders.append(placeholder)
        return placeholder

    def container(self, border=False, height=None) -> "FakeContainer":
        container = FakeContainer(border=border, height=height)
        self.containers.append(container)
        return container


class FakeWorker:
    def __init__(self, alive: bool) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


class FakeResult:
    def __init__(self, export_name: str, export_bytes: bytes, rows=None) -> None:
        self.rows = [] if rows is None else rows
        self.export_name = export_name
        self.export_bytes = export_bytes

    def dataframe(self):
        return "FRAME"


class FakeStreamlit:
    def __init__(
        self,
        *,
        buttons=None,
        sources=None,
        keywords="ai,web3",
        custom_urls="",
        use_claude_qualification=None,
    ) -> None:
        self.sidebar = FakeSidebar()
        self.session_state = {}
        self.button_presses = buttons or {}
        self.sources = ["ethglobal"] if sources is None else sources
        self.keywords = keywords
        self.custom_urls = custom_urls
        self.use_claude_qualification = use_claude_qualification
        self.errors = []
        self.successes = []
        self.warnings = []
        self.infos = []
        self.downloads = []
        self.columns_created = []
        self.containers = []
        self.markdowns = []
        self.events = []
        self.rerun_called = 0

    def set_page_config(self, **kwargs) -> None:
        self.page_config = kwargs

    def title(self, text) -> None:
        self.title_text = text

    def caption(self, text) -> None:
        self.caption_text = text

    def subheader(self, text) -> None:
        self.subheader_text = text

    def markdown(self, text, unsafe_allow_html=False) -> None:
        self.markdowns.append((text, unsafe_allow_html))

    def multiselect(self, label, options, default, format_func=None):
        self.multiselect_format_func = format_func
        return self.sources

    def text_input(self, label, value):
        return self.keywords

    def text_area(self, label, value="", help=None, height=None):
        return self.custom_urls

    def checkbox(self, label, value=False, help=None):
        if self.use_claude_qualification is None:
            return value
        return self.use_claude_qualification

    def number_input(self, label, min_value, max_value, value, step):
        return value

    def button(self, label, use_container_width=False, disabled=False):
        if disabled:
            return False
        return self.button_presses.get(label, False)

    def columns(self, count):
        cols = [FakeColumn(self.button_presses, self.events) for _ in range(count)]
        self.columns_created.append(cols)
        return cols

    def error(self, text) -> None:
        self.errors.append(text)

    def info(self, text) -> None:
        self.infos.append(text)

    def warning(self, text) -> None:
        self.warnings.append(text)

    def success(self, text) -> None:
        self.successes.append(text)

    def dataframe(self, frame, use_container_width, height) -> None:
        self.dataframe_frame = frame
        self.dataframe_height = height
        self.events.append("dataframe")

    def download_button(
        self, label, data, file_name, mime, use_container_width
    ) -> None:
        self.downloads.append(file_name)
        self.events.append("download")

    def container(self, border=False, height=None) -> FakeContainer:
        container = FakeContainer(border=border, height=height)
        self.containers.append(container)
        self.events.append("container")
        return container

    def rerun(self) -> None:
        self.rerun_called += 1


def _build_active_run(
    export_name: str,
    *,
    status="completed",
    alive=False,
    rows=None,
    started_at=0.0,
    estimated_total_seconds=120,
    finished_at=None,
    completion_notice_shown=False,
) -> ui.ActiveRunState:
    source_states = {"ethglobal": ui.SourceProgressState(name="ethglobal")}
    controller = PipelineControl()
    if status == "stopping":
        controller.stop()
    active_run = ui.ActiveRunState(
        source_order=["ethglobal"],
        source_states=source_states,
        progress_queue=Queue(),
        controller=controller,
        worker=FakeWorker(alive=alive),
        started_at=started_at,
        estimated_total_seconds=estimated_total_seconds,
        status=status,
        result=FakeResult(export_name, b"excel-bytes", rows=rows),
        finished_at=finished_at,
        completion_notice_shown=completion_notice_shown,
    )
    return active_run


def test_render_env_status_displays_metrics(settings, monkeypatch) -> None:
    fake_st = FakeStreamlit(sources=settings.default_sources)
    monkeypatch.setattr(ui, "st", fake_st)

    ui._render_env_status(settings)

    metrics = fake_st.columns_created[0]
    assert metrics[0].metrics[0] == ("SMTP sender", "set")
    assert metrics[1].metrics[0] == ("Website precheck", "on")
    assert metrics[2].metrics[0] == ("SMTP precheck", "on")
    assert metrics[3].metrics[0] == ("Browser fallback", "on")
    assert metrics[4].metrics[0] == ("Fit filter", "on")
    assert metrics[5].metrics[0] == ("Claude key", "set")


def test_render_shows_error_when_smtp_sender_missing(settings, monkeypatch) -> None:
    fake_st = FakeStreamlit(buttons={"Start": True})
    monkeypatch.setattr(ui, "st", fake_st)
    settings.smtp_from_email = ""
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)

    ui.render()

    assert fake_st.errors == [
        "Set SMTP_FROM_EMAIL in your .env file before running the scraper."
    ]


def test_render_warns_and_starts_when_claude_key_missing(settings, monkeypatch) -> None:
    fake_st = FakeStreamlit(buttons={"Start": True})
    monkeypatch.setattr(ui, "st", fake_st)
    settings.anthropic_api_key = ""
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)

    captured = {"started": False}

    def fake_start(
        incoming_settings,
        selected_sources,
        keywords,
        limit_per_source,
        custom_urls,
    ):
        captured["started"] = True
        active_run = _build_active_run("result.xlsx")
        fake_st.session_state[ui.ACTIVE_RUN_KEY] = active_run
        return active_run

    monkeypatch.setattr(ui, "_start_background_run", fake_start)

    ui.render()

    assert captured["started"] is True
    assert fake_st.warnings[:1] == [
        (
            "ANTHROPIC_API_KEY is not set. Using the non-LLM "
            "fallback flow for sponsor and contact review in this run."
        )
    ]


def test_render_start_displays_completed_result(
    settings, monkeypatch, tmp_path: Path
) -> None:
    export_name = "result.xlsx"
    fake_st = FakeStreamlit(buttons={"Start": True})
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)
    monkeypatch.setattr(ui.time, "time", lambda: 0.0)

    def fake_start(
        incoming_settings,
        selected_sources,
        keywords,
        limit_per_source,
        custom_urls,
    ):
        active_run = _build_active_run(export_name)
        fake_st.session_state[ui.ACTIVE_RUN_KEY] = active_run
        return active_run

    monkeypatch.setattr(ui, "_start_background_run", fake_start)

    ui.render()

    assert fake_st.successes == ["0 validated lead(s) are ready to download."]
    assert "Run finished in 0s. Output table is ready." in fake_st.infos
    assert fake_st.downloads == [export_name]
    source_columns = fake_st.columns_created[2]
    source_container = source_columns[0].containers[0]
    assert source_container.subheaders == ["ETHGLOBAL"]
    assert source_container.height == ui.SOURCE_PANEL_HEIGHT
    assert source_container.containers[0].height == ui.SOURCE_LOG_HEIGHT
    assert fake_st.dataframe_height == ui._dataframe_height_for_rows(0)
    assert fake_st.events.index("download") < fake_st.events.index("dataframe")
    assert fake_st.events.index("dataframe") < fake_st.events.index("container")
    assert fake_st.events.index("download") < fake_st.events.index("container")
    assert fake_st.multiselect_format_func("ethglobal") == "ETHGLOBAL"


def test_render_shows_completion_text_once(settings, monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)
    fake_st.session_state[ui.ACTIVE_RUN_KEY] = _build_active_run(
        "result.xlsx",
        status="completed",
        alive=False,
        started_at=0.0,
        finished_at=125.0,
    )

    ui.render()
    ui.render()

    assert fake_st.infos.count("Run finished in 2m 5s. Output table is ready.") == 1


def test_render_sidebar_qualification_toggle_overrides_settings(
    settings, monkeypatch
) -> None:
    fake_st = FakeStreamlit(buttons={"Start": True}, use_claude_qualification=False)
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)

    captured = {}

    def fake_start(
        incoming_settings,
        selected_sources,
        keywords,
        limit_per_source,
        custom_urls,
    ):
        captured["use_claude_qualification"] = (
            incoming_settings.use_claude_qualification
        )
        active_run = _build_active_run("result.xlsx")
        fake_st.session_state[ui.ACTIVE_RUN_KEY] = active_run
        return active_run

    monkeypatch.setattr(ui, "_start_background_run", fake_start)

    ui.render()

    assert captured["use_claude_qualification"] is False


def test_render_does_not_warn_when_claude_is_disabled(settings, monkeypatch) -> None:
    fake_st = FakeStreamlit(
        buttons={"Start": True},
        use_claude_qualification=False,
    )
    monkeypatch.setattr(ui, "st", fake_st)
    settings.anthropic_api_key = ""
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)

    def fake_start(
        incoming_settings,
        selected_sources,
        keywords,
        limit_per_source,
        custom_urls,
    ):
        active_run = _build_active_run("result.xlsx")
        fake_st.session_state[ui.ACTIVE_RUN_KEY] = active_run
        return active_run

    monkeypatch.setattr(ui, "_start_background_run", fake_start)

    ui.render()

    assert not any("ANTHROPIC_API_KEY is not set" in text for text in fake_st.warnings)


def test_render_starts_with_custom_urls_only(settings, monkeypatch) -> None:
    fake_st = FakeStreamlit(
        buttons={"Start": True},
        sources=[],
        custom_urls="demo.example/event\nhttps://two.example/hackathon",
    )
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)

    captured = {}

    def fake_start(
        incoming_settings,
        selected_sources,
        keywords,
        limit_per_source,
        custom_urls,
    ):
        captured["selected_sources"] = selected_sources
        captured["custom_urls"] = custom_urls
        active_run = _build_active_run("result.xlsx")
        fake_st.session_state[ui.ACTIVE_RUN_KEY] = active_run
        return active_run

    monkeypatch.setattr(ui, "_start_background_run", fake_start)

    ui.render()

    assert captured["selected_sources"] == ["custom"]
    assert captured["custom_urls"] == [
        "https://demo.example/event",
        "https://two.example/hackathon",
    ]


def test_parse_custom_urls_normalizes_and_dedupes() -> None:
    parsed = ui._parse_custom_urls(
        "demo.example/event\nhttps://demo.example/event\nbad\n"
    )

    assert parsed == ["https://demo.example/event"]


def test_render_pause_button_updates_active_run_status(
    settings, monkeypatch, tmp_path: Path
) -> None:
    fake_st = FakeStreamlit(buttons={"Pause": True})
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)
    fake_st.session_state[ui.ACTIVE_RUN_KEY] = _build_active_run(
        "result.xlsx",
        status="running",
        alive=True,
    )

    ui.render()

    active_run = fake_st.session_state[ui.ACTIVE_RUN_KEY]
    assert active_run.status == "paused"


def test_render_shows_runtime_estimate_while_running(
    settings, monkeypatch, tmp_path: Path
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)
    monkeypatch.setattr(ui.time, "time", lambda: 30.0)
    fake_st.session_state[ui.ACTIVE_RUN_KEY] = _build_active_run(
        "result.xlsx",
        status="running",
        alive=True,
        started_at=0.0,
        estimated_total_seconds=120,
    )

    ui.render()

    assert any("Estimated time remaining: 1m 30s." in text for text in fake_st.infos)


def test_estimate_total_seconds_increases_with_expensive_checks(settings) -> None:
    baseline = ui._estimate_total_seconds(settings, 2, 3)

    settings.use_claude_qualification = False
    settings.qualification_enabled = False
    settings.smtp_precheck_required = False
    settings.website_precheck_required = False
    settings.use_browser_fallback = False

    lighter = ui._estimate_total_seconds(settings, 2, 3)

    assert baseline > lighter


def test_render_shows_non_empty_loading_table_while_running(
    settings, monkeypatch, tmp_path: Path
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)
    fake_st.session_state[ui.ACTIVE_RUN_KEY] = ui.ActiveRunState(
        source_order=["ethglobal"],
        source_states={"ethglobal": ui.SourceProgressState(name="ethglobal")},
        progress_queue=Queue(),
        controller=PipelineControl(),
        worker=FakeWorker(alive=True),
        started_at=0.0,
        estimated_total_seconds=120,
        status="running",
        result=None,
    )

    ui.render()

    assert not hasattr(fake_st, "dataframe_frame")
    assert any("loading-table" in text for text, _ in fake_st.markdowns)
    assert any(
        column in text
        for text, _ in fake_st.markdowns
        for column in ui.PUBLIC_LEAD_COLUMNS
    )


def test_render_stop_button_requests_stop(
    settings, monkeypatch, tmp_path: Path
) -> None:
    fake_st = FakeStreamlit(buttons={"Stop": True})
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui.Settings, "load", lambda: settings)
    fake_st.session_state[ui.ACTIVE_RUN_KEY] = _build_active_run(
        "result.xlsx",
        status="running",
        alive=True,
    )

    ui.render()

    active_run = fake_st.session_state[ui.ACTIVE_RUN_KEY]
    assert active_run.status == "stopping"
    assert active_run.controller.should_stop() is True
