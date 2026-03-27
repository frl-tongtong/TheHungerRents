# TheHungerRents

A Telegram bot that monitors Berlin housing company websites for new rental listings and notifies you the moment something matching your criteria appears.

## What it does

Every 2 minutes, the bot scrapes four major Berlin municipal housing providers:
- **Degewo**
- **WBM**
- **HOWOGE**
- **Gewobag**

New listings are matched against each user's saved preferences and sent as Telegram messages instantly.

## Search options

When you start the bot, it walks you through:

1. **Area** — choose one of:
   - Inside the S-Bahn ring
   - Specific postal codes (PLZ)
   - Berlin districts (Bezirke)
2. **Budget** — maximum Warmmiete (all-in rent)
3. **Rooms** — minimum number of rooms

Use `/einstellungen` to update your preferences at any time, and `/pause` to toggle notifications on/off.

## Stack

- **python-telegram-bot** — conversation handling and message delivery
- **httpx + BeautifulSoup** — scraping for most providers
- **Playwright** — headless browser scraping for HOWOGE (JS-rendered)
- **Supabase** — stores user preferences and deduplicates seen listings
- **Railway** — deployment target (Docker + nixpacks)

## Environment variables

| Variable | Description |
|---|---|
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |

## Running locally

```bash
pip install -r requirements.txt
playwright install chromium
TELEGRAM_TOKEN=... SUPABASE_URL=... SUPABASE_KEY=... python main.py
```
