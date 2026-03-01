import httpx
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SOURCES = [
    {
        "name": "inberlinwohnen",
        "url": "https://inberlinwohnen.de/wohnungsfinder/",
        "anbieter": "Landeseigene (degewo, HOWOGE, Gewobag, GESOBAU, WBM, STADT UND LAND)"
    },
    {
        "name": "degewo",
        "url": "https://degewo.de/angebote/wohnungsangebote.html",
        "anbieter": "degewo"
    },
    {
        "name": "gesobau",
        "url": "https://www.gesobau.de/mieten/wohnungsangebote.html",
        "anbieter": "GESOBAU"
    },
    {
        "name": "gewobag",
        "url": "https://www.gewobag.de/fuer-mieter-und-mietinteressenten/mietangebote/",
        "anbieter": "Gewobag"
    },
    {
        "name": "howoge",
        "url": "https://www.howoge.de/wohnungen-gewerbe/wohnungsangebote.html",
        "anbieter": "HOWOGE"
    },
    {
        "name": "wbm",
        "url": "https://www.wbm.de/wohnungen-berlin/angebote/",
        "anbieter": "WBM"
    },
    {
        "name": "stadtundland",
        "url": "https://www.stadtundland.de/Mietangebote.htm",
        "anbieter": "STADT UND LAND"
    }
]


def parse_preis(text):
    """Extract price as integer from string like '850,00 €'"""
    if not text:
        return None
    import re
    match = re.search(r'(\d+[\.,]?\d*)', text.replace('.', '').replace(',', '.'))
    if match:
        try:
            return int(float(match.group(1)))
        except:
            return None
    return None


def parse_zimmer(text):
    """Extract room count from string like '2 Zimmer' or '2,5'"""
    if not text:
        return None
    import re
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))
    return None


async def scrape_inberlinwohnen():
    listings = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                "https://inberlinwohnen.de/wohnungsfinder/",
                headers={"User-Agent": "Mozilla/5.0 (compatible; WohnungsBot/1.0)"}
            )
            soup = BeautifulSoup(response.text, "html.parser")

            # Each listing is typically in a div/article - adjust selector as needed
            items = soup.select(".wohnungsfinder-treffer, .angebot-item, article.listing")
            for item in items:
                try:
                    title = item.select_one("h2, h3, .title")
                    preis_el = item.select_one(".preis, .miete, [class*='price'], [class*='miete']")
                    zimmer_el = item.select_one(".zimmer, [class*='zimmer'], [class*='room']")
                    groesse_el = item.select_one(".groesse, .flaeche, [class*='flaeche'], [class*='groesse']")
                    bezirk_el = item.select_one(".bezirk, .ort, .lage, [class*='bezirk'], [class*='lage']")
                    link_el = item.select_one("a[href]")

                    listing = {
                        "titel": title.get_text(strip=True) if title else "Wohnung",
                        "preis": parse_preis(preis_el.get_text() if preis_el else None),
                        "zimmer": parse_zimmer(zimmer_el.get_text() if zimmer_el else None),
                        "groesse": groesse_el.get_text(strip=True) if groesse_el else "?",
                        "bezirk": bezirk_el.get_text(strip=True) if bezirk_el else "Berlin",
                        "url": link_el["href"] if link_el else "https://inberlinwohnen.de",
                        "anbieter": "Landeseigene",
                        "source": "inberlinwohnen"
                    }
                    if listing["url"] and not listing["url"].startswith("http"):
                        listing["url"] = "https://inberlinwohnen.de" + listing["url"]
                    listings.append(listing)
                except Exception as e:
                    logger.warning(f"Error parsing inberlinwohnen item: {e}")
    except Exception as e:
        logger.error(f"Error scraping inberlinwohnen: {e}")
    return listings


async def scrape_degewo():
    listings = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                "https://immosuche.degewo.de/de/search?property_type_id=1&type=1&price_switch=true&price_radio=null&price_from=null&price_to=null&qm_radio=null&qm_from=null&qm_to=null&rooms_radio=null&rooms_from=null&rooms_to=null&wbs_required=null&order=rent_total_without_vat_asc",
                headers={"User-Agent": "Mozilla/5.0 (compatible; WohnungsBot/1.0)"}
            )
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("article.immo-teaser, .property-item, .listing-item")
            for item in items:
                try:
                    preis_el = item.select_one("[class*='price'], [class*='miete'], [class*='rent']")
                    zimmer_el = item.select_one("[class*='room'], [class*='zimmer']")
                    groesse_el = item.select_one("[class*='area'], [class*='flaeche'], [class*='groesse']")
                    bezirk_el = item.select_one("[class*='district'], [class*='bezirk'], [class*='location'], [class*='address']")
                    link_el = item.select_one("a[href]")

                    listing = {
                        "titel": "Degewo Wohnung",
                        "preis": parse_preis(preis_el.get_text() if preis_el else None),
                        "zimmer": parse_zimmer(zimmer_el.get_text() if zimmer_el else None),
                        "groesse": groesse_el.get_text(strip=True) if groesse_el else "?",
                        "bezirk": bezirk_el.get_text(strip=True) if bezirk_el else "Berlin",
                        "url": link_el["href"] if link_el else "https://degewo.de",
                        "anbieter": "degewo",
                        "source": "degewo"
                    }
                    if listing["url"] and not listing["url"].startswith("http"):
                        listing["url"] = "https://immosuche.degewo.de" + listing["url"]
                    listings.append(listing)
                except Exception as e:
                    logger.warning(f"Error parsing degewo item: {e}")
    except Exception as e:
        logger.error(f"Error scraping degewo: {e}")
    return listings


async def run_scraper(supabase):
    """Main scraper function - runs all scrapers and returns only NEW listings."""
    all_listings = []

    # Run all scrapers
    all_listings += await scrape_inberlinwohnen()
    all_listings += await scrape_degewo()
    # More scrapers can be added here later

    logger.info(f"Found {len(all_listings)} total listings")

    # Check which ones are new (not in database)
    new_listings = []
    for listing in all_listings:
        url = listing.get("url")
        if not url:
            continue
        try:
            result = supabase.table("seen_listings").select("url").eq("url", url).execute()
            if not result.data:
                # New listing! Save it and add to notifications list
                supabase.table("seen_listings").insert({"url": url, "titel": listing.get("titel", "")}).execute()
                new_listings.append(listing)
        except Exception as e:
            logger.error(f"DB error: {e}")

    logger.info(f"Found {len(new_listings)} NEW listings")
    return new_listings
