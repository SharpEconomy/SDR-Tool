from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from hackindia_leads.config import Settings
from hackindia_leads.models import PUBLIC_LEAD_COLUMNS, Event, Lead, Sponsor
from hackindia_leads.services.email_validation import EmailValidatorService
from hackindia_leads.services.enrichment import ContactEnricher
from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.search import SearchClient
from hackindia_leads.sources import build_sources


@dataclass(slots=True)
class PipelineResult:
    rows: list[Lead]
    csv_path: Path

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [row.as_export_row() for row in self.rows], columns=PUBLIC_LEAD_COLUMNS
        )


class PipelineControl:
    def __init__(self) -> None:
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._stop_event = threading.Event()

    def pause(self) -> None:
        if not self._stop_event.is_set():
            self._resume_event.clear()

    def resume(self) -> None:
        self._resume_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._resume_event.set()

    def is_paused(self) -> bool:
        return not self._resume_event.is_set() and not self._stop_event.is_set()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self) -> bool:
        while not self._resume_event.wait(timeout=0.1):
            if self._stop_event.is_set():
                return False
        return not self._stop_event.is_set()


class LeadPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fetcher = PageFetcher(settings)
        self.search_client = SearchClient()
        self.sources = build_sources(self.fetcher, self.search_client)
        self.enricher = ContactEnricher(settings, self.fetcher, self.search_client)
        self.validator = EmailValidatorService(settings)
        self._progress_lock = threading.Lock()

    def run(
        self,
        selected_sources: list[str],
        keywords: list[str],
        limit_per_source: int,
        progress_callback: Callable[[str], None] | None = None,
        control: PipelineControl | None = None,
    ) -> PipelineResult:
        self._emit(progress_callback, "Starting scrape run")
        if not self._checkpoint(control):
            return self._finish_run([], progress_callback, stopped=True)

        source_results = self._fetch_sources(
            selected_sources,
            keywords,
            limit_per_source,
            progress_callback,
            control,
        )

        sponsor_jobs: list[tuple[str, Event, Sponsor]] = []
        for source_name, events in source_results:
            if not self._checkpoint(control):
                return self._finish_run([], progress_callback, stopped=True)
            for event in events:
                if not self._checkpoint(control):
                    return self._finish_run([], progress_callback, stopped=True)
                self._emit(
                    progress_callback,
                    (
                        f"{source_name}: queued event '{event.title}' "
                        f"with {len(event.sponsors)} sponsor(s)"
                    ),
                )
                for sponsor in event.sponsors:
                    if not self._checkpoint(control):
                        return self._finish_run([], progress_callback, stopped=True)
                    sponsor_jobs.append((source_name, event, sponsor))

        leads = self._enrich_sponsors(sponsor_jobs, progress_callback, control)
        return self._finish_run(
            leads,
            progress_callback,
            stopped=bool(control and control.should_stop()),
        )

    def _fetch_sources(
        self,
        selected_sources: list[str],
        keywords: list[str],
        limit_per_source: int,
        progress_callback: Callable[[str], None] | None,
        control: PipelineControl | None,
    ) -> list[tuple[str, list[Event]]]:
        results: list[tuple[str, list[Event]]] = []
        max_workers = max(
            1, min(len(selected_sources), self.settings.max_source_workers)
        )
        executor = ThreadPoolExecutor(max_workers=max_workers)
        stopped_early = False
        try:
            future_map = {}
            for source_name in selected_sources:
                if not self._checkpoint(control):
                    stopped_early = True
                    break
                source = self.sources[source_name]
                self._emit(progress_callback, f"Scanning source: {source_name}")
                future = executor.submit(
                    source.fetch_events,
                    keywords,
                    limit_per_source,
                    self._source_progress_callback(progress_callback),
                )
                future_map[future] = source_name

            pending = set(future_map)
            while pending:
                if not self._checkpoint(control):
                    stopped_early = True
                    break
                done, pending = wait(
                    pending,
                    timeout=0.1,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    source_name = future_map[future]
                    try:
                        events = future.result()
                        self._emit(
                            progress_callback,
                            (
                                f"{source_name}: {len(events)} "
                                f"event(s) ready for enrichment"
                            ),
                        )
                        results.append((source_name, events))
                    except Exception as exc:
                        self._emit(
                            progress_callback, f"{source_name}: source failed ({exc})"
                        )
        finally:
            executor.shutdown(wait=not stopped_early, cancel_futures=True)
        return results

    def _enrich_sponsors(
        self,
        sponsor_jobs: list[tuple[str, Event, Sponsor]],
        progress_callback: Callable[[str], None] | None,
        control: PipelineControl | None,
    ) -> list[Lead]:
        if not sponsor_jobs:
            return []

        leads: list[Lead] = []
        max_workers = max(
            1, min(len(sponsor_jobs), self.settings.max_enrichment_workers)
        )
        executor = ThreadPoolExecutor(max_workers=max_workers)
        stopped_early = False
        try:
            futures = set()
            for source_name, event, sponsor in sponsor_jobs:
                if not self._checkpoint(control):
                    stopped_early = True
                    break
                futures.add(
                    executor.submit(
                        self._process_sponsor,
                        source_name,
                        event,
                        sponsor,
                        progress_callback,
                        control,
                    )
                )

            pending = set(futures)
            while pending:
                if not self._checkpoint(control):
                    stopped_early = True
                    break
                done, pending = wait(
                    pending,
                    timeout=0.1,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    lead = future.result()
                    if lead is not None:
                        leads.append(lead)
        finally:
            executor.shutdown(wait=not stopped_early, cancel_futures=True)
        return leads

    def _process_sponsor(
        self,
        source_name: str,
        event: Event,
        sponsor: Sponsor,
        progress_callback: Callable[[str], None] | None,
        control: PipelineControl | None,
    ) -> Lead | None:
        if not self._checkpoint(control):
            return None
        try:
            self._emit(
                progress_callback,
                f"{source_name}: enriching sponsor '{sponsor.name}'",
            )
            website = self.enricher.resolve_website(sponsor)
            if not self._checkpoint(control):
                return None
            domain = self.enricher.resolve_domain(sponsor, website)
            website_is_valid = self.enricher.validate_website(website)
            if self.settings.website_precheck_required and not website_is_valid:
                self._emit(
                    progress_callback,
                    (
                        f"{source_name}: skipped sponsor "
                        f"'{sponsor.name}' (invalid website)"
                    ),
                )
                return None
            contacts = self.enricher.find_contact_candidates(sponsor, website, domain)
        except Exception as exc:
            self._emit(
                progress_callback,
                f"{source_name}: skipped sponsor '{sponsor.name}' ({exc})",
            )
            return None

        best_lead: Lead | None = None
        for contact in contacts:
            if not self._checkpoint(control):
                if self.settings.smtp_precheck_required:
                    return None
                return best_lead
            self._emit(
                progress_callback,
                f"{source_name}: validating '{contact.email}' for '{sponsor.name}'",
            )
            validation = self.validator.validate(contact.email)
            lead = Lead(
                source=event.source,
                event_name=event.title,
                event_url=event.url,
                sponsor_company=sponsor.name,
                sponsor_website=website,
                sponsor_domain=domain,
                decision_maker_name=contact.full_name,
                decision_maker_title=contact.title,
                decision_maker_email=contact.email,
                contact_source=contact.source,
                linkedin_url=contact.linkedin_url,
                email_smtp_code=validation.smtp_code,
                email_score=validation.score,
                email_accepted=bool(
                    validation.accepted
                    and validation.score >= self.settings.min_validation_score
                ),
                evidence=sponsor.evidence,
            )
            if best_lead is None or lead.email_score > best_lead.email_score:
                best_lead = lead
            if not self.settings.smtp_precheck_required or lead.email_accepted:
                self._emit(
                    progress_callback,
                    f"{source_name}: accepted lead for '{sponsor.name}'",
                )
                return lead

        if best_lead is not None and not self.settings.smtp_precheck_required:
            self._emit(
                progress_callback,
                f"{source_name}: accepted lead for '{sponsor.name}'",
            )
            return best_lead

        self._emit(
            progress_callback,
            f"{source_name}: filtered out '{sponsor.name}' during precheck",
        )
        return None

    def _write_csv(self, leads: list[Lead]) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.settings.results_dir / f"hackindia_leads_{timestamp}.csv"
        pd.DataFrame(
            [lead.as_export_row() for lead in leads], columns=PUBLIC_LEAD_COLUMNS
        ).to_csv(path, index=False)
        return path

    def _finish_run(
        self,
        leads: list[Lead],
        progress_callback: Callable[[str], None] | None,
        *,
        stopped: bool,
    ) -> PipelineResult:
        csv_path = self._write_csv(leads)
        if stopped:
            self._emit(
                progress_callback,
                f"Run stopped with {len(leads)} validated lead(s). CSV: {csv_path}",
            )
        else:
            self._emit(
                progress_callback,
                (
                    f"Finished run with {len(leads)} validated lead(s). "
                    f"CSV: {csv_path}"
                ),
            )
        return PipelineResult(rows=leads, csv_path=csv_path)

    def _checkpoint(self, control: PipelineControl | None) -> bool:
        if control is None:
            return True
        return control.wait_if_paused()

    def _source_progress_callback(
        self, progress_callback: Callable[[str], None] | None
    ) -> Callable[[str], None]:
        def callback(message: str) -> None:
            self._emit(progress_callback, message)

        return callback

    def _emit(
        self, progress_callback: Callable[[str], None] | None, message: str
    ) -> None:
        if progress_callback is not None:
            with self._progress_lock:
                progress_callback(message)
