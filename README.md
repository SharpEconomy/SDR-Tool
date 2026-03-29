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
- Uses a Claude-backed qualification pass for the final fit decision.
- Keeps Tech/AI/Web3 fit, US/India priority, and part of the developer
  adoption signal as deterministic rule-based hints.
- Restricts final qualification evidence to recent public data, with a 6-month
  window and a 3-month preference.
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
ANTHROPIC_API_KEY=your_anthropic_api_key
ANTHROPIC_MODEL=claude-sonnet-4-20250514
QUALIFICATION_RECENT_MONTHS=6
QUALIFICATION_PREFERRED_RECENT_MONTHS=3
GOOGLE_SEARCH_API_KEY=your_google_search_api_key
GOOGLE_SEARCH_ENGINE_ID=your_programmable_search_engine_id
```

Set `QUALIFICATION_ENABLED=false` for bulk test runs when you want to skip
company-fit qualification entirely. When qualification is enabled, the app
expects an Anthropic API key in `.env`. If Google Custom Search credentials are
not set, the app falls back to DuckDuckGo Search and still applies the same
freshness filter to dated results.

1. Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

1. Run the UI:

```bash
streamlit run app.py
```

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
