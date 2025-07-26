import os
import json
import time
import logging
import requests
import pandas as pd
import ta
import datetime
import matplotlib.pyplot as plt
from binance.client import Client
from dotenv import load_dotenv
import telegram
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Load config
with open("config.json") as f:
    config = json.load(f)

symbols = config["symbols"]
settings = config["settings"]

# ✅ Replit secret usage
telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

spreadsheet_id = os.getenv("SPREADSHEET_ID")

# Setup clients
client = Client(api_key, api_secret)
bot = telegram.Bot(token=telegram_bot_token)

scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gsheet = gspread.authorize(creds)

# Utility functions
def get_klines(symbol, interval, lookback):
    try:
        data = client.get_klines(symbol=symbol, interval=interval, limit=lookback)
        df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume','close_time','qav','num_trades','taker_base_vol','taker_quote_vol','ignore'])
        df['close'] = pd.to_numeric(df['close'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['open'] = pd.to_numeric(df['open'])
        df['volume'] = pd.to_numeric(df['volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Error fetching klines for {symbol}: {e}")
        return None

def send_telegram_message(message):
    try:
        bot.send_message(chat_id=telegram_chat_id, text=message)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

# Example signal checker
def check_signal(symbol):
    df = get_klines(symbol, '15m', 100)
    if df is None:
        return

    try:
        # Indicators
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        df['ema'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
        df['macd'] = ta.trend.MACD(df['close']).macd_diff()

        last_rsi = df['rsi'].iloc[-1]
        last_ema = df['ema'].iloc[-1]
        last_macd = df['macd'].iloc[-1]
        last_price = df['close'].iloc[-1]

        signal = None
        if last_rsi < 30 and last_macd > 0 and last_price > last_ema:
            signal = "BUY"
        elif last_rsi > 70 and last_macd < 0 and last_price < last_ema:
            signal = "SELL"

        logger.info(f"{symbol} signal: {signal}, RSI: {last_rsi:.2f}, EMA: {last_ema:.2f}, MACD: {last_macd:.4f}")

        if signal:
            msg = f"{symbol} SIGNAL: {signal}\nPrice: {last_price}\nRSI: {last_rsi:.2f}\nMACD: {last_macd:.4f}\nEMA20: {last_ema:.2f}"
            send_telegram_message(msg)

            # Plot chart
            plt.figure(figsize=(10, 5))
            plt.plot(df['timestamp'], df['close'], label='Price')
            plt.plot(df['timestamp'], df['ema'], label='EMA20')
            plt.title(f"{symbol} Signal: {signal}")
            plt.legend()
            plt.grid()
            filename = f"chart_{symbol}.png"
            plt.savefig(filename)
            plt.close()

            with open(filename, 'rb') as photo:
                bot.send_photo(chat_id=telegram_chat_id, photo=photo)
    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")

# Main loop
while True:
    for symbol in symbols:
        check_signal(symbol)
    time.sleep(settings.get("loop_interval", 60))
