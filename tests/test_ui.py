from __future__ import annotations

from queue import Queue

from growth_engine.ui import app as ui


def test_parse_list_input_dedupes_items() -> None:
    parsed = ui._parse_list_input("retail, distribution\nretail")

    assert parsed == ["retail", "distribution"]


def test_parse_multiline_urls_normalizes_scheme() -> None:
    parsed = ui._parse_multiline_urls("demo.example\nhttps://demo.example")

    assert parsed == ["https://demo.example"]


def test_sync_active_run_sets_result_status() -> None:
    queue = Queue()
    active_run = ui.ActiveRunState(
        progress_queue=queue,
        controller=ui.PipelineControl(),
        worker=type("Worker", (), {"is_alive": lambda self: False})(),
        started_at=0.0,
    )
    queue.put(("progress", "Profile normalized"))
    queue.put(("error", None))
    ui._sync_active_run(active_run)

    assert active_run.log_lines == ["Profile normalized"]
