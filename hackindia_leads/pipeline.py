from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

import pandas as pd

from hackindia_leads.config import Settings
from hackindia_leads.models import (
    PUBLIC_LEAD_COLUMNS,
    CompanyQualification,
    Event,
    Lead,
    Sponsor,
)
from hackindia_leads.services.company_qualification import CompanyQualifier
from hackindia_leads.services.email_validation import EmailValidatorService
from hackindia_leads.services.enrichment import ContactEnricher
from hackindia_leads.services.fetcher import PageFetcher
from hackindia_leads.services.search import SearchClient
from hackindia_leads.sources import build_sources


@dataclass(slots=True)
class PipelineResult:
    rows: list[Lead]
    export_name: str
    export_bytes: bytes

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
        self.search_client = SearchClient(settings)
        self.sources = build_sources(self.fetcher, self.search_client)
        self.enricher = ContactEnricher(settings, self.fetcher, self.search_client)
        self.qualifier = CompanyQualifier(settings, self.search_client)
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
            website_is_valid, qualification = self._resolve_sponsor_checks(
                source_name,
                event,
                sponsor,
                website,
                domain,
                progress_callback,
                control,
            )
            if not self._checkpoint(control):
                return None
            if self.settings.website_precheck_required and not website_is_valid:
                self._emit(
                    progress_callback,
                    (
                        f"{source_name}: skipped sponsor "
                        f"'{sponsor.name}' (invalid website)"
                    ),
                )
                return None
            if qualification is not None and not qualification.accepted:
                self._emit(
                    progress_callback,
                    (
                        f"{source_name}: filtered sponsor '{sponsor.name}' "
                        "by fit filter"
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

        return self._select_lead_for_contacts(
            source_name,
            event,
            sponsor,
            website,
            domain,
            qualification,
            contacts,
            progress_callback,
            control,
        )

    def _resolve_sponsor_checks(
        self,
        source_name: str,
        event: Event,
        sponsor: Sponsor,
        website: str | None,
        domain: str | None,
        progress_callback: Callable[[str], None] | None,
        control: PipelineControl | None,
    ) -> tuple[bool, CompanyQualification | None]:
        qualification_enabled = self.qualifier.is_enabled()
        qualification = None
        website_is_valid = False
        max_workers = 2 if qualification_enabled else 1
        future_names: dict[object, str] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_names[executor.submit(self.enricher.validate_website, website)] = (
                "website"
            )
            if qualification_enabled:
                future_names[
                    executor.submit(
                        self.qualifier.qualify,
                        sponsor,
                        event,
                        website,
                        domain,
                    )
                ] = "qualification"
            else:
                self._emit(
                    progress_callback,
                    f"{source_name}: qualification skipped for '{sponsor.name}'",
                )

            pending = set(future_names)
            while pending:
                if not self._checkpoint(control):
                    return False, None, []
                done, pending = wait(
                    pending,
                    timeout=0.1,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    result_name = future_names[future]
                    result = future.result()
                    if result_name == "website":
                        website_is_valid = bool(result)
                    elif result_name == "qualification":
                        qualification = result
                        if qualification is not None:
                            self._emit(
                                progress_callback,
                                f"{source_name}: qualified sponsor '{sponsor.name}'",
                            )

        return website_is_valid, qualification

    def _select_lead_for_contacts(
        self,
        source_name: str,
        event: Event,
        sponsor: Sponsor,
        website: str | None,
        domain: str | None,
        qualification: CompanyQualification | None,
        contacts: list,
        progress_callback: Callable[[str], None] | None,
        control: PipelineControl | None,
    ) -> Lead | None:
        best_lead: Lead | None = None
        validations_by_email = self._validate_contacts(
            source_name,
            sponsor,
            contacts,
            progress_callback,
            control,
        )
        if validations_by_email is None:
            return None if self.settings.smtp_precheck_required else best_lead

        for contact in contacts:
            if not self._checkpoint(control):
                if self.settings.smtp_precheck_required:
                    return None
                return best_lead
            validation = validations_by_email[contact.email]
            lead = self._build_lead(
                event,
                sponsor,
                website,
                domain,
                qualification,
                contact,
                validation,
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

    def _validate_contacts(
        self,
        source_name: str,
        sponsor: Sponsor,
        contacts: list,
        progress_callback: Callable[[str], None] | None,
        control: PipelineControl | None,
    ) -> dict[str, object] | None:
        if not contacts:
            return {}

        if not self.settings.smtp_precheck_required:
            contact = contacts[0]
            self._emit(
                progress_callback,
                f"{source_name}: validating '{contact.email}' for '{sponsor.name}'",
            )
            return {contact.email: self.validator.validate(contact.email)}

        max_workers = max(1, min(len(contacts), 4))
        future_emails: dict[object, str] = {}
        validations_by_email: dict[str, object] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for contact in contacts:
                if not self._checkpoint(control):
                    return None
                self._emit(
                    progress_callback,
                    f"{source_name}: validating '{contact.email}' for '{sponsor.name}'",
                )
                future_emails[
                    executor.submit(self.validator.validate, contact.email)
                ] = contact.email

            pending = set(future_emails)
            while pending:
                if not self._checkpoint(control):
                    return None
                done, pending = wait(
                    pending,
                    timeout=0.1,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    email = future_emails[future]
                    validations_by_email[email] = future.result()

        return validations_by_email

    def _build_lead(
        self,
        event: Event,
        sponsor: Sponsor,
        website: str | None,
        domain: str | None,
        qualification: CompanyQualification | None,
        contact,
        validation,
    ) -> Lead:
        return Lead(
            source=event.source,
            event_name=event.title,
            event_url=event.url,
            sponsor_company=sponsor.name,
            sponsor_website=website,
            sponsor_domain=domain,
            company_segment=(
                qualification.company_segment if qualification is not None else None
            ),
            recently_funded=(
                qualification.recently_funded if qualification is not None else None
            ),
            recent_funding_signal=(
                qualification.recent_funding_signal
                if qualification is not None
                else None
            ),
            company_location=(
                qualification.company_location if qualification is not None else None
            ),
            location_priority=(
                qualification.location_priority if qualification is not None else None
            ),
            developer_adoption_need=(
                qualification.developer_adoption_need
                if qualification is not None
                else None
            ),
            market_visibility_need=(
                qualification.market_visibility_need
                if qualification is not None
                else None
            ),
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
            qualification_notes=(
                qualification.qualification_notes if qualification is not None else None
            ),
            qualification_score=(
                qualification.score if qualification is not None else 0
            ),
            qualification_accepted=(
                qualification.accepted if qualification is not None else True
            ),
        )

    def _build_excel(self, leads: list[Lead]) -> tuple[str, bytes]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"hackindia_leads_{timestamp}.xlsx"
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame(
                [lead.as_export_row() for lead in leads],
                columns=PUBLIC_LEAD_COLUMNS,
            ).to_excel(writer, index=False, sheet_name="Leads")
        return export_name, buffer.getvalue()

    def _finish_run(
        self,
        leads: list[Lead],
        progress_callback: Callable[[str], None] | None,
        *,
        stopped: bool,
    ) -> PipelineResult:
        ordered_leads = sorted(leads, key=self._lead_sort_key, reverse=True)
        unique_leads = self._dedupe_leads_by_sponsor(ordered_leads)
        export_name, export_bytes = self._build_excel(unique_leads)
        if stopped:
            self._emit(
                progress_callback,
                (
                    f"Run stopped with {len(unique_leads)} validated lead(s). "
                    f"Download ready: {export_name}"
                ),
            )
        else:
            self._emit(
                progress_callback,
                (
                    f"Finished run with {len(unique_leads)} validated lead(s). "
                    f"Download ready: {export_name}"
                ),
            )
        return PipelineResult(
            rows=unique_leads,
            export_name=export_name,
            export_bytes=export_bytes,
        )

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

    def _lead_sort_key(self, lead: Lead) -> tuple[int, int, int]:
        location_rank = {"US": 3, "India": 3, "Global": 2, "Unknown": 1}
        return (
            location_rank.get(lead.location_priority or "Unknown", 0),
            lead.qualification_score,
            lead.email_score,
        )

    def _dedupe_leads_by_sponsor(self, leads: list[Lead]) -> list[Lead]:
        deduped: dict[str, Lead] = {}
        for lead in leads:
            sponsor_key = lead.sponsor_company.strip().lower()
            deduped.setdefault(sponsor_key, lead)
        return list(deduped.values())
