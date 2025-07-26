import time
import json
import logging
import gspread
import requests
import pandas as pd
import ta
import datetime
from binance.client import Client
from apscheduler.schedulers.background import BackgroundScheduler
from oauth2client.service_account import ServiceAccountCredentials

# ⏱️ Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Load settings from config.json
with open("config.json") as f:
    config = json.load(f)

settings = config["settings"]
symbols = config["symbols"]

# ✅ Setup Binance client
binance_client = Client(settings["api_key"], settings["api_secret"]) if "api_key" in settings else None

# ✅ Setup Google Sheets
gs_client = None
spreadsheet = None
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    gs_client = gspread.authorize(creds)
    spreadsheet = gs_client.open_by_key(settings["spreadsheet_id"])
    logging.info("✅ Google Sheets authentication successful!")
except Exception as e:
    logging.error(f"❌ Google Sheets authentication failed: {e}")
    spreadsheet = None

# ✅ Telegram config
TELEGRAM_TOKEN = config["telegram"]["token"]
TELEGRAM_CHAT_ID = config["telegram"]["chat_id"]

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            logging.error(f"❌ Telegram failed [{response.status_code}]: {response.text}")
        else:
            logging.info("📨 Telegram message sent successfully.")
    except Exception as e:
        logging.error(f"❌ Telegram exception: {e}")

# ✅ Example function to check signals (RSI, EMA, MACD logic goes here)
def check_signals():
    logging.info("🔁 Checking signals for all symbols... (logic placeholder)")
    # Your real trading logic goes here

# ✅ Daily P&L summary
def send_daily_summary_to_telegram():
    if spreadsheet:
        try:
            summary_sheet = spreadsheet.worksheet("Daily Summary")
            rows = summary_sheet.get_all_values()
            if len(rows) > 1:
                today = datetime.datetime.now().strftime("%Y-%m-%d")
                today_data = [row for row in rows if row[0] == today]
                if today_data:
                    last = today_data[-1]
                    profit = last[1] if len(last) > 1 else "0"
                    send_telegram(f"📊 *Daily P&L Summary ({today})*\nProfit/Loss: {profit} USDT")
        except Exception as e:
            logging.error(f"❌ Daily summary error: {e}")

# ✅ Weekly P&L summary
def send_weekly_summary():
    if spreadsheet:
        try:
            summary_sheet = spreadsheet.worksheet("Daily Summary")
            df = pd.DataFrame(summary_sheet.get_all_records())
            if not df.empty:
                last_week = df.tail(7)
                total = last_week["Profit/Loss"].astype(float).sum()
                send_telegram(f"📈 *Weekly Summary*\n7-day P&L: {total:.2f} USDT")
        except Exception as e:
            logging.error(f"❌ Weekly summary error: {e}")

# ✅ Real-time trading loop
def run_bot_loop():
    logging.info(f"🚀 Bot started. Real-time interval = {settings['interval_minutes']} mins.")
    check_signals()

# ✅ Scheduler
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
scheduler.add_job(run_bot_loop, "interval", minutes=settings["interval_minutes"])
scheduler.add_job(send_daily_summary_to_telegram, "cron", hour=23, minute=59)
scheduler.add_job(send_weekly_summary, "cron", day_of_week="sun", hour=23, minute=59)
scheduler.start()

# ✅ Send startup message
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
logging.info("📨 Sending bot start message to Telegram...")
send_telegram(f"🤖 Bot started at {now} and is monitoring trades every {settings['interval_minutes']} minutes.")

# 🕒 Keep alive
try:
    while True:
        time.sleep(60)
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
    logging.info("🛑 Bot stopped.")
