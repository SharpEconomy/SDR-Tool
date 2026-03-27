# HackIndia Lead Finder

Minimal Python app to find active hackathon sponsor companies, enrich likely
decision-maker emails from public data, precheck them, validate sponsor
websites, and prepare the final output as a downloadable Excel file.

## What it does

- Scrapes or discovers hackathon event pages from `ETHGlobal`, `Devpost`, `DoraHacks`, and `MLH`.
- Extracts sponsor or partner companies from those pages.
- Resolves and validates the sponsor's primary website and domain.
- Uses public search results and sponsor websites to infer likely
  decision-makers.
- Uses a non-LLM qualification pass to score sponsors for Tech/AI/Web3 fit,
  recent funding signals, US/India priority, developer adoption need, and
  market visibility.
- Prechecks each email with syntax, MX, and SMTP validation before it is
  written to the Excel export.
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
QUALIFICATION_ENABLED=true
GOOGLE_SEARCH_API_KEY=your_google_search_api_key
GOOGLE_SEARCH_ENGINE_ID=your_programmable_search_engine_id
```

Set `QUALIFICATION_ENABLED=false` for bulk test runs when you want to skip
company-fit qualification entirely. If Google Custom Search credentials are not
set, the app falls back to DuckDuckGo Search.

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
- `streamlit==1.47.0` is pinned because older 1.44.x builds can hit the
  upstream `SessionInfo` websocket race on hosted deployments like Render.
- `USE_BROWSER_FALLBACK=false` is set in `render.yaml` by default to avoid Playwright/Chromium deployment issues.
- Excel files are kept in memory and exposed through the in-app download button only.
- If you later want browser fallback on Render, you will need an additional Playwright/Chromium setup step and a compatible Render instance image.

## Output

Excel files are generated in memory and downloaded from the UI.

Expected columns:

- `source`
- `event_name`
- `event_url`
- `sponsor_company`
- `sponsor_website`
- `sponsor_domain`
- `company_segment`
- `recently_funded`
- `recent_funding_signal`
- `company_location`
- `location_priority`
- `developer_adoption_need`
- `market_visibility_need`
- `decision_maker_name`
- `decision_maker_title`
- `decision_maker_email`
- `linkedin_url`
- `evidence`
- `qualification_notes`

## Extending to more websites later

Add a new source adapter inside `hackindia_leads/sources/` and register it in `hackindia_leads/sources/registry.py`.

The simplest path is:

1. Subclass `SearchBackedSource` for search-driven discovery.
2. Override `discover_event_urls()` if the site has a stable listing page.
3. Override `extract_sponsors()` if the site uses a source-specific JSON blob or special markup.
