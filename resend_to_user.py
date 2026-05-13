"""
One-off script: scrape all providers and send matching listings directly
to a specific user, bypassing the seen_listings check.

Usage:
    TELEGRAM_TOKEN=... SUPABASE_URL=... SUPABASE_KEY=... python resend_to_user.py
"""
import asyncio
import os
import httpx
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TARGET_USER_ID = "1834783828"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

from scraper import (
    scrape_degewo, scrape_wbm, scrape_howoge, scrape_gewobag,
    scrape_stadtundland, scrape_grandcity, SCRAPER_NAMES,
)
from filters import filter_listing
from plz_berlin import PLZ_ORTSTEIL


async def fetch_user():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/user_preferences",
            headers=headers,
            params={"user_id": f"eq.{TARGET_USER_ID}"},
        )
        rows = r.json()
        return rows[0] if rows else None


async def send_listing(listing: dict):
    listing_wbs = listing.get("wbs")
    if listing_wbs:
        wbs_min, wbs_max = listing_wbs
        if wbs_min == wbs_max:
            wbs_line = f"📋 WBS {wbs_min} erforderlich\n"
        elif wbs_min == 100 and wbs_max == 220:
            wbs_line = "📋 WBS erforderlich\n"
        else:
            wbs_line = f"📋 WBS {wbs_min}–{wbs_max} erforderlich\n"
    else:
        wbs_line = "📋 Kein WBS erforderlich\n"

    plz = listing.get("plz", "")
    ortsteil = PLZ_ORTSTEIL.get(plz) if plz else None
    location = f"{ortsteil or listing.get('bezirk', '?')} ({plz})" if plz else listing.get("bezirk", "?")
    url = listing.get("url", "")
    msg = (
        f"🏠 <b>Neue Wohnung gefunden!</b>\n\n"
        f"📍 {location}\n"
        f"🚪 {listing.get('zimmer', '?')} Zimmer\n"
        f"💶 {listing.get('preis', '?')}€ warm\n"
        f"📐 {listing.get('groesse', '?')} m²\n"
        f"{wbs_line}"
        f"🏢 {listing.get('anbieter', '?')}\n\n"
        f"🔗 <a href='{url}'>Zur Wohnung</a>"
    )

    tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    bild = listing.get("bild")
    async with httpx.AsyncClient(timeout=15) as client:
        sent = False
        if bild:
            r = await client.post(f"{tg_url}/sendPhoto", json={
                "chat_id": TARGET_USER_ID, "photo": bild,
                "caption": msg, "parse_mode": "HTML",
            })
            sent = r.status_code == 200
        if not sent:
            r = await client.post(f"{tg_url}/sendMessage", json={
                "chat_id": TARGET_USER_ID, "text": msg,
                "parse_mode": "HTML", "disable_web_page_preview": False,
            })
            if r.status_code != 200:
                logger.error(f"Failed to send: {r.text}")
                return False
    return True


async def main():
    user = await fetch_user()
    if not user:
        logger.error(f"User {TARGET_USER_ID} not found in user_preferences")
        return

    logger.info(f"User settings: {user}")

    results = await asyncio.gather(
        scrape_degewo(), scrape_wbm(), scrape_howoge(), scrape_gewobag(),
        scrape_stadtundland(), scrape_berlinhaus(), scrape_grandcity(),
        return_exceptions=True,
    )

    all_listings = []
    for name, r in zip(SCRAPER_NAMES, results):
        if isinstance(r, list):
            logger.info(f"{name}: {len(r)} listings scraped")
            all_listings += r
        else:
            logger.error(f"{name}: scraper error — {r}")

    logger.info(f"Total: {len(all_listings)} listings across all providers")

    sent = 0
    skipped = 0
    for listing in all_listings:
        passes, reason = filter_listing(listing, user)
        if not passes:
            logger.debug(f"SKIP [{listing.get('anbieter')}] {listing.get('titel', '')[:50]} — {reason}")
            skipped += 1
            continue
        logger.info(f"SEND [{listing.get('anbieter')}] {listing.get('titel', '')[:60]}")
        ok = await send_listing(listing)
        if ok:
            sent += 1
        await asyncio.sleep(0.5)

    logger.info(f"Done — sent {sent}, skipped {skipped} (did not match filter)")


asyncio.run(main())
