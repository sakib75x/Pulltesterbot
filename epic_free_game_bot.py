import os
import requests
import json
import threading
import time
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")
if not CHAT_ID:
    raise ValueError("No CHAT_ID found in environment variables!")

# --- DATABASE LOGIC ---
def load_seen_games():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen_games(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# --- WEB SERVER (For Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running with Auto-Notifications!"

def run_flask():
    # Render provides the PORT environment variable automatically
    port = int(os.environ.get("PORT", 5000))
    # Use 0.0.0.0 to be accessible externally
    app.run(host='0.0.0.0', port=port)

# --- DATA FETCHING ---
def get_epic_games_rich():
    try:
        # Use the base promotional URL
        URL = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
        resp = requests.get(URL, timeout=20)
        data = resp.json()
        
        elements = data["data"]["Catalog"]["searchStore"]["elements"]
        current_list, upcoming_list = [], []
        
        for game in elements:
            title = game.get("title", "Unknown Game")
            promos = game.get("promotions")
            if not promos: continue

            # --- FIND THE URL SLUG (The tricky part) ---
            # Epic stores this in about 4 different possible places
            slug = None
            if game.get("productSlug"):
                slug = game.get("productSlug")
            elif game.get("urlSlug"):
                slug = game.get("urlSlug")
            elif game.get("catalogNs", {}).get("mappings"):
                # Sometimes it's buried in mappings
                mappings = game["catalogNs"]["mappings"]
                if mappings:
                    slug = mappings[0].get("pageSlug")
            
            clean_url = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://store.epicgames.com/en-US/free-games"

            # --- CHECK CURRENT OFFERS ---
            curr_offers = promos.get("promotionalOffers", [])
            for group in curr_offers:
                for offer in group.get("promotionalOffers", []):
                    if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                        end_date = offer.get("endDate", "Soon")[:10]
                        price_data = game.get("price", {}).get("totalPrice", {}).get("fmtPrice", {})
                        original = price_data.get("originalPrice", "???")
                        
                        current_list.append({
                            "title": title,
                            "desc": (game.get("description", "") or "")[:150],
                            "url": clean_url,
                            "original": original,
                            "end": end_date
                        })

            # --- CHECK UPCOMING OFFERS ---
            up_offers = promos.get("upcomingPromotionalOffers", [])
            for group in up_offers:
                for offer in group.get("promotionalOffers", []):
                    if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                        start_date = offer.get("startDate", "Unknown")[:10]
                        upcoming_list.append({
                            "title": title,
                            "start": start_date
                        })
                        
        return current_list, upcoming_list
    except Exception as e:
        print(f"API Error: {e}")
        return [], []

# --- AUTO-NOTIFICATION LOGIC ---
async def auto_check(application):
    while True:
        print("Checking for new games...")
        current, _ = get_epic_games_rich()
        seen = load_seen_games()
        new_found = False
        
        for game in current:
            if game['title'] not in seen:
                price_text = f"<s>{game['original']}</s> → <b>FREE</b>" if game['original'] else "<b>FREE</b>"
                msg = (f"🎮 <b>New FREE Game Alert!</b>\n\n"
                       f"🕹 <b>{game['title']}</b> {price_text}\n"
                       f"🗓 Free until: {game['end']}\n\n"
                       f"📖 {game['desc']}...\n\n"
                       f"🔗 <a href='{game['url']}'>Claim Now →</a>")
                await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML')
                seen.add(game['title'])
                new_found = True
        
        if new_found:
            save_seen_games(seen)
        
        await asyncio.sleep(3600) # Wait 1 hour before checking again

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🎮 Current Free Games", callback_data='get_games')],
                [InlineKeyboardButton("⏭ Upcoming Games", callback_data='get_next')]]
    await update.message.reply_text("👋 <b>Epic Free Games Bot</b>\nInstant check or wait for auto-alerts!", 
                                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    current, upcoming = get_epic_games_rich()
    if update.callback_query.data == 'get_games':
        for game in current:
            price_text = f"<s>{game['original']}</s> → <b>FREE</b>" if game['original'] else "<b>FREE</b>"
            msg = f"🎮 <b>{game['title']}</b> {price_text}\n🗓 Until: {game['end']}\n\n🔗 <a href='{game['url']}'>Claim →</a>"
            await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=msg, parse_mode='HTML')
    elif update.callback_query.data == 'get_next':
        text = "⏭ <b>Upcoming:</b>\n" + "\n".join([f"• {g['title']} ({g['start']})" for g in upcoming])
        await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=text, parse_mode='HTML')

# --- MAIN ---
async def start_bot():
    # 1. Start the Flask server in a separate thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # 2. Build the Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 3. Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # 4. Initialize the application
    await application.initialize()
    await application.start()
    
    # 5. Start the auto-checker task
    asyncio.create_task(auto_check(application))
    
    # 6. Run the bot polling
    await application.updater.start_polling()
    
    # Keep the bot running
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
