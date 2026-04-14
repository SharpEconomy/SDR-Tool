# Growth Opportunity Decision Engine

Production-ready Django application for capturing a verified business foundation from minimal input. The app starts with only a business name and website, researches public evidence, asks `gpt-5.4-mini` to cross-check the findings, and lets the user confirm or edit the full profile before saving it to Firestore.

## What the app does

- Accepts only a business name and website as manual input.
- Fetches the company website and supporting public search results.
- Parses public evidence deterministically and sends the evidence set to `gpt-5.4-mini` for a final cross-verified profile call.
- Builds a complete editable business profile draft with market, ICP, offerings, goals, and guardrails.
- Presents the gathered evidence and model summary in a review-first confirmation UI.
- Saves the confirmed profile to Firestore after user approval.
- Keeps the user journey unchanged through confirmation, then bifurcates into lead generation and social media content workflows.
- Generates prioritized leads from the confirmed profile and supports Excel download.
- Creates a social strategy plus channel-ready content for LinkedIn, Instagram, Facebook, and Twitter/X, then emails the package for manual posting.
- Persists profiles and downstream workflow records to Firestore, and exposes an admin-only analytics page for profile volume, workflow activity, and mix trends.

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
- After confirmation, the operator can either generate prioritized leads or create a social content package for manual publishing.
- Lead and social workflow outputs are saved in Firestore as part of the workspace ledger.
- Admin allowlisted users can open a Firestore-backed analytics dashboard from the workspace header.

## Core flows

1. Enter the business name and website.
2. Let the app fetch website and search evidence.
3. Review the GPT-cross-verified business profile.
4. Edit any field that needs correction.
5. Confirm and save the final record to Firestore.
6. Branch into lead generation or social media content creation from the same confirmed profile.
7. Download the lead workbook or email the social content package for manual posting.

The UI stays non-technical on purpose. It is designed for operators, founders, growth teams, procurement leads, and business owners who want a simple guided flow.

## Architecture

Main package: `growth_engine`

- `config.py`: runtime and deployment settings.
- `models.py`: intake, discovery, enrichment, scoring, matching, audit, and export models.
- `intake/`: business intake normalization, chat-style interview flow, and inferred targeting model creation.
- `discovery/`: adapters for user URLs, public web, directories, company sites, and procurement listings.
- `parsing/`: deterministic HTML parsing.
- `enrichment/`: entity resolution, contact-path discovery, decision-maker hints, and exclusions.
- `validation/`: email syntax and MX validation.
- `scoring/`: deterministic scoring plus bounded LLM refinement.
- `matching/`: business-facing output assembly.
- `export/`: Excel workbook generation.
- `profile_research/`: public-web evidence gathering and model-backed profile verification.
- `services/social_content.py`: social strategy creation, channel content generation, and Firestore-ready workflow packaging.
- `services/email_service.py`: SendGrid-backed delivery for the generated social package.
- `storage/`: Firestore audit and profile persistence helpers.
- `orchestration/`: end-to-end lead decision engine and pause/resume/stop control.
- `growth_engine_web/`: Django forms, views, templates, Google OAuth session flow, and session-backed workspace state.
- `growth_engine_web/`: Django forms, views, templates, admin analytics dashboard, Google OAuth session flow, and session-backed workspace state.
- `growth_engine_django/`: Django project settings, routing, and WSGI entrypoint.

More detail: [docs/architecture.md](/c:/Users/MCN/Dev/SDR-Tool/docs/architecture.md)

## Model usage

The app centralizes all model calls in `growth_engine/services/openai_service.py`.

Model responsibilities:

- targeting model refinement
- evidence-backed business profile verification
- evidence-backed social strategy creation and channel content generation
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
3. Fill in `.env.example` with your real local values.
4. Run the Django app.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
playwright install chromium
python manage.py runserver
```

## PowerShell helper script

Use the project helper at `scripts/sdr-tool-script.ps1` to launch the app directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -Port 8503
powershell -ExecutionPolicy Bypass -File scripts\sdr-tool-script.ps1 -NoBrowser
```

Script behavior:

- when the script runs, it stops other project-related terminal and server processes for this repo
- it clears `__pycache__` folders and `.pyc` files before starting Django
- it installs dependencies automatically if required runtime/test/lint modules are missing
- it runs `isort` and `black` for the Python project files before lint, tests, and startup
- it runs lint checks before startup
- it runs the test suite before startup
- it runs build/compile verification before startup
- it starts Django in the current terminal so startup errors are visible immediately
- it opens the browser automatically unless `-NoBrowser` is supplied
- the UI opens only after the verification pipeline passes

## Environment configuration

Use `.env.example` as the runtime configuration file.

Important settings:

- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-5.4-mini`
- `OPENAI_ENABLED=true`
- `OPENAI_REASONING_EFFORT=low`
- `REQUEST_RETRY_ATTEMPTS`
- `REQUEST_RETRY_BACKOFF_SECONDS`
- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_ENGINE_ID`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`
- `SENDGRID_FROM_NAME`
- `SENDGRID_TIMEOUT_SECONDS=10`
- `AUDIT_BACKEND=firestore`
- `FIRESTORE_COLLECTION`
- `FIRESTORE_PROFILE_COLLECTION`
- `FIRESTORE_DATABASE`
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`

Optional Google sign-in:

- `GOOGLE_SIGN_IN_ENABLED=true`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI=https://<host>/auth/google/callback/`
- `ADMIN_EMAILS=admin@example.com,ops@example.com`

Google sign-in behavior:

- Sign-in now uses a backend-owned Google OAuth authorization-code flow.
- If `GOOGLE_SIGN_IN_ENABLED=false`, the app skips Google sign-in and the analytics dashboard no longer requires admin-email verification.
- Django stores the authenticated user in the existing session workspace after the callback succeeds.
- Reloading the page keeps the session active until `Log out` clears the auth session and workspace state.
- If `GOOGLE_OAUTH_REDIRECT_URI` is set in `.env`, the app sends that exact callback URI to Google.
- If `GOOGLE_OAUTH_REDIRECT_URI` is blank, the app falls back to `APP_BASE_URL` and then the incoming request host.
- The callback URI must be registered in Google Cloud Console for every host you use.

Google Cloud Console requirements:

- Create an OAuth client for a web application.
- Add each callback URI in the format `https://<host>/auth/google/callback/`.
- For local development, register the exact local callback URI, for example `http://localhost:8000/auth/google/callback/`.

Leave the Google OAuth values blank if you do not want sign-in enabled for local runs.

## Firestore and Google Cloud credentials

The app uses Firestore for confirmed business profile persistence and optional audit persistence. There is no Realtime Database dependency in the current backend.

Google Cloud credentials are supplied through:

1. `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`

Recommended for encrypted secrets in CI/CD or hosted deployments:

- store the service account JSON as a base64-encoded secret
- set that secret as `GOOGLE_CLOUD_SERVICE_ACCOUNT_JSON_B64`
- set `GOOGLE_CLOUD_PROJECT` explicitly
- place the value in `.env.example`

The same credential source is used for Firestore and Pub/Sub helpers.

## Google Cloud support

The app runs locally without any SQL database. Firestore remains the only database in the stack. The codebase also supports simple cloud-oriented extension points:

- Cloud Run: `growth_engine/cloud/run_api.py` exposes `/healthz` and `/api/run`.
- Cloud Functions: `growth_engine/cloud/functions.py` exposes request and Pub/Sub job handlers.
- Pub/Sub: `growth_engine/cloud/pubsub.py` publishes intake jobs for async orchestration with a built-in topic name.
- Firestore: store confirmed business profiles in `FIRESTORE_PROFILE_COLLECTION` and audit records in `FIRESTORE_COLLECTION`.
- Firestore workflow ledger: store lead-generation and social-content workflow records in `FIRESTORE_COLLECTION`.

The Google Cloud integrations are lazy-imported so local runs remain lightweight.

## Real-world use cases

Detailed examples: [docs/use-cases.md](/c:/Users/MCN/Dev/SDR-Tool/docs/use-cases.md)

Representative use cases:

- A Mumbai packaged-food brand finds regional distributors and modern trade buyers.
- A Bengaluru SaaS startup identifies implementation partners and channel resellers.
- A Jaipur furniture manufacturer screens reliable suppliers before outreach.
- A Chennai healthcare service business finds hospital procurement opportunities.
- A Pune D2C brand maps service providers for warehousing, logistics, and retail activation.

## Django runtime

The web experience is now served through Django with file-backed sessions and cookie-backed messages so no SQLite or Postgres database is introduced.

Runtime notes:

- `python manage.py runserver` starts the web app locally.
- Django session state stores the in-progress profile draft, research result, auth session, lead request state, and generated workbook payload.
- Django session state stores the in-progress workspace, while Firestore remains the system of record for confirmed profiles and downstream workflow records.
- Google sign-in is optional and only enforced when the Google OAuth settings are populated.

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
- Django helper parsing, session serialization, Google OAuth verification hooks, bifurcated lead/social workflow views, and workbook download
- Firestore profile persistence
- social content generation and SendGrid delivery behavior
- email validation

Test guide: [tests/README.md](/c:/Users/MCN/Dev/SDR-Tool/tests/README.md)

## Operational notes

- Discovery uses public pages and internal search queries, not private platform scraping.
- Email validation is best-effort and should not be treated as guaranteed deliverability.
- Social content emails require SendGrid settings; if SendGrid is missing or unavailable, the package is still generated in the workspace and the delivery failure is surfaced to the user.
- Decision-maker inference is intentionally cautious and favors transparent guessed patterns over false precision.
- Export files are generated in memory and returned directly to the caller; there is no bucket-backed export persistence path.
- Workflow records for both lead generation and social content are persisted to Firestore in `FIRESTORE_COLLECTION`.

