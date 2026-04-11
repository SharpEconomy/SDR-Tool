# Growth Opportunity Decision Engine

Production-ready Streamlit application for small and mid-sized businesses that need ranked growth opportunities instead of raw search results. The app accepts a structured business profile and returns prioritized customers, partners, vendors, suppliers, and service providers with transparent reasoning, confidence, and next action.

## What the app does

- Normalizes business intake into a reusable targeting model.
- Discovers public opportunities across user URLs, public web pages, directories, company sites, and procurement-style listings.
- Parses pages deterministically first and uses `gpt-5.4-mini` only where ambiguity remains.
- Enriches each entity with category, location, company size, contact paths, and decision-maker signals.
- Scores every entity using deterministic rules with optional bounded model refinement.
- Produces a ranked opportunity list plus a skipped-entities audit trail.
- Exports a business-ready Excel workbook with two sheets:
  `Prioritized Opportunities` and `Skipped Entities`.
- Writes an audit record for each run so decisions remain explainable and reviewable later.
- Surfaces a human-readable reasoning summary and next action for every ranked result.

## Product intent

This is not a scraper marketplace, listing site, or general-purpose search tool. It is a decision engine:

- Input: business profile and need
- Processing: discovery, filtering, enrichment, scoring, matching
- Output: a short prioritized list with reasoning and next action

## QA-based intake experience

The intake UI is a guided conversation rather than a long form.

- The app asks adaptive questions in plain language and skips fields that are already known.
- `gpt-5.4-mini` is used to extract structured intake updates and generate the next best follow-up question when available.
- The interview layer falls back to deterministic extraction and rule-based next-question logic if the model is unavailable.
- Users can refine business basics, need definition, or filters without restarting the whole brief.
- The right-hand summary panel shows the live business brief that will drive discovery and scoring.

## Core flows

1. Answer a few adaptive questions about the business and what kind of opportunity is needed.
2. Review the generated business brief, constraints, and targeting summary.
3. Run discovery and optionally pause, resume, or stop the pipeline.
4. Review ranked matches with reasoning and next action.
5. Download the Excel workbook with prioritized and skipped entities.

The UI stays non-technical on purpose. It is designed for operators, founders, growth teams, procurement leads, and business owners who want a simple guided flow.

## Architecture

Main package: `growth_engine`

- `config.py`: runtime and deployment settings.
- `models.py`: intake, discovery, enrichment, scoring, matching, audit, and export models.
- `intake/`: business intake normalization, chat-style interview flow, and inferred targeting model creation.
- `discovery/`: adapters for user URLs, public web, directories, company sites, and procurement listings.
- `parsing/`: deterministic HTML parsing.
- `enrichment/`: entity resolution, contact-path discovery, decision-maker hints, and exclusions.
- `validation/`: email syntax, MX, and optional SMTP validation.
- `scoring/`: deterministic scoring plus bounded LLM refinement.
- `matching/`: business-facing output assembly.
- `export/`: Excel workbook generation.
- `storage/`: Firebase Storage export persistence and Firestore audit persistence.
- `orchestration/`: end-to-end decision engine and pause/resume/stop control.
- `ui/`: guided Streamlit interface.

More detail: [docs/architecture.md](/c:/Users/MCN/Dev/SDR-Tool/docs/architecture.md)

## Model usage

The app centralizes all model calls in `growth_engine/services/openai_service.py`.

Model responsibilities:

- targeting model refinement
- conversational intake extraction and adaptive follow-up generation
- ambiguous entity extraction
- bounded scoring refinement, matching guidance, and decision explanation

Reliability rules:

- deterministic parsing, enrichment, and scoring always run first
- every critical flow still works if the model is unavailable
- LLM refinement is bounded so the model cannot fully override deterministic scoring
- prompts are structured and reused from a single service layer
- network-facing services use retry and timeout controls from configuration

## Local setup

1. Create a virtual environment.
2. Install dependencies.
3. Create `.env` from `.env.example`.
4. Run the UI.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

## PowerShell helper script

Use the project helper at `scripts/sdr-tool-script.ps1` for common tasks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Task install
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Task lint
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Task test
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Task build
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Task all
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Task run -NoBrowser -Port 8503
```

Script behavior:

- `all` runs install, format, lint, test, and build without launching a browser.
- `run` starts Streamlit on the selected port and can skip browser launch with `-NoBrowser`.
- `clean` removes local caches such as `__pycache__`, `.pytest_cache`, and compiled `.pyc` files.

Verified tasks:

- `install`
- `lint`
- `test`
- `build`
- `clean`
- `all`
- `run -NoBrowser -Port 8503`

## Environment configuration

Use `.env.example` as the reference configuration.

Important settings:

- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-5.4-mini`
- `OPENAI_ENABLED=true`
- `OPENAI_REASONING_EFFORT=low`
- `REQUEST_RETRY_ATTEMPTS`
- `REQUEST_RETRY_BACKOFF_SECONDS`
- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_ENGINE_ID`
- `SMTP_PROBE_ENABLED=false`
- `AUDIT_BACKEND=firestore`
- `FIRESTORE_COLLECTION`
- `FIRESTORE_DATABASE`
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`
- `FIREBASE_STORAGE_BUCKET`

Optional Firebase sign-in:

- `FIREBASE_API_KEY`
- `FIREBASE_AUTH_DOMAIN`
- `FIREBASE_PROJECT_ID`

Leave the Firebase values blank if you do not want sign-in enabled for local runs.

## Firestore and Google Cloud credentials

The app uses Firestore for audit persistence when `AUDIT_BACKEND=firestore`. There is no Realtime Database dependency in the current backend.

Google Cloud credentials can be supplied in one of these ways:

1. `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`
2. default ambient credentials in the environment

Recommended for encrypted secrets in CI/CD or hosted deployments:

- store the service account JSON as a base64-encoded secret
- set that secret as `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`
- set `GOOGLE_CLOUD_PROJECT` explicitly

The same credential source is used for Firestore, Firebase Storage, and Pub/Sub helpers.

## Google Cloud support

The app runs locally without cloud dependencies. The codebase also supports simple cloud-oriented extension points:

- Cloud Run: `growth_engine/cloud/run_api.py` exposes `/healthz` and `/api/run`.
- Cloud Functions: `growth_engine/cloud/functions.py` exposes request and Pub/Sub job handlers.
- Pub/Sub: `growth_engine/cloud/pubsub.py` publishes intake jobs for async orchestration with a built-in topic name.
- Firestore: store audit records when `AUDIT_BACKEND=firestore`, using the configured Firestore collection and database.
- Firebase Storage: persist exports to the configured `FIREBASE_STORAGE_BUCKET`.

The Google Cloud integrations are lazy-imported so local runs remain lightweight.

## Real-world use cases

Detailed examples: [docs/use-cases.md](/c:/Users/MCN/Dev/SDR-Tool/docs/use-cases.md)

Representative use cases:

- A Mumbai packaged-food brand finds regional distributors and modern trade buyers.
- A Bengaluru SaaS startup identifies implementation partners and channel resellers.
- A Jaipur furniture manufacturer screens reliable suppliers before outreach.
- A Chennai healthcare service business finds hospital procurement opportunities.
- A Pune D2C brand maps service providers for warehousing, logistics, and retail activation.

## Testing

Run the suite:

```bash
python -m pytest
```

Test coverage includes:

- intake normalization
- adaptive interview extraction and follow-up selection
- discovery adapters
- parsing
- enrichment
- matching
- scoring
- export generation
- orchestration
- cloud helpers
- fetch/search/OpenAI retry behavior
- UI helpers
- email validation

Test guide: [tests/README.md](/c:/Users/MCN/Dev/SDR-Tool/tests/README.md)

## Operational notes

- Discovery uses public pages and internal search queries, not private platform scraping.
- Email validation is best-effort and should not be treated as guaranteed deliverability.
- Decision-maker inference is intentionally cautious and favors transparent guessed patterns over false precision.
- Export files are persisted to Firebase Storage when `FIREBASE_STORAGE_BUCKET` is configured.
- Audit records are persisted to Firestore when `AUDIT_BACKEND=firestore`.
