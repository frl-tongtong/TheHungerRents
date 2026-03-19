import httpx
import logging
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_preis(text):
    if not text:
        return None
    cleaned = re.sub(r'[^\d,.]', '', text.replace('.', '').replace(',', '.'))
    match = re.search(r'(\d+)', cleaned)
    if match:
        try:
            return int(match.group(1))
        except:
            return None
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
                    # Title
                    title_el = item.select_one("h2.article_title")

                    # Address: "Straße | Bezirk"
                    meta_el = item.select_one("span.article_meta")

                    # Properties: each li has an svg icon + span with class "text"
                    # "1 Zimmer", "45,45 m²", "ab sofort"
                    prop_spans = item.select("ul.article_properties li span.text")
                    zimmer_text = None
                    groesse_text = None
                    for span in prop_spans:
                        t = span.get_text(strip=True)
                        if "Zimmer" in t:
                            zimmer_text = t
                        elif "m²" in t:
                            groesse_text = t

                    # Price: div.article__price-tag – contains "422,61 €"
                    preis_el = item.select_one("div.article__price-tag")

                    # Link
                    link_el = item.select_one("a[href]")

                    # Parse Bezirk from "Straße | Bezirk"
                    bezirk = "Berlin"
                    if meta_el:
                        meta_text = meta_el.get_text(strip=True)
                        if "|" in meta_text:
                            bezirk = meta_text.split("|")[-1].strip()

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


async def run_scraper(supabase_url, supabase_key):
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    all_listings = []
    all_listings += await scrape_degewo()
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
