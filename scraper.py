import httpx
import logging
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_preis(text):
    if not text:
        return None
    cleaned = re.sub(r'[^\d]', '', text.replace('.', '').split(',')[0])
    try:
        return int(cleaned) if cleaned else None
    except:
        return None


def parse_zimmer(text):
    if not text:
        return None
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))
    return None


async def scrape_degewo():
    listings = []
    stadt = "Berlin"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                "https://www.degewo.de/immosuche",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("article.article-list__item")
            logger.info(f"degewo: found {len(items)} raw items")

            for item in items:
                try:
                    title_el = item.select_one("h2.article__title")
                    meta_el = item.select_one("span.article__meta")
                    preis_el = item.select_one("div.article__price-tag")
                    link_el = item.select_one("a[href]")

                    all_spans = item.select("span.text")
                    span_texts = [s.get_text(strip=True) for s in all_spans]

                    zimmer_text = None
                    groesse_text = None
                    for text in span_texts:
                        if "Zimmer" in text:
                            zimmer_text = text
                        elif "m" in text and any(c.isdigit() for c in text):
                            groesse_text = text

                    # Bezirk aus "Straße | Bezirk"
                    bezirk = stadt
                    if meta_el:
                        meta_text = meta_el.get_text(strip=True)
                        if "|" in meta_text:
                            bezirk = meta_text.split("|")[-1].strip() + f", {stadt}"

                    url = link_el["href"] if link_el else "https://www.degewo.de/immosuche"
                    if url and not url.startswith("http"):
                        url = "https://www.degewo.de" + url

                    listing = {
                        "titel": title_el.get_text(strip=True) if title_el else "Degewo Wohnung",
                        "preis": parse_preis(preis_el.get_text() if preis_el else None),
                        "zimmer": parse_zimmer(zimmer_text),
                        "groesse": groesse_text or "?",
                        "bezirk": bezirk,
                        "url": url,
                        "anbieter": "degewo",
                        "source": "degewo"
                    }
                    listings.append(listing)
                    logger.info(f"degewo parsed: {listing['titel']} | {listing['zimmer']} Zimmer | {listing['groesse']} | {listing['preis']}€ | {listing['bezirk']}")
                except Exception as e:
                    logger.warning(f"Error parsing degewo item: {e}")
    except Exception as e:
        logger.error(f"Error scraping degewo: {e}")
    return listings


async def scrape_wbm():
    listings = []
    stadt = "Berlin"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                "https://www.wbm.de/wohnungen-berlin/angebote/",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("div.row.openimmo-search-list-item")
            logger.info(f"wbm: found {len(items)} raw items")

            for item in items:
                try:
                    # Titel + Details aus article.immo-element
                    immo = item.select_one("article.immo-element:not(.teaserBox)")
                    if not immo:
                        continue

                    title_el = immo.select_one("h2.imageTitle")
                    address_el = immo.select_one("div.address")
                    preis_el = immo.select_one("div.main-property-value.main-property-rent")
                    groesse_el = immo.select_one("div.main-property-value.main-property-size")
                    zimmer_el = immo.select_one("div.main-property-value.main-property-rooms")

                    # Link aus tooltip div
                    data_uid = item.get("data-uid")
                    link_el = item.select_one(f"div#immobilie-list-item-tooltip-{data_uid} a[href]")
                    if not link_el:
                        link_el = item.select_one("a[href]")

                    # Bezirk aus div.area
                    bezirk_el = item.select_one("div.area")
                    bezirk = (bezirk_el.get_text(strip=True) + f", {stadt}") if bezirk_el else stadt

                    url = link_el["href"] if link_el else "https://www.wbm.de/wohnungen-berlin/angebote/"
                    if url and not url.startswith("http"):
                        url = "https://www.wbm.de" + url

                    listing = {
                        "titel": title_el.get_text(strip=True) if title_el else "WBM Wohnung",
                        "preis": parse_preis(preis_el.get_text() if preis_el else None),
                        "zimmer": parse_zimmer(zimmer_el.get_text() if zimmer_el else None),
                        "groesse": groesse_el.get_text(strip=True) if groesse_el else "?",
                        "bezirk": bezirk,
                        "url": url,
                        "anbieter": "WBM",
                        "source": "wbm"
                    }
                    listings.append(listing)
                    logger.info(f"wbm parsed: {listing['titel']} | {listing['zimmer']} Zimmer | {listing['groesse']} | {listing['preis']}€ | {listing['bezirk']}")
                except Exception as e:
                    logger.warning(f"Error parsing wbm item: {e}")
    except Exception as e:
        logger.error(f"Error scraping wbm: {e}")
    return listings


async def run_scraper(supabase_url, supabase_key):
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    all_listings = []
    all_listings += await scrape_degewo()
    all_listings += await scrape_wbm()
    logger.info(f"Found {len(all_listings)} total listings")

    new_listings = []
    async with httpx.AsyncClient(timeout=10) as client:
        for listing in all_listings:
            url = listing.get("url")
            if not url:
                continue
            try:
                r = await client.get(
                    f"{supabase_url}/rest/v1/seen_listings",
                    headers=headers,
                    params={"url": f"eq.{url}"}
                )
                if r.status_code == 200 and len(r.json()) == 0:
                    await client.post(
                        f"{supabase_url}/rest/v1/seen_listings",
                        headers=headers,
                        json={"url": url, "titel": listing.get("titel", "")}
                    )
                    new_listings.append(listing)
            except Exception as e:
                logger.error(f"DB error: {e}")

    logger.info(f"Found {len(new_listings)} NEW listings")
    return new_listings
