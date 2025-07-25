import os
import json
import time
import logging
import requests
import gspread
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from binance.client import Client
from oauth2client.service_account import ServiceAccountCredentials
import sys

# === Logging: Log to console + file ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log")
    ]
)

# === Load Secrets from Replit Environment ===
BINANCE_API_KEY = os.environ["BINANCE_API_KEY"]
BINANCE_API_SECRET = os.environ["BINANCE_API_SECRET"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

# === Google Sheets Setup ===
scope = ["https://www.googleapis.com/auth/spreadsheets"]
credentials_dict = json.loads(os.environ["GOOGLE_SHEETS_CREDENTIALS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
sheets_client = gspread.authorize(creds)
sheet = sheets_client.open_by_key(SPREADSHEET_ID)

# === Binance Client ===
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# === Telegram Message Helper ===
def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

# === Fetch OHLCV Data ===
def fetch_ohlcv(symbol, interval="15m", limit=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df['close'] = pd.to_numeric(df['close'])
        return df
    except Exception as e:
        logging.error(f"OHLCV Error for {symbol}: {e}")
        return pd.DataFrame()

# === Strategy: Check Buy Signal ===
def is_buy_signal(df):
    if df.empty:
        return False
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    ema = EMAIndicator(close=df['close'], window=21).ema_indicator()
    macd = MACD(close=df['close']).macd_diff()
    return rsi.iloc[-1] < 30 and df['close'].iloc[-1] > ema.iloc[-1] and macd.iloc[-1] > 0

# === Log Trade to Google Sheet ===
def log_trade(symbol, price, side):
    try:
        sheet_tab = sheet.worksheet(symbol)
    except gspread.exceptions.WorksheetNotFound:
        sheet_tab = sheet.add_worksheet(title=symbol, rows="1000", cols="5")
        sheet_tab.append_row(["Time", "Symbol", "Price", "Side"])

    sheet_tab.append_row([
        time.strftime("%Y-%m-%d %H:%M:%S"),
        symbol, str(price), side
    ])

# === Execute Trade ===
def execute_trade(symbol, price, side):
    message = f"{side} Signal for {symbol} at {price}"
    send_telegram_message(message)
    log_trade(symbol, price, side)
    logging.info(message)

# === Main Loop ===
def run_bot():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    while True:
        logging.info("🔁 Starting new iteration of signal check...")
        for symbol in symbols:
            logging.info(f"📊 Checking {symbol}")
            df = fetch_ohlcv(symbol)
            if is_buy_signal(df):
                price = df['close'].iloc[-1]
                execute_trade(symbol, price, "BUY")
        logging.info("⏸️ Waiting 5 minutes...\n")
        time.sleep(300)

# === Entry Point ===
if __name__ == "__main__":
    send_telegram_message("🚀 Bot Started Successfully!")

    try:
        balance = client.get_asset_balance(asset='USDT')
        logging.info(f"💰 USDT Balance: {balance['free']}")
    except Exception as e:
        logging.error(f"❌ Error fetching balance: {e}")

    run_bot()
