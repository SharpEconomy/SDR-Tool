from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime

from growth_engine.config import Settings
from growth_engine.discovery import build_discovery_adapters
from growth_engine.enrichment import OpportunityEnricher
from growth_engine.export import ExportService
from growth_engine.intake import BusinessProfileBuilder
from growth_engine.matching import MatchingEngine
from growth_engine.models import (
    AuditRecord,
    BusinessIntake,
    DecisionRunResult,
    DiscoveryDocument,
    EnrichedEntity,
    Opportunity,
    SkippedEntity,
)
from growth_engine.observability.logging import get_logger, log_event
from growth_engine.parsing import HtmlParsingService
from growth_engine.scoring import ScoringEngine
from growth_engine.services import OpenAIService, PageFetcher, SearchClient
from growth_engine.storage import (
    FirestoreAuditStore,
    NoOpAuditStore,
)
from growth_engine.utils import slugify
from growth_engine.validation import EmailValidatorService


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

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self) -> bool:
        while not self._resume_event.wait(timeout=0.1):
            if self._stop_event.is_set():
                return False
        return not self._stop_event.is_set()


@dataclass
class DecisionEngine:
    settings: Settings

    def __post_init__(self) -> None:
        self.logger = get_logger()
        self.fetcher = PageFetcher(self.settings)
        self.search_client = SearchClient(self.settings)
        self.openai_service = OpenAIService(self.settings)
        self.email_validator = EmailValidatorService(self.settings)
        self.profile_builder = BusinessProfileBuilder(self.openai_service)
        self.discovery_adapters = build_discovery_adapters(
            self.settings, self.fetcher, self.search_client
        )
        self.parser = HtmlParsingService()
        self.enricher = OpportunityEnricher(
            self.search_client, self.email_validator, self.openai_service
        )
        self.scoring_engine = ScoringEngine(self.openai_service)
        self.matching_engine = MatchingEngine()
        self.export_service = ExportService()
        self.audit_store = self._build_audit_store()

    def run(
        self,
        intake: BusinessIntake,
        *,
        progress_callback: Callable[[str], None] | None = None,
        control: PipelineControl | None = None,
    ) -> DecisionRunResult:
        log: list[str] = []
        run_id = f"{slugify(intake.business_name)}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        profile = self.profile_builder.build(intake)
        self._emit(progress_callback, log, "Profile normalized")
        discovered_documents = self._discover(profile, progress_callback, log, control)
        enriched_entities, skipped_entities = self._enrich_documents(
            profile, discovered_documents, progress_callback, log, control
        )
        opportunities = self._score_and_match(
            profile, enriched_entities, progress_callback, log, control
        )
        export_name, export_bytes = self.export_service.build_workbook(
            opportunities, skipped_entities
        )
        export_uri = None
        audit_record = AuditRecord(
            run_id=run_id,
            created_at=datetime.now(UTC),
            business_name=profile.business_name,
            discovery_modes=profile.discovery_modes,
            opportunity_count=len(opportunities),
            skipped_count=len(skipped_entities),
            export_name=export_name,
            export_uri=export_uri,
            log=log,
        )
        self.audit_store.save(audit_record)
        self._emit(
            progress_callback,
            log,
            f"Run complete with {len(opportunities)} prioritized opportunities",
        )
        return DecisionRunResult(
            profile=profile,
            opportunities=opportunities,
            skipped_entities=skipped_entities,
            export_name=export_name,
            export_bytes=export_bytes,
            export_uri=export_uri,
            audit_record=audit_record,
        )

    def _discover(
        self,
        profile,
        progress_callback,
        log,
        control,
    ) -> list[DiscoveryDocument]:
        documents: list[DiscoveryDocument] = []
        tasks: list[tuple[str, object]] = []
        for mode in profile.discovery_modes:
            for adapter in self.discovery_adapters:
                if adapter.name == "procurement" and mode not in {
                    "vendors",
                    "suppliers",
                    "service_providers",
                }:
                    continue
                if adapter.name == "user_urls" and not profile.user_urls:
                    continue
                tasks.append((mode, adapter))

        if not tasks:
            return documents

        emit_lock = threading.Lock()

        def _progress(message: str) -> None:
            with emit_lock:
                self._emit(progress_callback, log, message)

        def _run_discovery(task: tuple[str, object]) -> list[DiscoveryDocument]:
            mode, adapter = task
            _progress(f"{adapter.name}: discovering {mode}")
            return adapter.discover(profile, mode, progress_callback=_progress)

        with ThreadPoolExecutor(
            max_workers=min(self.settings.max_fetch_workers, len(tasks))
        ) as executor:
            futures = [executor.submit(_run_discovery, task) for task in tasks]
            for future in as_completed(futures):
                if not self._checkpoint(control):
                    break
                documents.extend(future.result())

        deduped: dict[tuple[str, str], DiscoveryDocument] = {}
        for document in documents:
            deduped[(document.discovery_mode, document.url)] = document
        return sorted(
            deduped.values(),
            key=lambda item: (item.discovery_mode, item.url),
        )

    def _enrich_documents(
        self,
        profile,
        documents: list[DiscoveryDocument],
        progress_callback,
        log,
        control,
    ) -> tuple[list[EnrichedEntity], list[SkippedEntity]]:
        enriched: list[EnrichedEntity] = []
        skipped: list[SkippedEntity] = []
        with ThreadPoolExecutor(
            max_workers=min(self.settings.max_fetch_workers, len(documents) or 1)
        ) as executor:
            futures = {
                executor.submit(self._parse_and_enrich, profile, document): document
                for document in documents
            }
            for future, document in futures.items():
                if not self._checkpoint(control):
                    break
                entity = future.result()
                if entity.excluded:
                    skipped.append(
                        SkippedEntity(
                            discovery_mode=entity.discovery_mode,
                            entity_name=entity.entity_name,
                            entity_website=entity.entity_website,
                            source_type=entity.source_type,
                            source_url=entity.source_url,
                            reason=entity.exclusion_reason or "Excluded",
                        )
                    )
                    self._emit(
                        progress_callback,
                        log,
                        f"skipped: {entity.entity_name} ({entity.exclusion_reason})",
                    )
                    continue
                if not entity.entity_name or len(entity.description) < 30:
                    skipped.append(
                        SkippedEntity(
                            discovery_mode=document.discovery_mode,
                            entity_name=document.title or document.url,
                            entity_website=document.url,
                            source_type=document.source_type,
                            source_url=document.url,
                            reason="Insufficient public context",
                        )
                    )
                    continue
                enriched.append(entity)
                self._emit(progress_callback, log, f"enriched: {entity.entity_name}")
        return enriched, skipped

    def _parse_and_enrich(self, profile, document: DiscoveryDocument) -> EnrichedEntity:
        parsed = self.parser.parse(document)
        return self.enricher.enrich(
            profile,
            document.discovery_mode,
            document.source_type,
            document.url,
            parsed,
            document.snippet,
        )

    def _score_and_match(
        self,
        profile,
        enriched_entities: list[EnrichedEntity],
        progress_callback,
        log,
        control,
    ) -> list[Opportunity]:
        if not enriched_entities:
            return []

        with ThreadPoolExecutor(
            max_workers=min(
                self.settings.max_validation_workers, len(enriched_entities)
            )
        ) as executor:
            scores = list(
                executor.map(
                    lambda entity: self.scoring_engine.score(profile, entity),
                    enriched_entities,
                )
            )
        scored = list(zip(enriched_entities, scores))
        scored.sort(key=lambda item: item[1].priority_score, reverse=True)
        refined_scores = self.scoring_engine.refine_top_scores(
            profile, scored[: self.settings.max_llm_refinements]
        )
        final_scored = [
            (
                (
                    entity,
                    refined_scores[index] if index < len(refined_scores) else score,
                )
                if index < self.settings.max_llm_refinements
                else (entity, score)
            )
            for index, (entity, score) in enumerate(scored)
        ]
        opportunities: list[Opportunity] = []
        for index, (entity, score) in enumerate(
            final_scored[: self.settings.max_opportunities], start=1
        ):
            if not self._checkpoint(control):
                break
            opportunity = self.matching_engine.build_opportunity(
                profile, entity, score, rank=index
            )
            opportunities.append(opportunity)
            self._emit(
                progress_callback,
                log,
                f"ranked: {opportunity.entity_name} ({opportunity.priority_score})",
            )
        return opportunities

    def _build_audit_store(self):
        if self.settings.audit_backend == "firestore":
            return FirestoreAuditStore(
                self.settings,
                self.settings.firestore_collection,
            )
        return NoOpAuditStore()

    def _checkpoint(self, control: PipelineControl | None) -> bool:
        if control is None:
            return True
        return control.wait_if_paused()

    def _emit(
        self,
        progress_callback: Callable[[str], None] | None,
        log: list[str],
        message: str,
    ) -> None:
        log.append(message)
        log_event(self.logger, "progress", message=message)
        if progress_callback is not None:
            progress_callback(message)
