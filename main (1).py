import time
import json
import logging
import gspread
import requests
import pandas as pd
import ta
import datetime
from binance.client import Client
from oauth2client.service_account import ServiceAccountCredentials
from apscheduler.schedulers.background import BackgroundScheduler

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load config
with open("config.json") as f:
    config = json.load(f)

symbols = config["symbols"]
settings = config["settings"]
api = config["api"]
telegram = config["telegram"]

# Telegram Bot
def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{telegram['bot_token']}/sendMessage"
        payload = {"chat_id": telegram['chat_id'], "text": message}
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            raise Exception(response.text)
    except Exception as e:
        logging.error(f"❌ Telegram failed [{response.status_code if 'response' in locals() else 'NO RESPONSE'}]: {e}")

# Authenticate Google Sheets
try:
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client_gsheets = gspread.authorize(creds)
    spreadsheet = client_gsheets.open_by_key(settings["spreadsheet_id"])
    logging.info("✅ Google Sheets authentication successful!")
except Exception as e:
    logging.error(f"Google Sheets authentication failed: {e}")

# Binance Client
client = Client(api["binance_api_key"], api["binance_api_secret"])

# Track last trade times
last_trade_time = {symbol: datetime.datetime.now() for symbol in symbols}

# Core Trading Logic
def run_bot_loop():
    for symbol in symbols:
        try:
            df = get_klines(symbol)
            signal = generate_signal(df)
            if signal:
                execute_trade(symbol, signal)
                last_trade_time[symbol] = datetime.datetime.now()
        except Exception as e:
            logging.error(f"Error in trading loop for {symbol}: {e}")

def get_klines(symbol):
    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=100)
    df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "num_trades", "taker_buy_base", "taker_buy_quote", "ignore"])
    df["close"] = pd.to_numeric(df["close"])
    df["rsi"] = ta.momentum.RSIIndicator(df["close"]).rsi()
    df["ema"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
    return df

def generate_signal(df):
    latest = df.iloc[-1]
    if latest['rsi'] < 30 and latest['close'] > latest['ema']:
        return "BUY"
    elif latest['rsi'] > 70 and latest['close'] < latest['ema']:
        return "SELL"
    return None

def execute_trade(symbol, signal):
    logging.info(f"🔁 {signal} signal for {symbol}")
    send_telegram_message(f"🔁 {signal} signal for {symbol} at {datetime.datetime.now().strftime('%H:%M:%S')}.")
    try:
        worksheet = spreadsheet.worksheet(symbol)
        worksheet.append_row([str(datetime.datetime.now()), signal])
    except Exception as e:
        logging.error(f"Google Sheets logging failed: {e}")

# Alert if no trades happened in X hours
def check_no_trade_alert():
    now = datetime.datetime.now()
    for symbol in symbols:
        elapsed = now - last_trade_time[symbol]
        if elapsed.total_seconds() > settings.get("no_trade_alert_hours", 3) * 3600:
            send_telegram_message(f"⚠️ No trade for {symbol} in the last {elapsed.total_seconds() // 3600:.0f} hours.")

# Daily summary (placeholder)
def send_daily_summary_to_telegram():
    send_telegram_message("📊 Daily summary will be here.")

# Weekly summary (placeholder)
def send_weekly_summary():
    send_telegram_message("📈 Weekly summary will be here.")

# Run scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(run_bot_loop, 'interval', minutes=15)
scheduler.add_job(send_daily_summary_to_telegram, 'cron', hour=23, minute=55)
scheduler.add_job(send_weekly_summary, 'cron', day_of_week='sun', hour=23, minute=59)
scheduler.add_job(check_no_trade_alert, 'interval', hours=1)
scheduler.start()

# Notify bot start
send_telegram_message("🚀 Bot started and running...")

# Keep running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logging.info("🛑 Bot stopped.")
