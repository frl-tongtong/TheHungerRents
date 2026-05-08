#!/usr/bin/env python3
"""
End-to-end pipeline test with fake users and real scraped listings.

Runs all scrapers (real HTTP, no DB interaction) and checks which fake
users would receive notifications. Useful for catching scraper regressions
(broken selectors, bad PLZ extraction) and filter bugs.

Usage:
    python test_pipeline.py          # summary only
    python test_pipeline.py -v       # show matched listings per user
    python test_pipeline.py -vv      # also show rejection reasons
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from scraper import (
    scrape_degewo, scrape_wbm, scrape_howoge,
    scrape_gewobag, scrape_stadtundland, scrape_berlinhaus, scrape_grandcity,
)
from filters import filter_listing

VERBOSE = "-v" in sys.argv or "-vv" in sys.argv
VERY_VERBOSE = "-vv" in sys.argv

SCRAPERS = [
    ("Degewo",        scrape_degewo),
    ("WBM",           scrape_wbm),
    ("HOWOGE",        scrape_howoge),
    ("Gewobag",       scrape_gewobag),
    ("Stadt und Land",scrape_stadtundland),
    ("Berlinhaus",    scrape_berlinhaus),
    ("Grand City",    scrape_grandcity),
]

# ── Fake users covering every filter dimension ───────────────────────────────
# Each has a descriptive user_id so failures are self-explaining.
FAKE_USERS = [
    {
        "_desc": "Ring | egal | egal | kein WBS  ← smoke test (should always match)",
        "user_id": "smoke_ring_any",
        "search_mode": "ring", "budget": 99999, "zimmer": "egal",
        "wbs": None, "bezirke": "[]", "plz": "[]", "active": True,
    },
    {
        "_desc": "Ring | 1.500€ | 3+  ← deine eigenen Einstellungen",
        "user_id": "ring_1500_3plus",
        "search_mode": "ring", "budget": 1500, "zimmer": "3+",
        "wbs": None, "bezirke": "[]", "plz": "[]", "active": True,
    },
    {
        "_desc": "Ring | 1.000€ | 2+  ← mittleres Budget",
        "user_id": "ring_1000_2plus",
        "search_mode": "ring", "budget": 1000, "zimmer": "2+",
        "wbs": None, "bezirke": "[]", "plz": "[]", "active": True,
    },
    {
        "_desc": "Ring | 1.500€ | egal | WBS 140  ← WBS-Nutzer",
        "user_id": "ring_1500_wbs140",
        "search_mode": "ring", "budget": 1500, "zimmer": "egal",
        "wbs": 140, "bezirke": "[]", "plz": "[]", "active": True,
    },
    {
        "_desc": "PLZ Friedrichshain | 1.500€ | egal  ← PLZ-Modus",
        "user_id": "plz_friedrichshain",
        "search_mode": "plz", "budget": 1500, "zimmer": "egal",
        "wbs": None, "bezirke": "[]",
        "plz": '["10243","10245","10247","10249"]', "active": True,
    },
    {
        "_desc": "Bezirk Neukölln | 1.500€ | egal  ← Bezirk-Modus",
        "user_id": "bezirk_neukoelln",
        "search_mode": "bezirk", "budget": 1500, "zimmer": "egal",
        "wbs": None, "bezirke": '["Neukölln"]', "plz": "[]", "active": True,
    },
    {
        "_desc": "Ring | 500€ | 3+  ← unmöglich, erwarte 0 Treffer",
        "user_id": "impossible_500_3plus",
        "search_mode": "ring", "budget": 500, "zimmer": "3+",
        "wbs": None, "bezirke": "[]", "plz": "[]", "active": True,
    },
]


def fmt_listing(listing):
    plz = listing.get("plz", "")
    loc = f"{listing.get('bezirk','?')} ({plz})" if plz else listing.get("bezirk", "?")
    return (
        f"{listing.get('anbieter','?'):12s}  "
        f"{listing.get('zimmer','?')} Zi  "
        f"{listing.get('preis','?'):>5}€  "
        f"{listing.get('groesse','?'):>8}  "
        f"{loc}"
    )


async def main():
    print("Starte Scraper …\n")

    tasks = [s() for _, s in SCRAPERS]
    names = [n for n, _ in SCRAPERS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    print("── Scraper-Ergebnisse " + "─" * 50)
    all_listings = []
    issues = []
    for name, r in zip(names, results):
        if isinstance(r, Exception):
            print(f"  ❌  {name:15s}  FEHLER: {r}")
            issues.append(name)
        elif not r:
            print(f"  ⚠️   {name:15s}  0 Listings gefunden")
            issues.append(name)
        else:
            no_plz = sum(1 for l in r if not l.get("plz"))
            plz_warn = f"  ({no_plz} ohne PLZ ⚠️)" if no_plz else ""
            print(f"  ✅  {name:15s}  {len(r)} Listings{plz_warn}")
            all_listings.extend(r)

    print(f"\nGesamt: {len(all_listings)} Listings von {len(names) - len(issues)}/{len(names)} Scrapern\n")

    if not all_listings:
        print("Keine Listings — Abbruch.")
        return

    print("── Fake-User-Filter " + "─" * 52)
    total_issues = 0

    for user in FAKE_USERS:
        matches = []
        misses = []
        for listing in all_listings:
            ok, reason = filter_listing(listing, user)
            if ok:
                matches.append(listing)
            else:
                misses.append((listing, reason))

        expected_zero = "unmöglich" in user["_desc"]
        if expected_zero:
            status = "✅ korrekt (0 erwartet)" if not matches else f"❌ {len(matches)} Treffer, erwartet 0!"
        else:
            status = f"✅ {len(matches)} Treffer" if matches else "❌ 0 Treffer — Filter zu eng oder Scraper-Problem"

        if not matches and not expected_zero:
            total_issues += 1

        print(f"\n{user['user_id']}")
        print(f"  {user['_desc']}")
        print(f"  → {status}")

        if VERBOSE and matches:
            for l in matches[:5]:
                print(f"       {fmt_listing(l)}")
            if len(matches) > 5:
                print(f"       … +{len(matches) - 5} weitere")

        if VERY_VERBOSE and misses:
            # Group rejections by reason prefix
            from collections import Counter
            reasons = Counter(r.split(" ")[0] for _, r in misses)
            print(f"     Ablehnungen: {dict(reasons)}")

    print("\n" + "─" * 72)
    if total_issues:
        print(f"⚠️  {total_issues} Nutzer ohne Treffer — Scraper oder Filter prüfen!")
    else:
        print("✅  Alle Nutzer (außer dem Unmöglich-Test) haben Treffer.")

    if issues:
        print(f"⚠️  Scraper mit Problemen: {', '.join(issues)}")


if __name__ == "__main__":
    asyncio.run(main())
