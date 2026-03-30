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


def extract_img(item, base_url):
    img = item.select_one("img")
    if not img:
        return None
    src = img.get("src") or img.get("data-src", "")
    if not src or src.startswith("data:"):
        return None
    if not src.startswith("http"):
        src = base_url + src
    return src


def parse_wbs(titel, features=None):
    """Check if WBS is required. Returns False or a (min, max) tuple of WBS levels."""
    texts = []
    if titel:
        texts.append(titel)
    if features:
        texts.extend(features)
    for text in texts:
        upper = text.upper()
        if "WBS" not in upper:
            continue
        range_match = re.search(r'WBS\s*(\d+)\s*(?:[-–—]|BIS|TO)\s*(\d+)', upper)
        if range_match:
            return (int(range_match.group(1)), int(range_match.group(2)))
        single_match = re.search(r'WBS\s*(\d+)', upper)
        if single_match:
            level = int(single_match.group(1))
            return (level, level)
        return (100, 220)  # WBS required but level unspecified
    return False


def _ortsteil_to_plz(ortsteil_text):
    """Return a representative PLZ for an ortsteil name (used for Degewo which doesn't expose PLZ).
    If any PLZ for that ortsteil is inside the ring, returns one of those (listing passes ring filter).
    If all are outside the ring, returns one of those (listing gets correctly rejected).
    Returns "" if ortsteil is unknown (listing passes through)."""
    from plz_berlin import PLZ_ORTSTEIL, INNERHALB_RING
    key = ortsteil_text.lower().strip()
    matches = []
    for plz, ortsteil in PLZ_ORTSTEIL.items():
        for part in ortsteil.split("/"):
            if part.strip().lower() == key:
                matches.append(plz)
                break
    if not matches:
        return ""
    ring_plzs = [p for p in matches if p in INNERHALB_RING]
    return ring_plzs[0] if ring_plzs else matches[0]


async def scrape_degewo():
    listings = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                "https://www.degewo.de/immosuche",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("a[href*='/immosuche/details/']")
            logger.info(f"degewo: found {len(items)} raw items")

            for item in items:
                try:
                    address_el = item.select_one("h3")
                    address_text = address_el.get_text(strip=True) if address_el else ""
                    ortsteil = address_text.split("|")[-1].strip() if "|" in address_text else ""
                    bezirk = f"{ortsteil}, Berlin" if ortsteil else "Berlin"
                    plz = _ortsteil_to_plz(ortsteil)

                    titel_el = item.select_one("h4")
                    titel = titel_el.get_text(strip=True) if titel_el else "Degewo Wohnung"

                    preis_el = item.select_one("span.amount")
                    preis = parse_preis(preis_el.get_text() if preis_el else None)

                    zimmer = None
                    groesse = "?"
                    for li in item.select("ul li"):
                        text = li.get_text(strip=True)
                        if "Zimmer" in text:
                            zimmer = parse_zimmer(text)
                        elif "m²" in text:
                            groesse = text.replace("m²", "").strip()

                    url = item["href"]
                    if url and not url.startswith("http"):
                        url = "https://www.degewo.de" + url

                    listing = {
                        "titel": titel,
                        "preis": preis,
                        "zimmer": zimmer,
                        "groesse": groesse,
                        "bezirk": bezirk,
                        "plz": plz,
                        "wbs": parse_wbs(titel),
                        "url": url,
                        "bild": extract_img(item, "https://www.degewo.de"),
                        "anbieter": "degewo",
                    }
                    listings.append(listing)
                    logger.info(f"degewo parsed: {listing['titel']} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ | WBS:{listing['wbs']} | {listing['plz']} {listing['bezirk']}")
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
                    immo = item.select_one("article.immo-element:not(.teaserBox)")
                    if not immo:
                        continue

                    title_el = immo.select_one("h2.imageTitle")
                    preis_el = immo.select_one("div.main-property-value.main-property-rent")
                    groesse_el = immo.select_one("div.main-property-value.main-property-size")
                    zimmer_el = immo.select_one("div.main-property-value.main-property-rooms")
                    features = [li.get_text(strip=True) for li in immo.select("ul.check-property-list li")]

                    link_el = immo.select_one("a.immo-button-cta[href]")
                    bezirk_el = item.select_one("div.area")
                    bezirk_text = bezirk_el.get_text(strip=True) if bezirk_el else ""
                    plz_match = re.search(r'(\d{5})', bezirk_text)
                    plz = plz_match.group(1) if plz_match else ""
                    bezirk = (bezirk_text + f", {stadt}") if bezirk_text else stadt

                    titel = title_el.get_text(strip=True) if title_el else "WBM Wohnung"

                    url = link_el["href"] if link_el else "https://www.wbm.de/wohnungen-berlin/angebote/"
                    if url and not url.startswith("http"):
                        url = "https://www.wbm.de" + url

                    listing = {
                        "titel": titel,
                        "preis": parse_preis(preis_el.get_text() if preis_el else None),
                        "zimmer": parse_zimmer(zimmer_el.get_text() if zimmer_el else None),
                        "groesse": groesse_el.get_text(strip=True) if groesse_el else "?",
                        "bezirk": bezirk,
                        "plz": plz,
                        "wbs": parse_wbs(titel, features),
                        "url": url,
                        "bild": extract_img(immo, "https://www.wbm.de"),
                        "anbieter": "WBM",
                    }
                    listings.append(listing)
                    logger.info(f"wbm parsed: {listing['titel']} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ | WBS:{listing['wbs']} | {listing['bezirk']}")
                except Exception as e:
                    logger.warning(f"Error parsing wbm item: {e}")
    except Exception as e:
        logger.error(f"Error scraping wbm: {e}")
    return listings


async def scrape_howoge():
    listings = []
    stadt = "Berlin"
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(
                "https://www.howoge.de/immobiliensuche/wohnungssuche.html",
                wait_until="networkidle",
                timeout=60000
            )
            # Cookie Banner wegklicken falls vorhanden
            try:
                await page.click("button.cookie-accept, #cookie-accept, .cookie-consent button, [data-cookie-accept], .cc-btn", timeout=5000)
            except:
                pass

            # HOWOGE lädt Listings per JS nach — "Filter anwenden" klicken
            try:
                await page.click("button:has-text('Filter anwenden')", timeout=5000)
            except:
                pass

            # Auf die tatsächlichen HOWOGE-Listing-Elemente warten
            try:
                await page.wait_for_selector("div.flat-single-grid-item", timeout=30000)
            except:
                # Fallback: vielleicht anderer Selektor nach Redesign
                logger.warning("howoge: flat-single-grid-item not found, trying alternatives...")
                try:
                    await page.wait_for_selector("[class*='flat-single'], [class*='immo-element'], article.listing", timeout=15000)
                except:
                    logger.warning("howoge: no listing elements found at all")

            html = await page.content()
            await browser.close()

            soup = BeautifulSoup(html, "html.parser")
            items = soup.select("div.flat-single-grid-item")
            logger.info(f"howoge: found {len(items)} raw items")

            # Debug: wenn keine Items, zeig was auf der Seite ist
            if not items:
                # Versuch alternative Selektoren
                alt_selectors = [
                    "div[class*='flat']",
                    "article[class*='angebot']",
                    "div[class*='listing']",
                    "div[class*='search-result']",
                ]
                for sel in alt_selectors:
                    alt_items = soup.select(sel)
                    if alt_items:
                        logger.info(f"howoge: alternative selector '{sel}' found {len(alt_items)} items")
                        break
                # Log page title to verify we're on the right page
                title_tag = soup.select_one("title")
                logger.info(f"howoge: page title = '{title_tag.get_text() if title_tag else 'unknown'}'")

            for item in items:
                try:
                    notice_el = item.select_one("div.notice")
                    titel = notice_el.get_text(strip=True) if notice_el else "HOWOGE Wohnung"

                    link_el = item.select_one("a.flat-single--link")
                    address_el = item.select_one("div.address")
                    adresse = address_el.get_text(strip=True) if address_el else ""

                    plz_match = re.search(r'(\d{5})', adresse)
                    plz = plz_match.group(1) if plz_match else ""

                    bezirk = stadt
                    if adresse and "," in adresse:
                        parts = adresse.split(",")
                        if len(parts) >= 3:
                            bezirk = parts[-1].strip() + f", {stadt}"
                        elif len(parts) == 2:
                            bezirk = parts[-1].strip() + f", {stadt}"

                    preis = None
                    groesse = "?"
                    zimmer = None

                    attr_blocks = item.select("div.attributes > div")
                    for block in attr_blocks:
                        headline = block.select_one("div.attributes-headline")
                        content = block.select_one("div.attributes-content")
                        if headline and content:
                            h = headline.get_text(strip=True)
                            c = content.get_text(strip=True)
                            if "Warmmiete" in h:
                                preis = parse_preis(c)
                            elif "fläche" in h.lower():
                                groesse = c.replace("m²", "").strip()
                            elif "Zimmer" in h:
                                zimmer = parse_zimmer(c)

                    features = [f.get_text(strip=True) for f in item.select("div.feature")]

                    url = link_el["href"] if link_el else "https://www.howoge.de/immobiliensuche/wohnungssuche.html"
                    if url and not url.startswith("http"):
                        url = "https://www.howoge.de" + url

                    listing = {
                        "titel": titel,
                        "preis": preis,
                        "zimmer": zimmer,
                        "groesse": groesse,
                        "bezirk": bezirk,
                        "plz": plz,
                        "wbs": parse_wbs(titel, features),
                        "url": url,
                        "bild": extract_img(item, "https://www.howoge.de"),
                        "anbieter": "HOWOGE",
                    }
                    listings.append(listing)
                    logger.info(f"howoge parsed: {listing['titel']} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ | WBS:{listing['wbs']} | {listing['plz']} {listing['bezirk']}")
                except Exception as e:
                    logger.warning(f"Error parsing howoge item: {e}")
    except Exception as e:
        logger.error(f"Error scraping howoge: {e}")
    return listings


async def scrape_gewobag():
    listings = []
    stadt = "Berlin"
    base_url = "https://www.gewobag.de/fuer-mietinteressentinnen/suche/wohnung/"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Seite 1 laden (und ggf. weitere Seiten)
            page_num = 1
            max_pages = 5
            while page_num <= max_pages:
                params = {
                    "gesamtmiete_von": "",
                    "gesamtmiete_bis": "",
                    "gesamtflaeche_von": "",
                    "gesamtflaeche_bis": "",
                    "zimmer_von": "",
                    "zimmer_bis": "",
                    "sort-by": "",
                }
                if page_num > 1:
                    params["seite"] = str(page_num)

                response = await client.get(
                    base_url,
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                    }
                )
                logger.info(f"gewobag: page {page_num} status {response.status_code}, {len(response.text)} bytes")

                if response.status_code != 200:
                    logger.warning(f"gewobag: page {page_num} returned {response.status_code}")
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                items = soup.select("article.angebot-big-box.gw-offer")
                if not items:
                    items = soup.select("article.angebot-big-box")
                logger.info(f"gewobag: page {page_num} found {len(items)} items")

                if not items:
                    break

                for item in items:
                    try:
                        title_el = item.select_one("h3.angebot-title")
                        titel = title_el.get_text(strip=True) if title_el else "Gewobag Wohnung"

                        # Bezirk aus angebot-region (zuverlässiger)
                        region_el = item.select_one("tr.angebot-region td")
                        bezirk_name = region_el.get_text(strip=True) if region_el else ""

                        # Adresse für mehr Kontext
                        address_el = item.select_one("tr.angebot-address address")
                        adresse = address_el.get_text(strip=True) if address_el else ""

                        # Bezirk zusammenbauen
                        if bezirk_name:
                            bezirk = f"{bezirk_name}, {stadt}"
                        elif adresse and "/" in adresse:
                            bezirk = adresse.split("/")[-1].strip() + f", {stadt}"
                        else:
                            bezirk = stadt

                        # PLZ aus Adresse extrahieren
                        plz = ""
                        plz_match = re.search(r'(\d{5})', adresse)
                        if plz_match:
                            plz = plz_match.group(1)

                        # Zimmer und Fläche
                        area_el = item.select_one("tr.angebot-area td:not(th)")
                        zimmer = None
                        groesse = "?"
                        if area_el:
                            area_text = area_el.get_text(strip=True)
                            if "|" in area_text:
                                parts = area_text.split("|")
                                zimmer = parse_zimmer(parts[0])
                                groesse = parts[1].replace("m²", "").strip() if len(parts) > 1 else "?"
                            else:
                                groesse = area_text.replace("m²", "").strip()

                        # Gesamtmiete (= Warmmiete)
                        preis_el = item.select_one("tr.angebot-kosten td:not(th)")
                        preis = parse_preis(preis_el.get_text() if preis_el else None)

                        # Features/Eigenschaften
                        features = [li.get_text(strip=True) for li in item.select("tr.angebot-characteristics li")]

                        # Link
                        link_el = item.select_one("div.angebot-footer a.read-more-link")
                        if not link_el:
                            link_el = item.select_one("a[href*='mietangebote']")
                        url = link_el["href"] if link_el else ""
                        if url and not url.startswith("http"):
                            url = "https://www.gewobag.de" + url

                        listing = {
                            "titel": titel,
                            "preis": preis,
                            "zimmer": zimmer,
                            "groesse": groesse,
                            "bezirk": bezirk,
                            "plz": plz,
                            "wbs": parse_wbs(titel, features),
                            "url": url,
                            "bild": extract_img(item, "https://www.gewobag.de"),
                            "anbieter": "Gewobag",
                        }
                        listings.append(listing)
                        logger.info(f"gewobag parsed: {listing['titel'][:60]} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ | WBS:{listing['wbs']} | {listing['bezirk']}")
                    except Exception as e:
                        logger.warning(f"Error parsing gewobag item: {e}")

                # Nächste Seite?
                next_link = soup.select_one("a.next, a[rel='next']")
                if not next_link:
                    # Alternativ: Pagination-Links prüfen
                    page_links = soup.select("nav.pagination a, .pagination a")
                    has_next = any(str(page_num + 1) in (a.get_text(strip=True)) for a in page_links)
                    if not has_next:
                        break
                page_num += 1

    except Exception as e:
        logger.error(f"Error scraping gewobag: {e}")
    return listings


async def scrape_stadtundland():
    listings = []
    try:
        from playwright.async_api import async_playwright
        from urllib.parse import urlparse, parse_qs
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(
                "https://stadtundland.de/wohnungssuche?district=all",
                wait_until="networkidle",
                timeout=60000
            )
            try:
                await page.click("button[id*='accept'], #CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", timeout=5000)
            except:
                pass
            try:
                await page.wait_for_selector("article[aria-labelledby^='headline-immo-']", timeout=30000)
            except:
                logger.warning("stadtundland: no listing articles found")

            html = await page.content()
            await browser.close()

            soup = BeautifulSoup(html, "html.parser")
            items = soup.select("article[aria-labelledby^='headline-immo-']")
            logger.info(f"stadtundland: found {len(items)} raw items")

            for item in items:
                try:
                    headline_el = item.select_one("h3[id^='headline-immo-']")
                    if headline_el:
                        for sr in headline_el.select("span.sr-only"):
                            sr.decompose()
                    headline_text = headline_el.get_text(strip=True) if headline_el else ""

                    zimmer_match = re.search(r'(\d+)\s*Zimmer', headline_text)
                    zimmer = int(zimmer_match.group(1)) if zimmer_match else None
                    groesse_match = re.search(r'([\d,]+)\s*m²', headline_text)
                    groesse = groesse_match.group(1) if groesse_match else "?"

                    titel_parts = headline_text.split(" – ", 1)
                    titel = titel_parts[1].strip() if len(titel_parts) > 1 else headline_text

                    address_el = item.select_one("p[class*='subHeadline']")
                    adresse = address_el.get_text(strip=True) if address_el else ""
                    plz_match = re.search(r'(\d{5})', adresse)
                    plz = plz_match.group(1) if plz_match else ""
                    bezirk = adresse or "Berlin"

                    preis = None
                    for row in item.select("tr"):
                        th = row.select_one("th")
                        td = row.select_one("td")
                        if th and td and "Gesamtmiete" in th.get_text():
                            preis = parse_preis(td.get_text())
                            break

                    link_el = item.select_one("a[href^='/wohnungssuche/']")
                    url = ("https://stadtundland.de" + link_el["href"]) if link_el else ""

                    bild = None
                    img_el = item.select_one("img")
                    if img_el:
                        src = img_el.get("src", "")
                        if "/_next/image" in src:
                            parsed = urlparse("https://stadtundland.de" + src)
                            params = parse_qs(parsed.query)
                            bild = params.get("url", [None])[0]
                        elif src.startswith("http"):
                            bild = src

                    listing = {
                        "titel": titel or "Stadt und Land Wohnung",
                        "preis": preis,
                        "zimmer": zimmer,
                        "groesse": groesse,
                        "bezirk": bezirk,
                        "plz": plz,
                        "wbs": parse_wbs(titel),
                        "url": url,
                        "bild": bild,
                        "anbieter": "Stadt und Land",
                    }
                    listings.append(listing)
                    logger.info(f"stadtundland parsed: {listing['titel'][:60]} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ | WBS:{listing['wbs']}")
                except Exception as e:
                    logger.warning(f"Error parsing stadtundland item: {e}")
    except Exception as e:
        logger.error(f"Error scraping stadtundland: {e}")
    return listings


async def scrape_grandcity():
    listings = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                "https://www.grandcityproperty.de/wohnung-berlin",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("div.each-real-estate-item")
            logger.info(f"grandcity: found {len(items)} raw items")

            for item in items:
                try:
                    nice_url = item.get("data-nice-url", "").strip()
                    plz_match = re.search(r'_(\d{5})_', nice_url)
                    plz = plz_match.group(1) if plz_match else ""

                    url = ("https://www.grandcityproperty.de" + nice_url) if nice_url else ""

                    titel_el = item.select_one("h2.name_property")
                    titel = titel_el.get_text(strip=True) if titel_el else item.get("data-title", "GrandCity Wohnung")

                    address_el = item.select_one("p.address")
                    bezirk = address_el.get_text(strip=True) if address_el else "Berlin"

                    preis = int(item["data-price"]) if item.get("data-price", "").isdigit() else None

                    zimmer = None
                    groesse = "?"
                    for wrapper in item.select("div.additional-wrapper"):
                        title_el = wrapper.select_one("div.title")
                        value_el = wrapper.select_one("div.value")
                        if not title_el or not value_el:
                            continue
                        t = title_el.get_text(strip=True)
                        v = value_el.get_text(strip=True)
                        if "Zimmer" in t:
                            zimmer = parse_zimmer(v)
                        elif "Fläche" in t:
                            groesse = v.replace("m2", "").replace("m²", "").strip()

                    data_img = item.get("data-img", "")
                    bild = ("https://www.grandcityproperty.de" + data_img) if data_img else None

                    listing = {
                        "titel": titel,
                        "preis": preis,
                        "zimmer": zimmer,
                        "groesse": groesse,
                        "bezirk": bezirk,
                        "plz": plz,
                        "wbs": parse_wbs(titel),
                        "url": url,
                        "bild": bild,
                        "anbieter": "GrandCity",
                    }
                    listings.append(listing)
                    logger.info(f"grandcity parsed: {listing['titel'][:60]} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ kalt | {listing['plz']}")
                except Exception as e:
                    logger.warning(f"Error parsing grandcity item: {e}")
    except Exception as e:
        logger.error(f"Error scraping grandcity: {e}")
    return listings


async def scrape_berlinhaus():
    from plz_berlin import ALL_BERLIN_PLZ
    listings = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            page_num = 1
            while page_num <= 10:
                url = "https://www.berlinhaus.com/mietangebote/" if page_num == 1 else f"https://www.berlinhaus.com/mietangebote/{page_num}/"
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
                soup = BeautifulSoup(response.text, "html.parser")
                items = soup.select("div.listing-item")
                logger.info(f"berlinhaus page {page_num}: found {len(items)} raw items")
                if not items:
                    break

                for item in items:
                    try:
                        location_el = item.select_one("p.location")
                        location_text = location_el.get_text(strip=True) if location_el else ""
                        plz_match = re.search(r'(\d{5})', location_text)
                        plz = plz_match.group(1) if plz_match else ""

                        if plz and plz not in ALL_BERLIN_PLZ:
                            continue  # skip non-Berlin listings

                        link_el = item.select_one("a[href]")
                        url = link_el["href"] if link_el else ""

                        title_el = item.select_one("h3 a")
                        titel = title_el.get_text(strip=True) if title_el else "Berlinhaus Wohnung"

                        specs_el = item.select_one("p.specs")
                        specs_text = specs_el.get_text(strip=True) if specs_el else ""
                        groesse_match = re.search(r'([\d,]+)\s*m²', specs_text)
                        groesse = groesse_match.group(1) if groesse_match else "?"
                        zimmer_match = re.search(r'(\d+)\s*Zimmer', specs_text)
                        zimmer = int(zimmer_match.group(1)) if zimmer_match else None

                        price_el = item.select_one("p.price")
                        preis = parse_preis(price_el.get_text() if price_el else None)

                        img_el = item.select_one("img")
                        bild = img_el["src"] if img_el and img_el.get("src") else None

                        listing = {
                            "titel": titel,
                            "preis": preis,
                            "zimmer": zimmer,
                            "groesse": groesse,
                            "bezirk": location_text,
                            "plz": plz,
                            "wbs": parse_wbs(titel),
                            "url": url,
                            "bild": bild,
                            "anbieter": "Berlinhaus",
                        }
                        listings.append(listing)
                        logger.info(f"berlinhaus parsed: {listing['titel'][:60]} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ kalt | {listing['plz']}")
                    except Exception as e:
                        logger.warning(f"Error parsing berlinhaus item: {e}")

                # check for next page
                if not soup.select_one("a.next, a[rel='next']"):
                    break
                page_num += 1

    except Exception as e:
        logger.error(f"Error scraping berlinhaus: {e}")
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
    all_listings += await scrape_howoge()
    all_listings += await scrape_gewobag()
    all_listings += await scrape_stadtundland()
    all_listings += await scrape_berlinhaus()
    all_listings += await scrape_grandcity()
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
