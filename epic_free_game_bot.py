import os
import requests
import json
import threading
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
SEEN_FILE = "seen_games.json"

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
    return "Bot is running with Auto-Notifications and Images!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- DATA FETCHING (Now with Image & Slug Support) ---
def get_epic_games_rich():
    try:
        URL = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
        resp = requests.get(URL, timeout=20)
        data = resp.json()
        
        elements = data["data"]["Catalog"]["searchStore"]["elements"]
        current_list, upcoming_list = [], []
        
        for game in elements:
            title = game.get("title", "Unknown Game")
            promos = game.get("promotions")
            if not promos: continue

            # --- EXTRACT IMAGE ---
            image_url = None
            for img in game.get("keyImages", []):
                # Prioritize high-quality wide images or thumbnails
                if img.get("type") in ["OfferImageWide", "Thumbnail", "DieselStoreFrontWide"]:
                    image_url = img.get("url")
                    break

            # --- FIND SLUG ---
            slug = game.get("productSlug") or game.get("urlSlug")
            if not slug and game.get("catalogNs", {}).get("mappings"):
                slug = game["catalogNs"]["mappings"][0].get("pageSlug")
            
            clean_url = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://store.epicgames.com/en-US/free-games"

            # --- CURRENT OFFERS ---
            curr_offers = promos.get("promotionalOffers", [])
            for group in curr_offers:
                for offer in group.get("promotionalOffers", []):
                    if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                        current_list.append({
                            "title": title,
                            "desc": (game.get("description", "") or "")[:150],
                            "url": clean_url,
                            "image": image_url,
                            "original": game.get("price", {}).get("totalPrice", {}).get("fmtPrice", {}).get("originalPrice", "???"),
                            "end": offer.get("endDate", "")[:10]
                        })

            # --- UPCOMING OFFERS ---
            up_offers = promos.get("upcomingPromotionalOffers", [])
            for group in up_offers:
                for offer in group.get("promotionalOffers", []):
                    if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                        upcoming_list.append({
                            "title": title,
                            "start": offer.get("startDate", "")[:10]
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
                price_text = f"<s>{game['original']}</s> → <b>FREE</b>"
                msg = (f"🎮 <b>New FREE Game Alert!</b>\n\n"
                       f"🕹 <b>{game['title']}</b> {price_text}\n"
                       f"🗓 Free until: {game['end']}\n\n"
                       f"📖 {game['desc']}...")
                
                keyboard = [
                    [InlineKeyboardButton("🚀 Claim Now", url=game['url'])],
                    [InlineKeyboardButton("📢 Share with Friends", url=f"https://t.me/share/url?url={game['url']}&text=Get {game['title']} for FREE on Epic Games!")]
                ]
                
                # Send with image if available
                if game['image']:
                    await application.bot.send_photo(chat_id=CHAT_ID, photo=game['image'], caption=msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
                
                seen.add(game['title'])
                new_found = True
        
        if new_found:
            save_seen_games(seen)
        
        await asyncio.sleep(3600)

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎮 Current Free Games", callback_data='get_games')],
        [InlineKeyboardButton("⏭ Upcoming Games", callback_data='get_next')],
        [InlineKeyboardButton("🛠 Help & Info", callback_data='help_info')]
    ]
    await update.message.reply_text(
        "👋 <b>Epic Games Notifier</b>\n\nI track free games so you never miss a claim! Use the buttons below to check the store.", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='HTML'
    )

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Manual scan initiated... checking for new freebies.")
    # This triggers the same logic as auto-check but immediately
    current, _ = get_epic_games_rich()
    await update.message.reply_text(f"Done! Found {len(current)} current free games.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current, upcoming = get_epic_games_rich()

    if query.data == 'get_games':
        if not current:
            await query.message.reply_text("Currently no free games found.")
            return
        for game in current:
            price_text = f"<s>{game['original']}</s> → <b>FREE</b>"
            msg = f"🎮 <b>{game['title']}</b> {price_text}\n🗓 Until: {game['end']}\n\n🔗 <a href='{game['url']}'>Claim here</a>"
            
            keyboard = [[InlineKeyboardButton("🎮 View Game", url=game['url'])]]
            
            if game['image']:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=game['image'], caption=msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'get_next':
        text = "⏭ <b>Upcoming Deals:</b>\n\n" + "\n".join([f"• <b>{g['title']}</b>\n  📅 Starts: {g['start']}\n" for g in upcoming])
        await query.message.reply_text(text, parse_mode='HTML')

    elif query.data == 'help_info':
        help_text = (
            "<b>Bot Commands:</b>\n"
            "/start - Main Menu\n"
            "/check - Force manual scan\n\n"
            "The bot automatically posts new free games to your designated channel every hour."
        )
        await query.message.reply_text(help_text, parse_mode='HTML')

# --- MAIN ---
async def start_bot():
    threading.Thread(target=run_flask, daemon=True).start()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    await application.initialize()
    await application.start()
    
    asyncio.create_task(auto_check(application))
    
    await application.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
