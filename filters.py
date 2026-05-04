import json
from plz_berlin import INNERHALB_RING

_ZIMMER_MAP = {"1+": 1, "2+": 2, "3+": 3, "egal": 0}


def filter_listing(listing: dict, user: dict) -> tuple[bool, str]:
    """Return (True, '') if listing matches user criteria, else (False, human-readable reason)."""
    search_mode = user.get("search_mode", "ring")

    bezirke_raw = user.get("bezirke") or "[]"
    bezirke = json.loads(bezirke_raw) if isinstance(bezirke_raw, str) else (bezirke_raw or [])

    plz_raw = user.get("plz") or "[]"
    plz_list = json.loads(plz_raw) if isinstance(plz_raw, str) else (plz_raw or [])

    max_budget = user.get("budget", 99999)
    if isinstance(max_budget, str):
        max_budget = int(max_budget) if str(max_budget).isdigit() else 99999

    min_zimmer = _ZIMMER_MAP.get(user.get("zimmer", "egal"), 0)
    user_wbs = user.get("wbs")

    # ── Location ──
    listing_plz = listing.get("plz", "")
    if search_mode == "ring":
        if listing_plz and listing_plz not in INNERHALB_RING:
            return False, f"PLZ {listing_plz} nicht im S-Bahn-Ring"
    elif search_mode == "plz":
        if listing_plz and plz_list and listing_plz not in plz_list:
            return False, f"PLZ {listing_plz} nicht in Nutzerliste"
    elif search_mode == "bezirk" and bezirke:
        listing_bezirk = listing.get("bezirk", "").lower()
        if not any(b.lower() in listing_bezirk for b in bezirke):
            return False, f"Bezirk nicht in Auswahl {bezirke}"

    # ── Budget ──
    if listing.get("preis") and listing["preis"] > max_budget:
        return False, f"Preis {listing['preis']}€ > Budget {max_budget}€"

    # ── Zimmer ──
    if listing.get("zimmer") and min_zimmer > 0 and listing["zimmer"] < min_zimmer:
        return False, f"{listing['zimmer']} Zi < Minimum {min_zimmer} Zi"

    # ── WBS ──
    listing_wbs = listing.get("wbs")
    if listing_wbs:
        if user_wbs is None:
            return False, "WBS erforderlich, Nutzer hat keinen WBS"
        wbs_min, wbs_max = listing_wbs
        if not (wbs_min <= user_wbs <= wbs_max):
            return False, f"WBS {user_wbs} nicht in [{wbs_min}–{wbs_max}]"

    return True, ""
