#!/usr/bin/env python3
"""
Filter sanity check.

Loads real user preferences from Supabase, then runs them against a set
of canary listings that cover every filter dimension. Nothing is sent.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python test_filter.py

Add -v / --verbose to also print every rejection reason.
"""
import json
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(__file__))
from filters import filter_listing

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def db_get(table, params=None):
    r = httpx.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        params=params or {},
    )
    return r.json() if r.status_code == 200 else []


# ── Canary listings ─────────────────────────────────────────────────────────
# Each entry covers a specific filter dimension.
# PLZs inside the S-Bahn ring: 10115, 10963, 10245, 12049, 10405, 13357
# PLZs outside the ring: 13581 (Spandau), 14165 (Zehlendorf), 12555 (Köpenick)

CANARY = [
    # ── Ring / location
    {
        "_id": "L1", "_label": "Ring | 2 Zi | 900€ | kein WBS (Mitte)",
        "titel": "Schöne 2-Zi in Mitte", "plz": "10115", "bezirk": "Mitte, Berlin",
        "preis": 900, "zimmer": 2, "groesse": "60", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/L1", "bild": None,
    },
    {
        "_id": "L2", "_label": "Ring | 1 Zi | 600€ | kein WBS (Kreuzberg)",
        "titel": "Studio Kreuzberg", "plz": "10963", "bezirk": "Kreuzberg, Berlin",
        "preis": 600, "zimmer": 1, "groesse": "35", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/L2", "bild": None,
    },
    {
        "_id": "L3", "_label": "Ring | 3 Zi | 1500€ | kein WBS (Prenzlauer Berg)",
        "titel": "Familienwhg Prenzlauer Berg", "plz": "10405", "bezirk": "Prenzlauer Berg, Berlin",
        "preis": 1500, "zimmer": 3, "groesse": "85", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/L3", "bild": None,
    },
    {
        "_id": "L4", "_label": "AUSSERHALB Ring | 2 Zi | 800€ | kein WBS (Spandau)",
        "titel": "Wohnung Spandau", "plz": "13581", "bezirk": "Spandau, Berlin",
        "preis": 800, "zimmer": 2, "groesse": "65", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/L4", "bild": None,
    },
    {
        "_id": "L5", "_label": "AUSSERHALB Ring | 2 Zi | 800€ | kein WBS (Zehlendorf)",
        "titel": "Wohnung Zehlendorf", "plz": "14165", "bezirk": "Zehlendorf, Berlin",
        "preis": 800, "zimmer": 2, "groesse": "62", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/L5", "bild": None,
    },
    # ── Budget boundary
    {
        "_id": "B1", "_label": "Ring | 2 Zi | 1000€ | kein WBS  ← Grenzfall Preis",
        "titel": "Wohnung genau am Budget", "plz": "10245", "bezirk": "Friedrichshain, Berlin",
        "preis": 1000, "zimmer": 2, "groesse": "58", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/B1", "bild": None,
    },
    {
        "_id": "B2", "_label": "Ring | 2 Zi | 1001€ | kein WBS  ← 1€ über Grenze",
        "titel": "Wohnung 1€ über Budget", "plz": "10245", "bezirk": "Friedrichshain, Berlin",
        "preis": 1001, "zimmer": 2, "groesse": "58", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/B2", "bild": None,
    },
    # ── WBS
    {
        "_id": "W1", "_label": "Ring | 2 Zi | 750€ | WBS 100–140",
        "titel": "WBS-Wohnung Neukölln", "plz": "12049", "bezirk": "Neukölln, Berlin",
        "preis": 750, "zimmer": 2, "groesse": "55", "wbs": (100, 140),
        "anbieter": "Test", "url": "https://example.com/W1", "bild": None,
    },
    {
        "_id": "W2", "_label": "Ring | 2 Zi | 700€ | WBS 140–160",
        "titel": "WBS-Wohnung Wedding", "plz": "13357", "bezirk": "Wedding, Berlin",
        "preis": 700, "zimmer": 2, "groesse": "54", "wbs": (140, 160),
        "anbieter": "Test", "url": "https://example.com/W2", "bild": None,
    },
    {
        "_id": "W3", "_label": "Ring | 2 Zi | 680€ | WBS (kein Level angegeben)",
        "titel": "WBS-Wohnung Moabit", "plz": "10551", "bezirk": "Moabit, Berlin",
        "preis": 680, "zimmer": 2, "groesse": "52", "wbs": (100, 220),
        "anbieter": "Test", "url": "https://example.com/W3", "bild": None,
    },
    # ── Kein PLZ (soll bei allen Suchwegen durchkommen)
    {
        "_id": "N1", "_label": "Ring | 2 Zi | 800€ | kein WBS | PLZ unbekannt",
        "titel": "Wohnung ohne PLZ", "plz": "", "bezirk": "Berlin",
        "preis": 800, "zimmer": 2, "groesse": "60", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/N1", "bild": None,
    },
    # ── Bezirk-spezifisch (für Nutzer mit Bezirk-Suche)
    {
        "_id": "BZ1", "_label": "Neukölln | 2 Zi | 900€ | außerhalb Ring",
        "titel": "Wohnung Neukölln-Süd", "plz": "12357", "bezirk": "Neukölln, Berlin",
        "preis": 900, "zimmer": 2, "groesse": "63", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/BZ1", "bild": None,
    },
    {
        "_id": "BZ2", "_label": "Charlottenburg | 3 Zi | 1800€ | außerhalb Ring",
        "titel": "Wohnung Charlottenburg", "plz": "14059", "bezirk": "Charlottenburg-Wilmersdorf, Berlin",
        "preis": 1800, "zimmer": 3, "groesse": "92", "wbs": False,
        "anbieter": "Test", "url": "https://example.com/BZ2", "bild": None,
    },
]


def user_summary(user):
    mode = user.get("search_mode", "ring")
    budget = user.get("budget", "∞")
    zimmer = user.get("zimmer", "egal")
    wbs = user.get("wbs")
    uid = user["user_id"]

    bezirke_raw = user.get("bezirke") or "[]"
    bezirke = json.loads(bezirke_raw) if isinstance(bezirke_raw, str) else (bezirke_raw or [])
    plz_raw = user.get("plz") or "[]"
    plz_list = json.loads(plz_raw) if isinstance(plz_raw, str) else (plz_raw or [])

    location_detail = {
        "ring": "S-Bahn-Ring",
        "plz": f"PLZ {plz_list}",
        "bezirk": f"Bezirke {bezirke}",
    }.get(mode, mode)

    wbs_str = f"WBS {wbs}" if wbs else "kein WBS"
    return f"User {uid}  [{location_detail} | Budget {budget}€ | {zimmer} | {wbs_str}]"


def main():
    users = db_get("user_preferences", {"active": "eq.true"})
    if not users:
        print("Keine aktiven Nutzer gefunden (oder Supabase-Verbindung fehlgeschlagen).")
        sys.exit(1)

    print(f"Geladene Nutzer: {len(users)}  |  Canary-Listings: {len(CANARY)}\n")
    print("=" * 72)

    total_issues = 0

    for user in users:
        print(user_summary(user))

        hits = []
        misses = []
        for listing in CANARY:
            ok, reason = filter_listing(listing, user)
            if ok:
                hits.append(listing)
            else:
                misses.append((listing, reason))

        if hits:
            for l in hits:
                print(f"  ✅  {l['_id']}  {l['_label']}")
        else:
            print("  ⚠️  keine Treffer bei keinem Canary-Listing")
            total_issues += 1

        if VERBOSE:
            for l, reason in misses:
                print(f"  ❌  {l['_id']}  {l['_label']}")
                print(f"       → {reason}")

        print()

    print("=" * 72)
    if total_issues:
        print(f"⚠️  {total_issues} Nutzer ohne Treffer — Einstellungen prüfen!")
    else:
        print("✅  Alle Nutzer haben mindestens einen Treffer.")

    # Quick sanity: B1 and B2 differ by 1€ — check they're treated differently
    # for any user with budget=1000
    budget_1000_users = [u for u in users if u.get("budget") == 1000]
    if budget_1000_users:
        print()
        for u in budget_1000_users:
            b1_ok, _ = filter_listing(CANARY[5], u)  # B1: 1000€
            b2_ok, _ = filter_listing(CANARY[6], u)  # B2: 1001€
            status = "✅ korrekt" if b1_ok and not b2_ok else "❌ Budget-Grenze falsch!"
            print(f"  Budget-Grenztest für {u['user_id']}: B1(1000€)={b1_ok} B2(1001€)={b2_ok} → {status}")


if __name__ == "__main__":
    main()
