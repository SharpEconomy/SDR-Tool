# Architecture

## Overview

The application is organized as a small decision-engine pipeline that keeps deterministic logic in control and uses `gpt-5.4-mini` only where the public data is unclear.

Pipeline:

1. Intake
2. Discovery
3. Parsing
4. Enrichment
5. Validation
6. Scoring
7. Matching
8. Export
9. Audit persistence

## Intake

`growth_engine/intake/service.py`

Conversational intake: `growth_engine/intake/interview.py`

Responsibilities:

- run the QA-based interview that builds the intake draft over multiple turns
- avoid repeating already-answered fields
- ask focused follow-up questions that adapt to prior answers
- use `gpt-5.4-mini` for structured intake extraction and next-question generation when available
- fall back to deterministic extraction and question planning when the model is unavailable
- normalize user inputs
- derive a domain from the business website
- create reusable targeting keywords, sectors, company-size preferences, and buying signals
- pull in ideal customer profile, opportunity type, and vendor/supplier constraints so they affect downstream relevance and filtering
- optionally refine the targeting model with `gpt-5.4-mini`

## Discovery

`growth_engine/discovery/adapters.py`

Adapters:

- `user_urls`
- `public_web`
- `directories`
- `company_sites`
- `procurement`

Principles:

- adapters are internal sources, not UI-facing search tools
- user-provided URLs are evaluated directly
- search-backed adapters generate a small number of targeted public queries
- adapter output is normalized into `DiscoveryDocument`

## Parsing

`growth_engine/parsing/html.py`

Deterministic parser extracts:

- title
- meta description
- headings
- visible text
- links
- emails
- phone numbers
- coarse category hints
- coarse location hints

If the extracted signal is thin or inconsistent, the document is flagged as ambiguous for downstream LLM fallback.

## Enrichment

`growth_engine/enrichment/service.py`

Responsibilities:

- resolve entity name, website, domain, category, and location
- infer company-size and budget signals
- gather trust, timing, and accessibility signals
- collect direct contact paths
- infer decision-maker candidates cautiously from public search results
- validate direct and inferred emails separately
- apply exclusion rules

Fallback behavior:

- deterministic enrichment runs first
- if parsing is ambiguous, `gpt-5.4-mini` can refine the entity profile
- exclusion logic remains deterministic

## Validation

`growth_engine/validation/email_validation.py`

Checks:

- syntax
- MX
- optional SMTP probe

This layer is isolated so tests can mock failure modes like DNS errors or SMTP rejection.

## Scoring

`growth_engine/scoring/service.py`

Deterministic score dimensions:

- fit
- relevance
- geography
- budget compatibility
- intent
- accessibility
- trust
- timing
- expected value

Rules:

- deterministic scoring always produces the baseline priority
- business constraints and ICP terms influence fit and relevance
- optional model refinement is bounded
- model adjustment is intentionally small to control cost, latency, and reliability risk

## Matching

`growth_engine/matching/service.py`

Transforms enriched entities plus scores into the business-facing `Opportunity` view:

- market side
- priority score
- confidence
- explanation
- reasoning summary
- next action

## Export

`growth_engine/export/service.py`

Generates one Excel workbook with two sheets:

- `Prioritized Opportunities`
- `Skipped Entities`

This keeps the final output clean for business users while preserving reviewability.

## Audit trails

`growth_engine/storage/artifacts.py`

Supported modes:

- local files
- optional Google Cloud Storage for artifacts
- optional Firestore for audit records

Every run produces:

- run id
- timestamp
- discovery modes used
- counts
- artifact location
- progress log

## UI

`growth_engine_web/views.py`

Design goals:

- guided web intake instead of a dashboard
- minimal language
- editable business-brief snapshot before persistence
- explicit request/response state instead of framework-managed reruns
- Firebase-backed optional Google sign-in with Django session continuity
- Firestore persistence without introducing a second database

## Deployment shape

Local:

- Django web app
- filesystem exports
- filesystem audit records

Google Cloud:

- Cloud Run API wrapper in `growth_engine/cloud/run_api.py`
- Firestore for audit records
- Cloud Storage for export files
- Cloud Function handlers in `growth_engine/cloud/functions.py`
- Pub/Sub publisher integration in `growth_engine/cloud/pubsub.py`
