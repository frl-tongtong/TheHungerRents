import asyncio
import httpx
import logging
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Shared Playwright browser — launched once, reused across all scraper runs.
# Avoids the overhead and instability of spawning a new Chromium process every
# 2 minutes on Railway's memory-constrained containers.
_playwright_semaphore = asyncio.Semaphore(1)  # serialise page creation
_playwright_instance = None
_playwright_browser = None


async def _get_browser():
    """Return the shared Chromium browser, (re)launching if needed."""
    global _playwright_instance, _playwright_browser
    from playwright.async_api import async_playwright
    if _playwright_browser is None or not _playwright_browser.is_connected():
        if _playwright_instance is not None:
            try:
                await _playwright_instance.stop()
            except Exception:
                pass
        _playwright_instance = await async_playwright().start()
        _playwright_browser = await _playwright_instance.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info("Playwright browser (re)launched")
    return _playwright_browser


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


_ORTSTEIL_ALIAS = {
    "allendeviertel": "12685",  # Marzahn
    "dammvorstadt": "13597",    # Spandau Altstadt
    "marzahn nord": "12679",
    "marzahn süd": "12689",
}


def _ortsteil_to_plz(ortsteil_text):
    """Return a representative PLZ for an ortsteil name (used for Degewo which doesn't expose PLZ).
    If any PLZ for that ortsteil is inside the ring, returns one of those (listing passes ring filter).
    If all are outside the ring, returns one of those (listing gets correctly rejected).
    Returns "" if ortsteil is unknown (listing passes through)."""
    from plz_berlin import PLZ_ORTSTEIL, INNERHALB_RING
    key = ortsteil_text.lower().strip()

    if key in _ORTSTEIL_ALIAS:
        return _ORTSTEIL_ALIAS[key]

    matches = []
    for plz, ortsteil in PLZ_ORTSTEIL.items():
        for part in ortsteil.split("/"):
            if part.strip().lower() == key:
                matches.append(plz)
                break

    # Fallback: match on any individual word (handles "Marzahn Mitte" → "Marzahn")
    if not matches:
        for word in key.split():
            if len(word) < 4:
                continue
            for plz, ortsteil in PLZ_ORTSTEIL.items():
                for part in ortsteil.split("/"):
                    if part.strip().lower() == word:
                        matches.append(plz)
                        break

    if not matches:
        return ""
    ring_plzs = [p for p in matches if p in INNERHALB_RING]
    return ring_plzs[0] if ring_plzs else matches[0]


def _degewo_parse_page(soup):
    """Parse one page of Degewo search results; returns (listings_on_page, next_page_urls)."""
    items = soup.select("div.c-teaser.c-teaser--apartment")
    next_urls = []
    for a in soup.select("a[href*='tx_openimmo_immobilie%5Bpage%5D'], a[href*='[page]']"):
        href = a.get("href", "")
        if href and href not in next_urls:
            next_urls.append("https://www.degewo.de" + href if href.startswith("/") else href)
    return items, next_urls


async def scrape_degewo():
    listings = []
    try:
        async with _playwright_semaphore:
            browser = await _get_browser()
            page = await browser.new_page()
            try:
                resp = await page.goto(
                    "https://www.degewo.de/immosuche",
                    wait_until="domcontentloaded",
                    timeout=15000
                )
                http_status = resp.status if resp else "unknown"
                page_title = await page.title()
                logger.info(f"degewo: HTTP {http_status}, title='{page_title}', url={page.url}")

                # Dismiss Cookiebot banner if present
                try:
                    await page.click(
                        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll, "
                        "button[id*='CookiebotDialog'][id*='Allow'], "
                        ".c-button--cookie-accept",
                        timeout=5000
                    )
                except Exception:
                    pass

                try:
                    await page.wait_for_selector("div.c-teaser.c-teaser--apartment", timeout=20000)
                except Exception:
                    logger.warning(f"degewo: c-teaser--apartment not found on page 1 (title='{page_title}')")

                html = await page.content()
            finally:
                await page.close()

        soup = BeautifulSoup(html, "html.parser")
        items, next_urls = _degewo_parse_page(soup)
        logger.info(f"degewo page 1: {len(items)} items, {len(next_urls)} more pages")

        all_items = list(items)

        # Fetch remaining pages with httpx (server-rendered, no JS needed after first load)
        if next_urls:
            ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": ua}) as client:
                def norm(u):
                    return u.split("#")[0]

                # Page 1 already done; deduplicate queue using dict.fromkeys (preserves order)
                norm_next = list(dict.fromkeys(norm(u) for u in next_urls))
                visited = {"https://www.degewo.de/immosuche"} | set(norm_next)
                queue = norm_next
                while queue:
                    url = queue.pop(0)
                    try:
                        r = await client.get(url)
                        s = BeautifulSoup(r.text, "html.parser")
                        page_items, more_urls = _degewo_parse_page(s)
                        all_items.extend(page_items)
                        logger.info(f"degewo: fetched {url[-50:]} → {len(page_items)} items")
                        for u in more_urls:
                            nu = norm(u)
                            if nu not in visited:
                                visited.add(nu)
                                queue.append(nu)
                    except Exception as e:
                        logger.warning(f"degewo: failed to fetch page {url}: {e}")

        logger.info(f"degewo: {len(all_items)} total items across all pages")

        for item in all_items:
            try:
                titel_el = item.select_one("h3.c-headline a, a.c-headline--linked")
                titel = titel_el.get_text(strip=True) if titel_el else "Degewo Wohnung"

                address_el = item.select_one("div.c-copy p")
                address_text = address_el.get_text(strip=True) if address_el else ""
                ortsteil = address_text.split("|")[-1].strip() if "|" in address_text else ""
                bezirk = f"{ortsteil}, Berlin" if ortsteil else "Berlin"
                plz = _ortsteil_to_plz(ortsteil)

                preis = None
                zimmer = None
                groesse = "?"
                for dl_item in item.select("div.c-definition-list__item"):
                    dt = dl_item.select_one("dt")
                    dd = dl_item.select_one("dd")
                    if not dt or not dd:
                        continue
                    value = dt.get_text(strip=True)
                    label = dd.get_text(strip=True).lower()
                    if "miete" in label:
                        preis = parse_preis(value)
                    elif "zimmer" in label:
                        zimmer = parse_zimmer(value)
                    elif "m²" in label:
                        groesse = value

                link_el = item.select_one("a[href*='/immosuche/details/']")
                url = link_el["href"] if link_el else ""
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
                    # PLZ is in the address line (e.g. "13591 Berlin"), not in div.area
                    full_text = item.get_text(" ", strip=True)
                    plz_match = re.search(r'\b(1[0-4]\d{3})\b', full_text)
                    plz = plz_match.group(1) if plz_match else _ortsteil_to_plz(bezirk_text)
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
                    logger.info(f"wbm parsed: {listing['titel']} | {listing['zimmer']} Zi | {listing['groesse']} | {listing['preis']}€ | WBS:{listing['wbs']} | {listing['plz']} {listing['bezirk']}")
                except Exception as e:
                    logger.warning(f"Error parsing wbm item: {e}")
    except Exception as e:
        logger.error(f"Error scraping wbm: {e}")
    return listings


async def scrape_howoge():
    listings = []
    stadt = "Berlin"
    try:
        async with _playwright_semaphore:
            browser = await _get_browser()
            page = await browser.new_page()
            try:
                await page.goto(
                    "https://www.howoge.de/immobiliensuche/wohnungssuche.html",
                    wait_until="domcontentloaded",
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
            finally:
                await page.close()

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

                    full_text = item.get_text(" ", strip=True)
                    plz_match = re.search(r'\b(1[0-4]\d{3})\b', full_text)
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
            page_num = 1
            max_pages = 5
            seen_urls = set()
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

                # Stop if this page returned only URLs we've already seen (Gewobag repeats pages)
                page_urls = {l["url"] for l in listings[-len(items):] if l.get("url")}
                if page_urls and page_urls.issubset(seen_urls):
                    logger.info(f"gewobag: page {page_num} returned duplicate content, stopping")
                    break
                seen_urls.update(page_urls)

                # Nächste Seite?
                next_link = soup.select_one("a.next, a[rel='next']")
                if not next_link:
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
        from urllib.parse import urlparse, parse_qs
        async with _playwright_semaphore:
            browser = await _get_browser()
            page = await browser.new_page()
            try:
                await page.goto(
                    "https://stadtundland.de/wohnungssuche?district=all",
                    wait_until="domcontentloaded",
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
            finally:
                await page.close()

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
    from plz_berlin import ALL_BERLIN_PLZ
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
                    plz_candidate = plz_match.group(1) if plz_match else ""
                    plz = plz_candidate if plz_candidate in ALL_BERLIN_PLZ else ""

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
    MAX_PAGES = 50
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": ua}) as client:
            total_items = 0
            for page_num in range(1, MAX_PAGES + 1):
                url = ("https://www.berlinhaus.com/mietangebote/" if page_num == 1
                       else f"https://www.berlinhaus.com/mietangebote/page/{page_num}/")
                response = await client.get(url)
                soup = BeautifulSoup(response.text, "html.parser")
                items = soup.select("article.frymo-listing-item")
                if not items:
                    break
                total_items += len(items)

                for item in items:
                    try:
                        link_el = item.select_one("h3.frymo-listing-title a")
                        if not link_el:
                            continue
                        listing_url = link_el["href"]
                        titel = link_el.get_text(strip=True) or "Berlinhaus Wohnung"

                        loc_el = item.select_one("div.frymo-listing-location")
                        loc_text = loc_el.get_text(strip=True) if loc_el else ""
                        plz_match = re.search(r'(\d{5})', loc_text)
                        plz = plz_match.group(1) if plz_match else ""

                        if plz and plz not in ALL_BERLIN_PLZ:
                            continue

                        city = loc_text.split(",", 1)[-1].strip() if "," in loc_text else loc_text
                        bezirk = f"{city}, Berlin" if city and "berlin" not in city.lower() else city

                        area_el = item.select_one("span.frymo-listing-area .frymo-listing-meta-item-value")
                        groesse = area_el.get_text(strip=True).replace("m²", "").strip() if area_el else "?"

                        rooms_el = item.select_one("span.frymo-listing-rooms .frymo-listing-meta-item-value")
                        zimmer = parse_zimmer(rooms_el.get_text(strip=True)) if rooms_el else None

                        price_el = item.select_one(".frymo-listing-price-value")
                        preis = parse_preis(price_el.get_text(strip=True)) if price_el else None

                        img_el = item.select_one("img")
                        bild = img_el.get("src") if img_el else None

                        listing = {
                            "titel": titel,
                            "preis": preis,
                            "zimmer": zimmer,
                            "groesse": groesse,
                            "bezirk": bezirk,
                            "plz": plz,
                            "wbs": parse_wbs(titel),
                            "url": listing_url,
                            "bild": bild,
                            "anbieter": "Berlinhaus",
                        }
                        listings.append(listing)
                        logger.info(f"berlinhaus parsed: {titel} | {zimmer}Zi | {groesse}m² | {preis}€ | {plz} {bezirk}")
                    except Exception as e:
                        logger.warning(f"Error parsing berlinhaus item: {e}")

            logger.info(f"berlinhaus: scraped {page_num} pages ({total_items} total items, {len(listings)} Berlin listings)")
    except Exception as e:
        logger.error(f"Error scraping berlinhaus: {e}")
    return listings


SCRAPER_NAMES = ["Degewo", "WBM", "HOWOGE", "Gewobag", "Stadt und Land", "Berlinhaus", "Grand City"]


async def run_scraper(supabase_url, supabase_key):
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    results = await asyncio.gather(
        scrape_degewo(),
        scrape_wbm(),
        scrape_howoge(),
        scrape_gewobag(),
        scrape_stadtundland(),
        scrape_berlinhaus(),
        scrape_grandcity(),
        return_exceptions=True,
    )

    scraper_stats = []
    all_listings = []
    for name, r in zip(SCRAPER_NAMES, results):
        if isinstance(r, list):
            scraper_stats.append({"name": name, "count": len(r), "error": None})
            all_listings += r
        else:
            scraper_stats.append({"name": name, "count": 0, "error": str(r)})
            logger.error(f"Scraper error ({name}): {r}")
    logger.info(f"Found {len(all_listings)} total listings")

    # Deduplicate by URL before checking
    seen_in_batch: set[str] = set()
    listings_with_url = []
    for l in all_listings:
        url = l.get("url")
        if url and url not in seen_in_batch:
            seen_in_batch.add(url)
            listings_with_url.append(l)

    new_listings = []
    if listings_with_url:
        sem = asyncio.Semaphore(10)

        async def _is_new(client: httpx.AsyncClient, url: str) -> bool:
            async with sem:
                try:
                    r = await client.get(
                        f"{supabase_url}/rest/v1/seen_listings",
                        headers=headers,
                        params={"url": f"eq.{url}", "select": "url", "limit": "1"},
                    )
                    return r.status_code == 200 and len(r.json()) == 0
                except Exception as e:
                    logger.error(f"DB error checking {url}: {e}")
                    return False

        async with httpx.AsyncClient(timeout=10) as client:
            results = await asyncio.gather(
                *[_is_new(client, l["url"]) for l in listings_with_url]
            )
        new_listings = [l for l, is_new in zip(listings_with_url, results) if is_new]

    logger.info(f"Found {len(new_listings)} NEW listings")

    # Count new listings per scraper (normalise name for matching)
    new_by_anbieter: dict[str, int] = {}
    for listing in new_listings:
        key = listing.get("anbieter", "").lower().replace(" ", "")
        new_by_anbieter[key] = new_by_anbieter.get(key, 0) + 1
    for stat in scraper_stats:
        key = stat["name"].lower().replace(" ", "")
        stat["new_count"] = new_by_anbieter.get(key, 0)

    return new_listings, scraper_stats
