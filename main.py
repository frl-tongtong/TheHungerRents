import asyncio
import os
import re
import sys
import json
import logging
from datetime import time, datetime, timezone
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from scraper import run_scraper
from plz_berlin import INNERHALB_RING, BEZIRKE

import sentry_sdk

# ─── Configure Sentry exception tracking ────────────────────────────────────────────────

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    send_default_pii=True,
)

# ─── Logging ────────────────────────────────────────────────
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.DEBUG)
_stdout_handler.addFilter(lambda r: r.levelno < logging.ERROR)
_stdout_handler.setFormatter(_formatter)

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.ERROR)
_stderr_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_stdout_handler, _stderr_handler])
logging.getLogger("httpx").setLevel(logging.WARNING)
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
SEARCH_MODE, BEZIRK, PLZ_INPUT, BUDGET, BUDGET_CUSTOM, ZIMMER, WBS, WBS_LEVEL = range(8)

# ─── Constants ──────────────────────────────────────────────
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
    data["modified_at"] = datetime.now(timezone.utc).isoformat()
    r = httpx.post(url, headers=headers, json=data)
    if r.status_code not in (200, 201):
        logger.error(f"db_upsert failed: {r.status_code} {r.text}")
        return False
    return True


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


def wbs_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ja, ich habe einen WBS", callback_data="wbs:yes")],
        [InlineKeyboardButton("❌ Nein, kein WBS", callback_data="wbs:no")],
    ])


def wbs_level_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("WBS 100", callback_data="wbslevel:100")],
        [InlineKeyboardButton("WBS 140", callback_data="wbslevel:140")],
        [InlineKeyboardButton("WBS 160", callback_data="wbslevel:160")],
        [InlineKeyboardButton("WBS 180", callback_data="wbslevel:180")],
        [InlineKeyboardButton("WBS 220+", callback_data="wbslevel:220")],
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
        context.user_data["plz"] = []
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
    await query.edit_message_text(f"🚪 Zimmer: {zimmer}")
    await query.message.reply_text(
        "📋 Hast du einen Wohnberechtigungsschein (WBS)?",
        reply_markup=wbs_keyboard()
    )
    return WBS


# ─── WBS Handlers ───────────────────────────────────────────

async def _save_and_confirm(query, context, wbs):
    user_id = str(query.from_user.id)
    search_mode = context.user_data.get("search_mode", "ring")
    bezirke = context.user_data.get("bezirke", [])
    plz = context.user_data.get("plz", [])
    budget = context.user_data.get("budget", 99999)
    zimmer = context.user_data.get("zimmer", "egal")

    db_upsert("user_preferences", {
        "user_id": user_id,
        "search_mode": search_mode,
        "bezirke": json.dumps(bezirke),
        "plz": json.dumps(plz),
        "budget": budget,
        "zimmer": zimmer,
        "wbs": wbs,
        "active": True,
    })

    if search_mode == "ring":
        location_info = "🔵 Innerhalb des S-Bahn-Rings"
    elif search_mode == "plz":
        location_info = f"📮 PLZ: {', '.join(plz)}"
    else:
        location_info = f"🏙️ Bezirke: {', '.join(bezirke)}"

    wbs_info = f"📋 WBS: {wbs}\n" if wbs else "📋 WBS: keiner\n"

    await query.edit_message_text(
        f"✅ *Einstellungen gespeichert!*\n\n"
        f"📍 {location_info}\n"
        f"💶 Budget: {format_budget(budget)}\n"
        f"🚪 Zimmer: {zimmer}\n"
        f"{wbs_info}\n"
        "Ich melde mich sobald etwas passt! 🏹\n\n"
        "/einstellungen – Präferenzen ändern\n"
        "/pause – Benachrichtigungen pausieren",
        parse_mode="Markdown"
    )


async def wbs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]

    if choice == "no":
        await _save_and_confirm(query, context, wbs=None)
        return ConversationHandler.END

    await query.edit_message_text(
        "📋 Welchen WBS hast du?",
        reply_markup=wbs_level_keyboard()
    )
    return WBS_LEVEL


async def wbs_level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    level = int(query.data.split(":")[1])
    await _save_and_confirm(query, context, wbs=level)
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
    total = len(users)
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user["user_id"],
                text=f"🆕 *Neue Version deployed!*\n\nDer Bot wurde aktualisiert und läuft wieder.\n👥 Aktuell {total} Nutzer registriert.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not announce to {user['user_id']}: {e}")


# ─── Daily Message ──────────────────────────────────────────

async def daily_message(context: ContextTypes.DEFAULT_TYPE):
    try:
        health_lines = []
        for stat in last_scraper_stats:
            if stat["error"]:
                icon = "❌"
                detail = "error"
            elif stat["count"] == 0:
                zeros = consecutive_zeros.get(stat["name"], 0)
                icon = "⚠️" if zeros >= ZERO_ALERT_THRESHOLD else "🟡"
                detail = f"0 listings found on site ({zeros}x in a row)"
            else:
                new = stat.get("new_count", 0)
                icon = "✅"
                detail = f"{stat['count']} found, {new} new"
            health_lines.append(f"{icon} {stat['name']}: {detail}")

        health_text = "\n\n*Scraper Health:*\n" + "\n".join(health_lines) if health_lines else ""

        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"Good morning! This is your reminder that Maik loves you dearly! ❤️🥰💖{health_text}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Could not send daily message to test user: {e}")


# ─── Scraper Health Tracking ────────────────────────────────
ADMIN_USER_ID = 446162891
consecutive_zeros: dict[str, int] = {}
last_scraper_stats: list[dict] = []

ZERO_ALERT_THRESHOLD = 3  # alert after this many consecutive zero-result runs


# ─── Scraper Job ────────────────────────────────────────────

async def scraper_job(context: ContextTypes.DEFAULT_TYPE):
    global last_scraper_stats
    logger.info("Running scraper...")
    try:
        new_listings, scraper_stats = await asyncio.wait_for(
            run_scraper(SUPABASE_URL, SUPABASE_KEY), timeout=115
        )
    except asyncio.TimeoutError:
        logger.error("scraper_job timed out after 115s")
        return
    last_scraper_stats = scraper_stats

    for stat in scraper_stats:
        name = stat["name"]
        if stat["error"]:
            consecutive_zeros[name] = consecutive_zeros.get(name, 0) + 1
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text=f"⚠️ Scraper error: *{name}*\n`{stat['error']}`",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"Could not send scraper alert: {e}")
        elif stat["count"] == 0:
            consecutive_zeros[name] = consecutive_zeros.get(name, 0) + 1
            if consecutive_zeros[name] == ZERO_ALERT_THRESHOLD:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=f"⚠️ *{name}* found 0 listings on the website for {ZERO_ALERT_THRESHOLD} consecutive runs. Scraper may be broken.",
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.warning(f"Could not send scraper alert: {e}")
        else:
            was_alerting = consecutive_zeros.get(name, 0) >= ZERO_ALERT_THRESHOLD
            consecutive_zeros[name] = 0
            if was_alerting:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=f"✅ *{name}* recovered — found {stat['count']} listings again.",
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.warning(f"Could not send recovery alert: {e}")

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

        user_wbs = user.get("wbs")  # None or int

        for listing in new_listings:
            # ── Location filter ──
            if search_mode == "ring":
                listing_plz = listing.get("plz", "")
                if listing_plz and listing_plz not in INNERHALB_RING:
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

            # ── WBS filter ──
            listing_wbs = listing.get("wbs")
            if listing_wbs:
                if user_wbs is None:
                    continue  # user has no WBS
                wbs_min, wbs_max = listing_wbs
                if not (wbs_min <= user_wbs <= wbs_max):
                    continue

            # ── Build WBS line for notification ──
            if listing_wbs:
                wbs_min, wbs_max = listing_wbs
                if wbs_min == wbs_max:
                    wbs_line = f"📋 WBS {wbs_min} erforderlich\n"
                elif wbs_min == 100 and wbs_max == 220:
                    wbs_line = "📋 WBS erforderlich\n"
                else:
                    wbs_line = f"📋 WBS {wbs_min}–{wbs_max} erforderlich\n"
            else:
                wbs_line = "📋 Kein WBS erforderlich\n"

            # ── Send notification ──
            plz = listing.get("plz", "")
            location = f"{listing.get('bezirk', '?')} ({plz})" if plz else listing.get('bezirk', '?')
            msg = (
                f"🏠 *Neue Wohnung gefunden!*\n\n"
                f"📍 {location}\n"
                f"🚪 {listing.get('zimmer', '?')} Zimmer\n"
                f"💶 {listing.get('preis', '?')}€ warm\n"
                f"📐 {listing.get('groesse', '?')} m²\n"
                f"{wbs_line}"
                f"🏢 {listing.get('anbieter', '?')}\n\n"
                f"🔗 [Zur Wohnung]({listing.get('url', '')})"
            )
            bild = listing.get("bild")
            try:
                if bild:
                    await context.bot.send_photo(
                        chat_id=user_id, photo=bild, caption=msg,
                        parse_mode="Markdown"
                    )
                else:
                    raise ValueError("no image")
            except Exception:
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
            WBS: [
                CallbackQueryHandler(wbs_callback, pattern="^wbs:")
            ],
            WBS_LEVEL: [
                CallbackQueryHandler(wbs_level_callback, pattern="^wbslevel:")
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("pause", pause))
    app.job_queue.run_once(announce_new_version, when=3)
    app.job_queue.run_daily(daily_message, time=time(8, 0))
    app.job_queue.run_repeating(scraper_job, interval=120, first=10, job_kwargs={"max_instances": 1})

    logger.info("TheHungerRents is running 🏹")
    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8080)),
            url_path=TOKEN,
            webhook_url=f"{webhook_url}/{TOKEN}",
            drop_pending_updates=True,
        )
    else:
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
