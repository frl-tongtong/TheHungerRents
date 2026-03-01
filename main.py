import os
import logging
import json
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

# Conversation states as simple integers
BEZIRK = 0
BUDGET = 1
ZIMMER = 2

BEZIRKE = [
    "Alle", "Mitte", "Prenzlauer Berg / Pankow",
    "Friedrichshain-Kreuzberg", "Neukölln",
    "Tempelhof-Schöneberg", "Charlottenburg-Wilmersdorf"
]
BUDGETS = ["bis 800€", "bis 1.000€", "bis 1.200€", "kein Limit"]
ZIMMER_OPTIONS = ["1+", "2+", "3+", "egal"]


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
    context.user_data["bezirke"] = []
    await update.message.reply_text(
        f"🏠 Willkommen bei *TheHungerRents*!\n\n"
        "Ich suche neue Berliner Wohnungen und benachrichtige dich sofort.\n\n"
        "Welche Bezirke interessieren dich?",
        parse_mode="Markdown",
        reply_markup=bezirk_keyboard([])
    )
    return BEZIRK


async def bezirk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.replace("bezirk_", "", 1)

    if value == "DONE":
        if not context.user_data.get("bezirke"):
            context.user_data["bezirke"] = ["Alle"]
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

    user_id = str(update.effective_user.id)
    bezirke = context.user_data.get("bezirke", ["Alle"])
    budget = context.user_data.get("budget", "kein Limit")
    zimmer = context.user_data.get("zimmer", "egal")

    db_upsert("user_preferences", {
        "user_id": user_id,
        "bezirke": json.dumps(bezirke),
        "budget": budget,
        "zimmer": zimmer,
        "active": True
    })

    await query.edit_message_text(
        "✅ *Alles gespeichert!*\n\n"
        f"📍 Bezirke: {', '.join(bezirke)}\n"
        f"💶 Budget: {budget}\n"
        f"🚪 Zimmer: {zimmer}\n\n"
        "Ich melde mich sobald etwas passt! 🏹\n\n"
        "/einstellungen – Präferenzen ändern\n"
        "/pause – Benachrichtigungen pausieren",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def einstellungen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bezirke"] = []
    await update.message.reply_text(
        "🔧 Einstellungen aktualisieren – welche Bezirke?",
        reply_markup=bezirk_keyboard([])
    )
    return BEZIRK


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
    logger.info("Running scraper...")
    new_listings = await run_scraper(SUPABASE_URL, SUPABASE_KEY)

    if not new_listings:
        return

    users = db_get("user_preferences", {"active": "eq.true"})
    budget_map = {"bis 800€": 800, "bis 1.000€": 1000, "bis 1.200€": 1200, "kein Limit": 99999}
    zimmer_map = {"1+": 1, "2+": 2, "3+": 3, "egal": 0}

    for user in users:
        user_id = user["user_id"]
        bezirke = json.loads(user["bezirke"]) if isinstance(user["bezirke"], str) else user["bezirke"]
        max_budget = budget_map.get(user["budget"], 99999)
        min_zimmer = zimmer_map.get(user["zimmer"], 0)

        for listing in new_listings:
            if "Alle" not in bezirke:
                if not any(b.lower() in listing.get("bezirk", "").lower() for b in bezirke):
                    continue
            if listing.get("preis") and listing["preis"] > max_budget:
                continue
            if listing.get("zimmer") and min_zimmer > 0 and listing["zimmer"] < min_zimmer:
                continue

            msg = (
                f"🏠 *Neue Wohnung!*\n\n"
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


def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("einstellungen", einstellungen),
        ],
        states={
            BEZIRK: [CallbackQueryHandler(bezirk_callback, pattern="^bezirk_")],
            BUDGET: [CallbackQueryHandler(budget_callback, pattern="^budget_")],
            ZIMMER: [CallbackQueryHandler(zimmer_callback, pattern="^zimmer_")],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("pause", pause))
    app.job_queue.run_repeating(scraper_job, interval=900, first=10)

    logger.info("TheHungerRents is running 🏹")
    app.run_polling()


if __name__ == "__main__":
    main()
