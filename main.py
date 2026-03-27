import os
import re
import json
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from scraper import run_scraper

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────
TOKEN = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ─── Conversation States ────────────────────────────────────
SEARCH_MODE, BEZIRK, PLZ_INPUT, BUDGET, BUDGET_CUSTOM, ZIMMER = range(6)

# ─── Constants ──────────────────────────────────────────────
BEZIRKE = [
    "Mitte", "Friedrichshain-Kreuzberg", "Pankow",
    "Charlottenburg-Wilmersdorf", "Spandau", "Steglitz-Zehlendorf",
    "Tempelhof-Schöneberg", "Neukölln", "Treptow-Köpenick",
    "Marzahn-Hellersdorf", "Lichtenberg", "Reinickendorf"
]

# PLZ innerhalb des S-Bahn-Rings (ungefähre Auswahl)
S_BAHN_RING_PLZ = [
    "10115", "10117", "10119", "10178", "10179",  # Mitte
    "10243", "10245", "10247", "10249",            # Friedrichshain
    "10317",                                        # Lichtenberg (Rummelsburg)
    "10405", "10407", "10409",                      # Prenzlauer Berg
    "10435", "10437", "10439",                      # Prenzlauer Berg
    "10551", "10553", "10555", "10557", "10559",    # Moabit
    "10585", "10587", "10589",                      # Charlottenburg
    "10623", "10625", "10627", "10629",             # Charlottenburg
    "10707", "10709", "10711", "10713", "10715",    # Wilmersdorf
    "10717", "10719",                               # Wilmersdorf
    "10777", "10779", "10781", "10783",             # Schöneberg
    "10785", "10787", "10789",                      # Tiergarten/Schöneberg
    "10823", "10825", "10827", "10829",             # Schöneberg
    "10961", "10963", "10965", "10967", "10969",    # Kreuzberg
    "10997", "10999",                               # Kreuzberg
    "12043", "12045", "12047", "12049",             # Neukölln
    "12051", "12053", "12055",                      # Neukölln
    "13347", "13349", "13351", "13353", "13355",    # Wedding
    "13357", "13359",                               # Wedding
]

ZIMMER_OPTIONS = ["1+", "2+", "3+", "egal"]


# ─── Database Helpers ───────────────────────────────────────

def db_get(table, filters=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = filters or {}
    r = httpx.get(url, headers=HEADERS, params=params)
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


# ─── Budget Parser ──────────────────────────────────────────

def parse_budget(text: str):
    """Parse user input into a budget integer. Returns None if invalid."""
    cleaned = re.sub(r'[^\d.,]', '', text.strip())
    if not cleaned:
        return None

    if ',' in cleaned and '.' in cleaned:
        if cleaned.rindex(',') > cleaned.rindex('.'):
            # German: 1.100,50
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            # English: 1,100.50
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        parts = cleaned.split(',')
        if len(parts) == 2 and len(parts[1]) == 3:
            cleaned = cleaned.replace(',', '')   # 1,100 → 1100
        else:
            cleaned = cleaned.replace(',', '.')  # 850,50 → 850.5
    elif '.' in cleaned:
        parts = cleaned.split('.')
        if len(parts) == 2 and len(parts[1]) == 3:
            cleaned = cleaned.replace('.', '')   # 1.100 → 1100
        # else: 850.50 stays

    try:
        value = int(float(cleaned))
        if 200 <= value <= 5000:
            return value
        return None
    except (ValueError, OverflowError):
        return None


def format_budget(value):
    """Format budget integer for display: 1100 → '1.100€'"""
    if value >= 99999:
        return "egal"
    return f"{value:,}€".replace(",", ".")


# ─── Keyboards ──────────────────────────────────────────────

def search_mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Innerhalb des S-Bahn-Rings", callback_data="mode:ring")],
        [InlineKeyboardButton("📮 Nach Postleitzahlen", callback_data="mode:plz")],
        [InlineKeyboardButton("🏙️ Nach Bezirken", callback_data="mode:bezirk")],
    ])


def bezirk_keyboard(selected):
    keyboard = []
    for b in BEZIRKE:
        mark = "✅ " if b in selected else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{b}", callback_data=f"bezirk:{b}")])
    keyboard.append([InlineKeyboardButton("✔️ Fertig", callback_data="bezirk:done")])
    return InlineKeyboardMarkup(keyboard)


def budget_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("bis 500€", callback_data="budget:500")],
        [InlineKeyboardButton("bis 1.000€", callback_data="budget:1000")],
        [InlineKeyboardButton("bis 1.500€", callback_data="budget:1500")],
        [InlineKeyboardButton("egal", callback_data="budget:99999")],
        [InlineKeyboardButton("✏️ Eigenen Betrag", callback_data="budget:custom")],
    ])


def zimmer_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(z, callback_data=f"zimmer:{z}")]
        for z in ZIMMER_OPTIONS
    ])


# ─── /start ─────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()
    context.user_data["bezirke"] = []

    await update.message.reply_text(
        f"🏠 Willkommen bei *TheHungerRents*, {user.first_name}!\n\n"
        "Ich durchsuche Berliner Hausverwaltungsseiten nach neuen Wohnungen "
        "und schicke dir sofort eine Nachricht wenn etwas Passendes auftaucht.\n\n"
        "Lass uns kurz deine Suchpräferenzen einstellen!",
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        "🔧 Einstellungen aktualisieren – wie möchtest du suchen?",
        reply_markup=search_mode_keyboard()
    )
    return SEARCH_MODE


# ─── /einstellungen ─────────────────────────────────────────

async def einstellungen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["bezirke"] = []

    await update.message.reply_text(
        "🔧 Einstellungen aktualisieren – wie möchtest du suchen?",
        reply_markup=search_mode_keyboard()
    )
    return SEARCH_MODE


# ─── Search Mode Handler ────────────────────────────────────

async def search_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":")[1]
    context.user_data["search_mode"] = mode

    if mode == "ring":
        context.user_data["bezirke"] = []
        context.user_data["plz"] = S_BAHN_RING_PLZ
        await query.edit_message_text("🔵 Innerhalb des S-Bahn-Rings ausgewählt!")
        await query.message.reply_text(
            "💶 Was ist dein maximales Budget (Warmmiete)?",
            reply_markup=budget_keyboard()
        )
        return BUDGET

    elif mode == "plz":
        await query.edit_message_text(
            "📮 Schreib deine Wunsch-Postleitzahlen, getrennt durch Komma oder Leerzeichen.\n\n"
            "Beispiel: `10999, 10997, 12045`",
            parse_mode="Markdown"
        )
        return PLZ_INPUT

    elif mode == "bezirk":
        await query.edit_message_text(
            "🏙️ Welche Bezirke interessieren dich? (mehrere auswählen möglich)",
            reply_markup=bezirk_keyboard([])
        )
        return BEZIRK


# ─── PLZ Input Handler ──────────────────────────────────────

async def plz_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Extract all 5-digit numbers
    plz_list = re.findall(r'\d{5}', text)

    if not plz_list:
        await update.message.reply_text(
            "🤔 Keine gültigen Postleitzahlen erkannt. "
            "Bitte gib mindestens eine 5-stellige PLZ ein, z.B. `10999`",
            parse_mode="Markdown"
        )
        return PLZ_INPUT

    context.user_data["plz"] = plz_list
    context.user_data["bezirke"] = []

    await update.message.reply_text(
        f"📮 PLZ gespeichert: {', '.join(plz_list)}"
    )
    await update.message.reply_text(
        "💶 Was ist dein maximales Budget (Warmmiete)?",
        reply_markup=budget_keyboard()
    )
    return BUDGET


# ─── Bezirk Handlers ────────────────────────────────────────

async def bezirk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]

    if choice == "done":
        selected = context.user_data.get("bezirke", [])
        if not selected:
            await query.answer("Wähle mindestens einen Bezirk!", show_alert=True)
            return BEZIRK

        context.user_data["plz"] = []
        await query.edit_message_text(
            f"🏙️ Bezirke: {', '.join(selected)}"
        )
        await query.message.reply_text(
            "💶 Was ist dein maximales Budget (Warmmiete)?",
            reply_markup=budget_keyboard()
        )
        return BUDGET

    # Toggle bezirk selection
    selected = context.user_data.get("bezirke", [])
    if choice in selected:
        selected.remove(choice)
    else:
        selected.append(choice)
    context.user_data["bezirke"] = selected

    await query.edit_message_reply_markup(
        reply_markup=bezirk_keyboard(selected)
    )
    return BEZIRK


# ─── Budget Handlers ────────────────────────────────────────

async def budget_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]

    if choice == "custom":
        await query.edit_message_text(
            "💶 Schreib dein maximales Budget als Zahl, z.B. `1100`",
            parse_mode="Markdown"
        )
        return BUDGET_CUSTOM

    budget = int(choice)
    context.user_data["budget"] = budget
    await query.edit_message_text(f"💶 Budget: {format_budget(budget)}")
    await query.message.reply_text(
        "🚪 Wie viele Zimmer mindestens?",
        reply_markup=zimmer_keyboard()
    )
    return ZIMMER


async def budget_custom_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = parse_budget(update.message.text)

    if value is None:
        await update.message.reply_text(
            "🤔 Das hab ich nicht erkannt. "
            "Schreib einfach eine Zahl zwischen 200 und 5.000, z.B. `1100`",
            parse_mode="Markdown"
        )
        return BUDGET_CUSTOM

    context.user_data["budget"] = value
    await update.message.reply_text(f"💶 Budget: {format_budget(value)}")
    await update.message.reply_text(
        "🚪 Wie viele Zimmer mindestens?",
        reply_markup=zimmer_keyboard()
    )
    return ZIMMER


# ─── Zimmer Handler ─────────────────────────────────────────

async def zimmer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    zimmer = query.data.split(":")[1]
    context.user_data["zimmer"] = zimmer

    # Save preferences
    user_id = str(update.effective_user.id)
    search_mode = context.user_data.get("search_mode", "ring")
    bezirke = context.user_data.get("bezirke", [])
    plz = context.user_data.get("plz", [])
    budget = context.user_data.get("budget", 99999)

    prefs = {
        "user_id": user_id,
        "search_mode": search_mode,
        "bezirke": json.dumps(bezirke),
        "plz": json.dumps(plz),
        "budget": budget,
        "zimmer": zimmer,
        "active": True,
    }

    db_upsert("user_preferences", prefs)

    # Build summary
    if search_mode == "ring":
        location_info = "🔵 Innerhalb des S-Bahn-Rings"
    elif search_mode == "plz":
        location_info = f"📮 PLZ: {', '.join(plz)}"
    else:
        location_info = f"🏙️ Bezirke: {', '.join(bezirke)}"

    await query.edit_message_text(
        f"✅ *Einstellungen gespeichert!*\n\n"
        f"📍 {location_info}\n"
        f"💶 Budget: {format_budget(budget)}\n"
        f"🚪 Zimmer: {zimmer}\n\n"
        "Ich melde mich sobald etwas passt! 🏹\n\n"
        "/einstellungen – Präferenzen ändern\n"
        "/pause – Benachrichtigungen pausieren",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ─── /pause ─────────────────────────────────────────────────

async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    result = db_get("user_preferences", {"user_id": f"eq.{user_id}"})
    if result:
        current = result[0]["active"]
        new_state = not current
        db_update("user_preferences", {"active": new_state}, {"user_id": f"eq.{user_id}"})
        if new_state:
            await update.message.reply_text("▶️ Benachrichtigungen wieder aktiv!")
        else:
            await update.message.reply_text(
                "⏸️ Benachrichtigungen pausiert. Mit /pause wieder aktivieren."
            )
    else:
        await update.message.reply_text(
            "Du hast noch keine Einstellungen. Starte mit /start!"
        )


# ─── Startup Announcement ───────────────────────────────────

async def announce_new_version(context: ContextTypes.DEFAULT_TYPE):
    users = db_get("user_preferences")
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user["user_id"],
                text="🆕 *Neue Version deployed!*\n\nDer Bot wurde aktualisiert und läuft wieder.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not announce to {user['user_id']}: {e}")


# ─── Scraper Job ────────────────────────────────────────────

async def scraper_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running scraper...")
    new_listings = await run_scraper(SUPABASE_URL, SUPABASE_KEY)

    if not new_listings:
        logger.info("No new listings found.")
        return

    users = db_get("user_preferences", {"active": "eq.true"})
    zimmer_map = {"1+": 1, "2+": 2, "3+": 3, "egal": 0}

    for user in users:
        user_id = user["user_id"]
        search_mode = user.get("search_mode", "ring")
        bezirke = json.loads(user["bezirke"]) if isinstance(user["bezirke"], str) else user["bezirke"]
        plz_list = json.loads(user["plz"]) if isinstance(user.get("plz", "[]"), str) else user.get("plz", [])
        max_budget = user.get("budget", 99999)
        if isinstance(max_budget, str):
            max_budget = int(max_budget) if max_budget.isdigit() else 99999
        min_zimmer = zimmer_map.get(user.get("zimmer", "egal"), 0)

        for listing in new_listings:
            # ── Location filter ──
            if search_mode == "ring":
                listing_plz = listing.get("plz", "")
                if listing_plz and listing_plz not in S_BAHN_RING_PLZ:
                    continue
            elif search_mode == "plz":
                listing_plz = listing.get("plz", "")
                if listing_plz and plz_list and listing_plz not in plz_list:
                    continue
            elif search_mode == "bezirk" and bezirke:
                listing_bezirk = listing.get("bezirk", "").lower()
                if not any(b.lower() in listing_bezirk for b in bezirke):
                    continue

            # ── Budget filter ──
            if listing.get("preis") and listing["preis"] > max_budget:
                continue

            # ── Zimmer filter ──
            if listing.get("zimmer") and min_zimmer > 0 and listing["zimmer"] < min_zimmer:
                continue

            # ── Send notification ──
            msg = (
                f"🏠 *Neue Wohnung gefunden!*\n\n"
                f"📍 {listing.get('bezirk', '?')}\n"
                f"🚪 {listing.get('zimmer', '?')} Zimmer\n"
                f"💶 {listing.get('preis', '?')}€ warm\n"
                f"📐 {listing.get('groesse', '?')} m²\n"
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


# ─── Main ───────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("einstellungen", einstellungen),
        ],
        states={
            SEARCH_MODE: [
                CallbackQueryHandler(search_mode_callback, pattern="^mode:")
            ],
            BEZIRK: [
                CallbackQueryHandler(bezirk_callback, pattern="^bezirk:")
            ],
            PLZ_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, plz_input_handler)
            ],
            BUDGET: [
                CallbackQueryHandler(budget_callback, pattern="^budget:")
            ],
            BUDGET_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, budget_custom_handler)
            ],
            ZIMMER: [
                CallbackQueryHandler(zimmer_callback, pattern="^zimmer:")
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("pause", pause))
    app.job_queue.run_once(announce_new_version, when=3)
    app.job_queue.run_repeating(scraper_job, interval=120, first=10)

    logger.info("TheHungerRents is running 🏹")
    app.run_polling()


if __name__ == "__main__":
    main()
