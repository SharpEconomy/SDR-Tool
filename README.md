# HackIndia Lead Finder

Minimal Python app to find active hackathon sponsor companies, enrich likely
decision-maker emails from public data, precheck them, validate sponsor
websites, and save the final output into CSV.

## What it does

- Scrapes or discovers hackathon event pages from `ETHGlobal`, `Devpost`, `DoraHacks`, and `MLH`.
- Extracts sponsor or partner companies from those pages.
- Resolves and validates the sponsor's primary website and domain.
- Uses public search results and sponsor websites to infer likely
  decision-makers.
- Prechecks each email with syntax, MX, and SMTP validation before it is
  written to CSV.
- Exports only accepted leads when `SMTP_PRECHECK_REQUIRED=true`.

## Important limits

- Some target sites use JavaScript or anti-bot protection. The app includes optional Playwright browser fallback for that reason.
- Email precheck is best-effort. SMTP probing improves quality, but no scraper can honestly guarantee 100% future inbox deliverability.
- The app does not scrape private LinkedIn content. It can attach public LinkedIn profile URLs from search results when available.

## Setup

1. Configure your `.env` file directly:

```bash
notepad .env
```

1. Fill in at least:

```dotenv
SMTP_FROM_EMAIL=hello@yourdomain.com
WEBSITE_PRECHECK_REQUIRED=true
SMTP_PRECHECK_REQUIRED=true
```

1. Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

1. Run the UI:

```bash
streamlit run app.py
```

## Deploy to Render

This repo now includes a Render blueprint in `render.yaml`.

Steps:

1. Push this repo to GitHub.
1. In Render, create a new Blueprint service from the repo.
1. Render will pick up:

```text
Build Command: pip install -r requirements.txt
Start Command: streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true
```

1. In the Render dashboard, set:

```dotenv
SMTP_FROM_EMAIL=hello@yourdomain.com
```

Notes:

- Python is pinned to `3.13.2` for Render because `pandas==2.2.3` does not provide
  Python 3.14 wheels, which causes slow or stuck source builds during deploys.
- `USE_BROWSER_FALLBACK=false` is set in `render.yaml` by default to avoid Playwright/Chromium deployment issues.
- CSVs are written to the service filesystem under `output/`, which is ephemeral on Render. Use the in-app download button to retrieve files.
- If you later want browser fallback on Render, you will need an additional Playwright/Chromium setup step and a compatible Render instance image.

## Output

CSV files are written into `output/`.

Expected columns:

- `source`
- `event_name`
- `event_url`
- `sponsor_company`
- `sponsor_website`
- `sponsor_domain`
- `decision_maker_name`
- `decision_maker_title`
- `decision_maker_email`
- `linkedin_url`
- `evidence`

## Extending to more websites later

Add a new source adapter inside `hackindia_leads/sources/` and register it in `hackindia_leads/sources/registry.py`.

The simplest path is:

1. Subclass `SearchBackedSource` for search-driven discovery.
2. Override `discover_event_urls()` if the site has a stable listing page.
3. Override `extract_sponsors()` if the site uses a source-specific JSON blob or special markup.
