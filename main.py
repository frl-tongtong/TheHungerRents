import os
import logging
import json
import re
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# Conversation states
SUCHTYP = 0
PLZ_EINGABE = 1
BEZIRK = 2
BUDGET = 3
ZIMMER = 4
WBS = 5

BEZIRKE = [
    "Alle", "Mitte", "Prenzlauer Berg / Pankow",
    "Friedrichshain-Kreuzberg", "Neukölln",
    "Tempelhof-Schöneberg", "Charlottenburg-Wilmersdorf",
    "Lichtenberg", "Treptow-Köpenick", "Spandau",
    "Reinickendorf", "Steglitz-Zehlendorf", "Marzahn-Hellersdorf"
]
BUDGETS = ["bis 800€", "bis 1.000€", "bis 1.200€", "kein Limit"]
ZIMMER_OPTIONS = ["1+", "2+", "3+", "egal"]
WBS_OPTIONS = ["Ohne WBS", "Mit WBS", "Egal"]


def db_get(table, filters=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = httpx.get(url, headers=HEADERS, params=filters or {})
    return r.json() if r.status_code == 200 else []


def db_upsert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    r = httpx.post(url, headers=headers, json=data)
    return r.status_code in (200, 201)


def db_update(table, data, filters):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = httpx.patch(url, headers=HEADERS, json=data, params=filters)
    return r.status_code in (200, 204)


def bezirk_keyboard(selected):
    keyboard = []
    for b in BEZIRKE:
        label = f"✅ {b}" if b in selected else b
        keyboard.append([InlineKeyboardButton(label, callback_data=f"bezirk_{b}")])
    keyboard.append([InlineKeyboardButton("➡️ Weiter", callback_data="bezirk_DONE")])
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🔵 Innerhalb des S-Bahn-Rings", callback_data="suchtyp_ring")],
        [InlineKeyboardButton("📮 Nach Postleitzahlen", callback_data="suchtyp_plz")],
        [InlineKeyboardButton("🗺️ Nach Bezirken", callback_data="suchtyp_bezirk")],
    ]
    await update.message.reply_text(
        "🏠 Willkommen bei *TheHungerRents*!\n\n"
        "Ich suche neue Berliner Wohnungen und benachrichtige dich sofort.\n\n"
        "Wie möchtest du suchen?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SUCHTYP


async def suchtyp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    suchtyp = query.data.replace("suchtyp_", "")
    context.user_data["suchtyp"] = suchtyp

    if suchtyp == "ring":
        context.user_data["standort"] = "ring"
        keyboard = [[InlineKeyboardButton(b, callback_data=f"budget_{b}")] for b in BUDGETS]
        await query.edit_message_text(
            "🔵 *Innerhalb des S-Bahn-Rings* ausgewählt!\n\n"
            "💶 Was ist dein maximales Budget (Warmmiete)?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return BUDGET

    elif suchtyp == "plz":
        await query.edit_message_text(
            "📮 *Suche nach Postleitzahlen*\n\n"
            "Gib deine gewünschten PLZ kommagetrennt ein:\n"
            "_Beispiel: 10961, 10997, 10999, 10115_",
            parse_mode="Markdown"
        )
        return PLZ_EINGABE

    elif suchtyp == "bezirk":
        context.user_data["bezirke"] = []
        await query.edit_message_text(
            "🗺️ Welche Bezirke interessieren dich?",
            reply_markup=bezirk_keyboard([])
        )
        return BEZIRK


async def plz_eingabe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from plz_berlin import validate_plz
    user_input = update.message.text.strip()
    result = validate_plz(user_input)

    valid = result["valid"]
    invalid = result["invalid"]

    if invalid:
        invalid_text = "\n".join([f"❌ {i['plz']} – {i['reason']}" for i in invalid])
        valid_text = "\n".join([f"✅ {v['plz']} – {v['ortsteil']}" for v in valid]) if valid else ""

        msg = "Ich habe folgende Probleme gefunden:\n\n"
        if valid_text:
            msg += valid_text + "\n"
        msg += invalid_text
        msg += "\n\nBitte korrigiere die ungültigen PLZ und schick sie nochmal."

        if valid:
            keyboard = [[InlineKeyboardButton(
                f"➡️ Weiter mit {len(valid)} gültigen PLZ",
                callback_data="plz_weiter"
            )]]
            context.user_data["plz_valid"] = [v["plz"] for v in valid]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(msg)
        return PLZ_EINGABE

    # Alle PLZ gültig
    valid_text = "\n".join([f"✅ {v['plz']} – {v['ortsteil']}" for v in valid])
    context.user_data["standort"] = "plz"
    context.user_data["plz_liste"] = [v["plz"] for v in valid]

    keyboard = [[InlineKeyboardButton(b, callback_data=f"budget_{b}")] for b in BUDGETS]
    await update.message.reply_text(
        f"Super, folgende PLZ gespeichert:\n\n{valid_text}\n\n"
        "💶 Was ist dein maximales Budget (Warmmiete)?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BUDGET


async def plz_weiter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["standort"] = "plz"
    context.user_data["plz_liste"] = context.user_data.get("plz_valid", [])
    keyboard = [[InlineKeyboardButton(b, callback_data=f"budget_{b}")] for b in BUDGETS]
    await query.edit_message_text(
        "💶 Was ist dein maximales Budget (Warmmiete)?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BUDGET


async def bezirk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.replace("bezirk_", "", 1)

    if value == "DONE":
        if not context.user_data.get("bezirke"):
            context.user_data["bezirke"] = ["Alle"]
        context.user_data["standort"] = "bezirk"
        keyboard = [[InlineKeyboardButton(b, callback_data=f"budget_{b}")] for b in BUDGETS]
        await query.edit_message_text(
            "💶 Was ist dein maximales Budget (Warmmiete)?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return BUDGET

    selected = context.user_data.get("bezirke", [])
    if value == "Alle":
        selected = ["Alle"]
    else:
        if "Alle" in selected:
            selected = []
        if value in selected:
            selected.remove(value)
        else:
            selected.append(value)
    context.user_data["bezirke"] = selected
    await query.edit_message_reply_markup(reply_markup=bezirk_keyboard(selected))
    return BEZIRK


async def budget_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["budget"] = query.data.replace("budget_", "", 1)
    keyboard = [[InlineKeyboardButton(z, callback_data=f"zimmer_{z}")] for z in ZIMMER_OPTIONS]
    await query.edit_message_text(
        "🚪 Wie viele Zimmer brauchst du mindestens?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ZIMMER


async def zimmer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["zimmer"] = query.data.replace("zimmer_", "", 1)
    keyboard = [[InlineKeyboardButton(w, callback_data=f"wbs_{w}")] for w in WBS_OPTIONS]
    await query.edit_message_text(
        "📋 Sollen Wohnungen mit WBS-Pflicht angezeigt werden?\n\n"
        "_WBS = Wohnberechtigungsschein erforderlich_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WBS


async def wbs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["wbs"] = query.data.replace("wbs_", "", 1)

    user_id = str(update.effective_user.id)
    suchtyp = context.user_data.get("suchtyp", "bezirk")
    budget = context.user_data.get("budget", "kein Limit")
    zimmer = context.user_data.get("zimmer", "egal")
    wbs = context.user_data.get("wbs", "Egal")

    # Standort-Info für Anzeige und Speicherung
    if suchtyp == "ring":
        standort_display = "🔵 Innerhalb des S-Bahn-Rings"
        standort_data = json.dumps({"typ": "ring"})
    elif suchtyp == "plz":
        plz_liste = context.user_data.get("plz_liste", [])
        standort_display = f"📮 PLZ: {', '.join(plz_liste)}"
        standort_data = json.dumps({"typ": "plz", "liste": plz_liste})
    else:
        bezirke = context.user_data.get("bezirke", ["Alle"])
        standort_display = f"🗺️ {', '.join(bezirke)}"
        standort_data = json.dumps({"typ": "bezirk", "liste": bezirke})

    db_upsert("user_preferences", {
        "user_id": user_id,
        "standort": standort_data,
        "budget": budget,
        "zimmer": zimmer,
        "wbs": wbs,
        "active": True
    })

    await query.edit_message_text(
        "✅ *Alles gespeichert!*\n\n"
        f"📍 Standort: {standort_display}\n"
        f"💶 Budget: {budget}\n"
        f"🚪 Zimmer: {zimmer}\n"
        f"📋 WBS: {wbs}\n\n"
        "Ich melde mich sobald etwas passt! 🏹\n\n"
        "/einstellungen – Präferenzen ändern\n"
        "/pause – Benachrichtigungen pausieren",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def einstellungen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🔵 Innerhalb des S-Bahn-Rings", callback_data="suchtyp_ring")],
        [InlineKeyboardButton("📮 Nach Postleitzahlen", callback_data="suchtyp_plz")],
        [InlineKeyboardButton("🗺️ Nach Bezirken", callback_data="suchtyp_bezirk")],
    ]
    await update.message.reply_text(
        "🔧 Einstellungen aktualisieren – wie möchtest du suchen?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SUCHTYP


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    result = db_get("user_preferences", {"user_id": f"eq.{user_id}"})
    if result:
        current = result[0]["active"]
        new_state = not current
        db_update("user_preferences", {"active": new_state}, {"user_id": f"eq.{user_id}"})
        msg = "▶️ Benachrichtigungen wieder aktiv!" if new_state else "⏸️ Pausiert. /pause zum Reaktivieren."
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Noch keine Einstellungen. Starte mit /start!")


async def scraper_job(context: ContextTypes.DEFAULT_TYPE):
    from scraper import run_scraper
    from plz_berlin import plz_matches_filter
    import re

    logger.info("Running scraper...")
    new_listings = await run_scraper(SUPABASE_URL, SUPABASE_KEY)

    if not new_listings:
        return

    users = db_get("user_preferences", {"active": "eq.true"})
    budget_map = {"bis 800€": 800, "bis 1.000€": 1000, "bis 1.200€": 1200, "kein Limit": 99999}
    zimmer_map = {"1+": 1, "2+": 2, "3+": 3, "egal": 0}

    for user in users:
        user_id = user["user_id"]
        max_budget = budget_map.get(user["budget"], 99999)
        min_zimmer = zimmer_map.get(user["zimmer"], 0)
        wbs_filter = user.get("wbs", "Egal")

        # Standort-Filter laden
        standort_raw = user.get("standort")
        # Fallback für alte Nutzer die noch bezirke-Spalte haben
        if not standort_raw:
            bezirke_raw = user.get("bezirke", '["Alle"]')
            bezirke = json.loads(bezirke_raw) if isinstance(bezirke_raw, str) else bezirke_raw
            standort = {"typ": "bezirk", "liste": bezirke}
        else:
            standort = json.loads(standort_raw) if isinstance(standort_raw, str) else standort_raw

        for listing in new_listings:
            # PLZ aus Listing extrahieren
            adresse = listing.get("bezirk", "") + " " + listing.get("titel", "")
            plz_match = re.search(r'\b(\d{5})\b', adresse)
            listing_plz = plz_match.group(1) if plz_match else None

            # Standort-Filter
            if standort["typ"] == "ring":
                if listing_plz and not plz_matches_filter(listing_plz, "ring", None):
                    continue
            elif standort["typ"] == "plz":
                if listing_plz and not plz_matches_filter(listing_plz, "plz", standort["liste"]):
                    continue
            elif standort["typ"] == "bezirk":
                bezirke = standort.get("liste", ["Alle"])
                if "Alle" not in bezirke:
                    if listing_plz:
                        if not plz_matches_filter(listing_plz, "bezirk", bezirke):
                            continue
                    else:
                        # Fallback: Text-Matching wenn keine PLZ
                        if not any(b.lower() in listing.get("bezirk", "").lower() for b in bezirke):
                            continue

            # Budget Filter
            if listing.get("preis") and listing["preis"] > max_budget:
                continue

            # Zimmer Filter
            if listing.get("zimmer") and min_zimmer > 0 and listing["zimmer"] < min_zimmer:
                continue

            # WBS Filter
            listing_wbs = listing.get("wbs", False)
            if wbs_filter == "Ohne WBS" and listing_wbs:
                continue
            if wbs_filter == "Mit WBS" and not listing_wbs:
                continue

            wbs_label = "🔑 WBS erforderlich" if listing_wbs else "✅ Kein WBS"

            msg = (
                f"🏠 *Neue Wohnung!*\n\n"
                f"📍 {listing.get('bezirk', '?')}\n"
                f"🚪 {listing.get('zimmer', '?')} Zimmer\n"
                f"💶 {listing.get('preis', '?')}€ warm\n"
                f"📐 {listing.get('groesse', '?')}\n"
                f"📋 {wbs_label}\n"
                f"🏢 {listing.get('anbieter', '?')}\n\n"
                f"🔗 [Zur Wohnung]({listing.get('url', '')})"
            )
            try:
                await context.bot.send_message(
                    chat_id=user_id, text=msg,
                    parse_mode="Markdown", disable_web_page_preview=False
                )
            except Exception as e:
                logger.error(f"Could not send to {user_id}: {e}")


def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("einstellungen", einstellungen),
        ],
        states={
            SUCHTYP: [CallbackQueryHandler(suchtyp_callback, pattern="^suchtyp_")],
            PLZ_EINGABE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, plz_eingabe_handler),
                CallbackQueryHandler(plz_weiter_callback, pattern="^plz_weiter$"),
            ],
            BEZIRK: [CallbackQueryHandler(bezirk_callback, pattern="^bezirk_")],
            BUDGET: [CallbackQueryHandler(budget_callback, pattern="^budget_")],
            ZIMMER: [CallbackQueryHandler(zimmer_callback, pattern="^zimmer_")],
            WBS: [CallbackQueryHandler(wbs_callback, pattern="^wbs_")],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("pause", pause))
    app.job_queue.run_repeating(scraper_job, interval=120, first=10)

    logger.info("TheHungerRents is running 🏹")
    app.run_polling()


if __name__ == "__main__":
    main()
