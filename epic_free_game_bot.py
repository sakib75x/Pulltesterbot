import os
import requests
import asyncio
import threading
from flask import Flask
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIGURATION (Environment Variables) ---
# These are pulled from Render's Environment Settings for security
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
EPIC_API_URL = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"

app = Flask(__name__)

# --- FLASK SERVER (For Health Checks & Cron-job) ---
@app.route('/')
def home():
    # Minimal output to keep Cron-job.org happy and green
    return "OK", 200

def run_flask():
    # Render uses port 10000 by default
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- EPIC GAMES LOGIC ---
def get_free_games():
    try:
        response = requests.get(EPIC_API_URL, timeout=10)
        data = response.json()
        games = data['data']['Catalog']['searchStore']['elements']
        
        current_games = []
        upcoming_games = []
        
        for game in games:
            promotions = game.get('promotions')
            if not promotions:
                continue
                
            # Check for active free games
            active_promos = promotions.get('promotionalOffers')
            if active_promos and active_promos[0]['promotionalOffers']:
                current_games.append(game)
                
            # Check for upcoming free games
            upcoming_promos = promotions.get('upcomingPromotionalOffers')
            if upcoming_promos and upcoming_promos[0]['promotionalOffers']:
                upcoming_games.append(game)
                
        return current_games, upcoming_games
    except Exception as e:
        print(f"Error fetching games: {e}")
        return [], []

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎮 Current Free Games", callback_query_data='current')],
        [InlineKeyboardButton("⏳ Upcoming Games", callback_query_data='upcoming')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Click a button to check Epic Games Store freebies:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    current, upcoming = get_free_games()
    
    if query.data == 'current':
        text = "<b>🌟 Current Free Games:</b>\n\n"
        for g in current:
            text += f"▪️ {g['title']}\n🔗 <a href='https://store.epicgames.com/en-US/p/{g['catalogNs']['mappings'][0]['pageSlug']}'>Claim Here</a>\n\n"
    else:
        text = "<b>⏳ Upcoming Free Games:</b>\n\n"
        for g in upcoming:
            text += f"▪️ {g['title']} (Coming Soon)\n"
            
    await query.edit_message_text(text=text, parse_mode='HTML', disable_web_page_preview=False)

# --- AUTO-CHECKER TASK ---
async def auto_check(application: Application):
    # This keeps track of games already notified (in memory for simplicity)
    last_notified = set()
    
    while True:
        current, _ = get_free_games()
        for game in current:
            game_id = game['id']
            if game_id not in last_notified:
                message = f"🚨 <b>NEW FREE GAME!</b>\n\n<b>{game['title']}</b> is now FREE on Epic Games!\n\n🔗 <a href='https://store.epicgames.com/en-US/p/{game['catalogNs']['mappings'][0]['pageSlug']}'>Claim Now</a>"
                await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='HTML')
                last_notified.add(game_id)
        
        # Check every hour
        await asyncio.sleep(3600)

# --- MAIN RUNNER (Python 3.14+ Fix) ---
async def start_bot():
    # 1. Start Flask in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # 2. Setup Bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # 3. Initialize & Start
    await application.initialize()
    await application.start()
    
    # 4. Start Background Task
    asyncio.create_task(auto_check(application))
    
    # 5. Run Polling
    await application.updater.start_polling()
    print("🚀 Bot is live and listening...")
    
    # Keep main task alive
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
