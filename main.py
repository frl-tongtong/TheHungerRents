import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler
)
from supabase import create_client
from scraper import run_scraper

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Supabase
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Telegram Token
TOKEN = os.environ["TELEGRAM_TOKEN"]

# Conversation states
BEZIRK, BUDGET, ZIMMER = range(3)

BEZIRKE = [
    "Alle", "Mitte", "Prenzlauer Berg / Pankow",
    "Friedrichshain-Kreuzberg", "Neukölln",
    "Tempelhof-Schöneberg", "Charlottenburg-Wilmersdorf"
]

BUDGETS = ["bis 800€", "bis 1.000€", "bis 1.200€", "kein Limit"]
ZIMMER = ["1+", "2+", "3+", "egal"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🏠 Willkommen bei *TheHungerRents*, {user.first_name}!\n\n"
        "Ich durchsuche Berliner Hausverwaltungsseiten nach neuen Wohnungen "
        "und schicke dir sofort eine Nachricht wenn etwas Passendes auftaucht.\n\n"
        "Lass uns kurz deine Präferenzen einstellen. Welche Bezirke interessieren dich?",
        parse_mode="Markdown"
    )
    keyboard = [[InlineKeyboardButton(b, callback_data=f"bezirk:{b}")] for b in BEZIRKE]
    await update.message.reply_text(
        "👇 Wähle einen oder mehrere Bezirke:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data["bezirke"] = []
    return BEZIRK


async def bezirk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bezirk = query.data.split(":")[1]

    if bezirk == "Alle":
        context.user_data["bezirke"] = ["Alle"]
    else:
        if "Alle" in context.user_data["bezirke"]:
            context.user_data["bezirke"] = []
        if bezirk in context.user_data["bezirke"]:
            context.user_data["bezirke"].remove(bezirk)
        else:
            context.user_data["bezirke"].append(bezirk)

    selected = context.user_data["bezirke"]
    keyboard = []
    for b in BEZIRKE:
        label = f"✅ {b}" if b in selected else b
        keyboard.append([InlineKeyboardButton(label, callback_data=f"bezirk:{b}")])
    keyboard.append([InlineKeyboardButton("➡️ Weiter", callback_data="bezirk:done")])

    await query.edit_message_text(
        f"Ausgewählt: {', '.join(selected) if selected else 'nichts'}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BEZIRK


async def bezirk_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton(b, callback_data=f"budget:{b}")] for b in BUDGETS]
    await query.edit_message_text(
        "💶 Was ist dein maximales Budget (Warmmiete)?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BUDGET


async def budget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["budget"] = query.data.split(":")[1]
    keyboard = [[InlineKeyboardButton(z, callback_data=f"zimmer:{z}")] for z in ZIMMER]
    await query.edit_message_text(
        "🚪 Wie viele Zimmer brauchst du mindestens?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ZIMMER


async def zimmer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["zimmer"] = query.data.split(":")[1]

    user_id = str(update.effective_user.id)
    prefs = {
        "user_id": user_id,
        "bezirke": context.user_data.get("bezirke", ["Alle"]),
        "budget": context.user_data.get("budget", "kein Limit"),
        "zimmer": context.user_data.get("zimmer", "egal"),
        "active": True
    }

    # Upsert in Supabase
    supabase.table("user_preferences").upsert(prefs).execute()

    await query.edit_message_text(
        "✅ *Alles gespeichert!*\n\n"
        f"📍 Bezirke: {', '.join(prefs['bezirke'])}\n"
        f"💶 Budget: {prefs['budget']}\n"
        f"🚪 Zimmer: {prefs['zimmer']}\n\n"
        "Ich halte jetzt die Augen offen und melde mich sobald etwas passt. "
        "Der Kampf ums Wohnen beginnt! 🏹\n\n"
        "Mit /einstellungen kannst du deine Präferenzen jederzeit ändern.\n"
        "Mit /pause kannst du Benachrichtigungen pausieren.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def einstellungen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bezirke"] = []
    await update.message.reply_text("🔧 Lass uns deine Einstellungen aktualisieren!")
    keyboard = [[InlineKeyboardButton(b, callback_data=f"bezirk:{b}")] for b in BEZIRKE]
    await update.message.reply_text(
        "Welche Bezirke interessieren dich?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BEZIRK


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    result = supabase.table("user_preferences").select("active").eq("user_id", user_id).execute()
    if result.data:
        current = result.data[0]["active"]
        new_state = not current
        supabase.table("user_preferences").update({"active": new_state}).eq("user_id", user_id).execute()
        if new_state:
            await update.message.reply_text("▶️ Benachrichtigungen wieder aktiv!")
        else:
            await update.message.reply_text("⏸️ Benachrichtigungen pausiert. Mit /pause wieder aktivieren.")
    else:
        await update.message.reply_text("Du hast noch keine Einstellungen. Starte mit /start!")


async def scraper_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 15 minutes to check for new listings."""
    logger.info("Running scraper...")
    new_listings = await run_scraper(supabase)

    if not new_listings:
        logger.info("No new listings found.")
        return

    # Get all active users
    users = supabase.table("user_preferences").select("*").eq("active", True).execute()

    for user in users.data:
        user_id = user["user_id"]
        bezirke = user["bezirke"]
        budget_str = user["budget"]
        zimmer_str = user["zimmer"]

        # Parse budget
        budget_map = {"bis 800€": 800, "bis 1.000€": 1000, "bis 1.200€": 1200, "kein Limit": 99999}
        max_budget = budget_map.get(budget_str, 99999)

        # Parse zimmer
        zimmer_map = {"1+": 1, "2+": 2, "3+": 3, "egal": 0}
        min_zimmer = zimmer_map.get(zimmer_str, 0)

        for listing in new_listings:
            # Filter by Bezirk
            if "Alle" not in bezirke:
                if not any(b.lower() in listing.get("bezirk", "").lower() for b in bezirke):
                    continue

            # Filter by budget
            if listing.get("preis") and listing["preis"] > max_budget:
                continue

            # Filter by Zimmer
            if listing.get("zimmer") and min_zimmer > 0 and listing["zimmer"] < min_zimmer:
                continue

            # Send notification
            msg = (
                f"🏠 *Neue Wohnung gefunden!*\n\n"
                f"📍 {listing.get('bezirk', 'Unbekannt')}\n"
                f"🚪 {listing.get('zimmer', '?')} Zimmer\n"
                f"💶 {listing.get('preis', '?')}€ warm\n"
                f"📐 {listing.get('groesse', '?')} m²\n"
                f"🏢 {listing.get('anbieter', '?')}\n\n"
                f"🔗 [Zur Wohnung]({listing.get('url', '')})"
            )
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode="Markdown",
                    disable_web_page_preview=False
                )
            except Exception as e:
                logger.error(f"Could not send to {user_id}: {e}")


def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("einstellungen", einstellungen)
        ],
        states={
            BEZIRK: [
                CallbackQueryHandler(bezirk_done, pattern="^bezirk:done$"),
                CallbackQueryHandler(bezirk_handler, pattern="^bezirk:")
            ],
            BUDGET: [CallbackQueryHandler(budget_handler, pattern="^budget:")],
            ZIMMER: [CallbackQueryHandler(zimmer_handler, pattern="^zimmer:")],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("pause", pause))

    # Run scraper every 15 minutes
    app.job_queue.run_repeating(scraper_job, interval=900, first=10)

    logger.info("TheHungerRents Bot is running... 🏹")
    app.run_polling()


if __name__ == "__main__":
    main()
