# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TheHungerRents is a Telegram bot that scrapes four Berlin municipal housing company websites (Degewo, WBM, HOWOGE, Gewobag) every 2 minutes and notifies users when new listings matching their criteria appear.

## Environment Variables

Required to run locally:
- `TELEGRAM_TOKEN` — Telegram bot token from @BotFather
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_KEY` — Supabase service role key

## Running Locally

```bash
pip install -r requirements.txt
playwright install chromium
TELEGRAM_TOKEN=... SUPABASE_URL=... SUPABASE_KEY=... python main.py
```

## Deployment

Deployed on Railway using the Dockerfile builder (`railway.json` + `nixpacks.toml`). Docker build:
```bash
docker build -t thehungerrents .
docker run -e TELEGRAM_TOKEN=... -e SUPABASE_URL=... -e SUPABASE_KEY=... thehungerrents
```

## Architecture

### File Roles

- **`main.py`** — Telegram bot entry point. Manages the `ConversationHandler` state machine for user onboarding/settings, stores user preferences to Supabase, and schedules `scraper_job` every 120 seconds via `job_queue`.
- **`scraper.py`** — Four async scraper functions (one per provider) that fetch listings, deduplicate against Supabase's `seen_listings` table, filter by user criteria, and return new matches.
- **`plz_berlin.py`** — Static data: maps Berlin postal codes to districts and S-Bahn ring zones; provides validation and filtering utilities used by both `main.py` and `scraper.py`.

### Data Flow

```
User sets preferences → stored in Supabase (user table)
job_queue (every 120s) → scraper.py fetches all 4 providers in parallel
                        → deduplicates against seen_listings
                        → filters by each user's preferences
                        → sends Telegram notifications to matching users
```

### Supabase Schema (REST API, no ORM)

**Users table:**
```python
{ "user_id": str, "search_mode": "ring|plz|bezirk",
  "bezirke": JSON list, "plz": JSON list,
  "budget": int, "zimmer": "1+|2+|3+|egal", "active": bool }
```

**Listing (scraped, in-memory):**
```python
{ "titel": str, "preis": int, "zimmer": int, "groesse": str,
  "bezirk": str, "plz": str, "wbs": bool, "url": str, "anbieter": str }
```

Database helpers in `main.py`: `db_get()`, `db_upsert()`, `db_update()` — all direct Supabase REST via `httpx`.

### Scraper Details

- **Degewo, WBM, Gewobag** — `httpx` + BeautifulSoup; Gewobag paginates up to 5 pages.
- **HOWOGE** — Requires Playwright (headless Chromium) to handle JS-rendered content; dismisses cookie banners and clicks filter buttons before scraping.

### Conversation State Machine

`/start` or `/einstellungen` triggers:
```
SEARCH_MODE → ring → BUDGET → ZIMMER → save & END
           → plz  → PLZ_INPUT → BUDGET → ZIMMER → save & END
           → bezirk → BEZIRK (toggle districts) → BUDGET → ZIMMER → save & END
```
Budget can be a preset inline button or `BUDGET_CUSTOM` (user types amount). UI uses inline keyboards with callback data like `mode:ring`, `bezirk:Mitte`, `budget:1000`, `zimmer:2+`.

### Search Modes

1. **S-Bahn Ring** — 62 hardcoded postal codes inside the ring (`plz_berlin.py`)
2. **Custom PLZ** — Comma/space-separated 5-digit codes provided by user
3. **Districts (Bezirke)** — 12 Berlin districts; `plz_berlin.py` maps each to its PLZs
