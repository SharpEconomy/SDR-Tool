# Growth Opportunity Decision Engine

Production-ready Streamlit application for capturing a verified business foundation from minimal input. The app starts with only a business name and website, researches public evidence, asks `gpt-5.4-mini` to cross-check the findings, and lets the user confirm or edit the full profile before saving it to Firestore.

## What the app does

- Accepts only a business name and website as manual input.
- Fetches the company website and supporting public search results.
- Parses public evidence deterministically and sends the evidence set to `gpt-5.4-mini` for a final cross-verified profile call.
- Builds a complete editable business profile draft with market, ICP, offerings, goals, and guardrails.
- Presents the gathered evidence and model summary in a review-first confirmation UI.
- Saves the confirmed profile to Firestore after user approval.

## Product intent

This is not a scraper marketplace, listing site, or general-purpose search tool. It is a decision engine:

- Input: business profile and need
- Processing: discovery, filtering, enrichment, scoring, matching
- Output: a short prioritized list with reasoning and next action

## Verification-first intake experience

The current UI is optimized for speed and review quality rather than long-form manual intake.

- The user enters only the business name and website.
- The app performs web research automatically using the primary site plus custom search results.
- `gpt-5.4-mini` makes the final structured call from that evidence set.
- Every generated field remains editable before confirmation.
- The confirmed record is written to Firestore for downstream use.

## Core flows

1. Enter the business name and website.
2. Let the app fetch website and search evidence.
3. Review the GPT-cross-verified business profile.
4. Edit any field that needs correction.
5. Confirm and save the final record to Firestore.

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
- `profile_research/`: public-web evidence gathering and model-backed profile verification.
- `storage/`: Firebase Storage export persistence plus Firestore audit and profile persistence.
- `orchestration/`: end-to-end decision engine and pause/resume/stop control.
- `ui/`: guided Streamlit interface.

More detail: [docs/architecture.md](/c:/Users/MCN/Dev/SDR-Tool/docs/architecture.md)

## Model usage

The app centralizes all model calls in `growth_engine/services/openai_service.py`.

Model responsibilities:

- targeting model refinement
- evidence-backed business profile verification
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
- `FIRESTORE_PROFILE_COLLECTION`
- `FIRESTORE_DATABASE`
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`
- `FIREBASE_STORAGE_BUCKET`

Optional Firebase sign-in:

- `FIREBASE_API_KEY`
- `FIREBASE_AUTH_DOMAIN`
- `FIREBASE_PROJECT_ID`

Firebase sign-in behavior:

- Google sign-in is persisted in the browser with Firebase local auth persistence.
- Reloading the page or reopening the app in the same browser restores the session automatically.
- `Log out` now signs out both the Streamlit session and the persisted Firebase browser session.

Leave the Firebase values blank if you do not want sign-in enabled for local runs.

## Firestore and Google Cloud credentials

The app uses Firestore for confirmed business profile persistence and optional audit persistence. There is no Realtime Database dependency in the current backend.

Google Cloud credentials are supplied through:

1. `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`

Recommended for encrypted secrets in CI/CD or hosted deployments:

- store the service account JSON as a base64-encoded secret
- set that secret as `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`
- set `GOOGLE_CLOUD_PROJECT` explicitly
- place the value in `.env` or `.env.example`

The same credential source is used for Firestore, Firebase Storage, and Pub/Sub helpers.

## Google Cloud support

The app runs locally without cloud dependencies. The codebase also supports simple cloud-oriented extension points:

- Cloud Run: `growth_engine/cloud/run_api.py` exposes `/healthz` and `/api/run`.
- Cloud Functions: `growth_engine/cloud/functions.py` exposes request and Pub/Sub job handlers.
- Pub/Sub: `growth_engine/cloud/pubsub.py` publishes intake jobs for async orchestration with a built-in topic name.
- Firestore: store confirmed business profiles in `FIRESTORE_PROFILE_COLLECTION` and audit records in `FIRESTORE_COLLECTION`.
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

- profile research and model-backed verification fallback behavior
- intake normalization and legacy interview helpers
- discovery adapters
- parsing
- enrichment
- matching
- scoring
- export generation
- orchestration
- cloud helpers
- fetch/search/OpenAI retry behavior
- UI helpers, confirmation-form parsing, and auth session restoration
- Firestore profile persistence
- email validation

Test guide: [tests/README.md](/c:/Users/MCN/Dev/SDR-Tool/tests/README.md)

## Operational notes

- Discovery uses public pages and internal search queries, not private platform scraping.
- Email validation is best-effort and should not be treated as guaranteed deliverability.
- Decision-maker inference is intentionally cautious and favors transparent guessed patterns over false precision.
- Export files are persisted to Firebase Storage when `FIREBASE_STORAGE_BUCKET` is configured.
- Audit records are persisted to Firestore when `AUDIT_BACKEND=firestore`.
